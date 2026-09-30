"""M6.7 controlled thirty-chapter soak with outage and journal recovery."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .advisory_audit import AdvisoryAuditor
from .candidate_reconcile import CandidateReconciler
from .chapter_commit import ChapterCommitter
from .events import EventLog
from .extraction import CandidateExtractor
from .hard_audit import HardInvariantAuditor
from .production import ContextPackBuilder, ProductionPlanner
from .projection import ProjectionStore
from .snapshots import SnapshotManager
from .soft_audit import SoftAuditor
from .storage import atomic_write_json, sha256_file, sha256_json
from .temporal import TemporalStateQuery
from .three_chapter_smoke import _artifact_paths, _assert_published_run
from .writer_runtime import WriterRunController


@dataclass(frozen=True)
class SoakReport:
    ok: bool
    schema_version: str
    chapter_count: int
    authority_event_count: int
    fact_count: int
    snapshot_count: int
    interruption_recovered: bool
    silent_data_loss: bool
    report_hash: str


class ThirtyChapterSoak:
    """Run exactly thirty controlled chapters; this is not a throughput benchmark."""

    def run(
        self,
        book_root: Path | str,
        *,
        thresholds_path: Path | str,
        evaluated_at: str,
        prose_for_chapter: Callable[[int], str],
        restore_target: Path | str,
        interrupt: Callable[[Path, str], None],
        actor: str = "human.editor",
        report_path: Path | str | None = None,
    ) -> SoakReport:
        book = Path(book_root)
        initial_count = len(EventLog(book).read_events())
        started = time.monotonic()
        rows: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        interrupted = False

        for number in range(1, 31):
            chapter_id = f"ch_{number:03d}"
            plan = ProductionPlanner().plan(book, chapter_id=chapter_id)
            ContextPackBuilder().build(book, run_id=plan.run_id)
            writer = WriterRunController()
            writer.start_task(book, task_id=plan.task_id)
            run = Path(plan.run_path)
            (run / "prose.md").write_text(prose_for_chapter(number), encoding="utf-8")
            writer.request_review(book, run_id=plan.run_id)
            writer.decide_review(book, run_id=plan.run_id, decision="approve", actor="editor")
            CandidateExtractor().extract(book, run_id=plan.run_id)
            reconcile = CandidateReconciler().reconcile(book, run_id=plan.run_id)
            hard = HardInvariantAuditor().audit(book, run_id=plan.run_id)
            if reconcile.has_hard_violation or hard.has_hard_violation:
                raise RuntimeError(f"controlled soak produced a hard error: {chapter_id}")
            SoftAuditor().semantic(book, run_id=plan.run_id)
            SoftAuditor().style(book, run_id=plan.run_id)
            AdvisoryAuditor().audit(
                book, run_id=plan.run_id, thresholds_path=thresholds_path, evaluated_at=evaluated_at
            )
            SoftAuditor().gate(book, run_id=plan.run_id, decision="approve", actor="editor")

            if number == 20:
                try:
                    interrupt(book, plan.run_id)
                except Exception:
                    interrupted = True
                if not interrupted:
                    raise RuntimeError("chapter twenty fault injector did not interrupt commit")

            commit = ChapterCommitter().commit(book, run_id=plan.run_id, actor=actor)
            receipt = _assert_published_run(book, plan.run_id)
            request = json.loads((run / "request.json").read_text(encoding="utf-8"))
            rows.append(
                {
                    "chapter_id": chapter_id,
                    "run_id": plan.run_id,
                    "authority_parent": request["authority_head"],
                    "commit_head": commit.commit_head,
                    "event_count": len(commit.event_ids),
                    "chapter_hash": commit.chapter_hash,
                    "hard_error_count": hard.counts["hard"],
                    "advisory_finding_count": receipt["advisory"]["finding_count"],
                }
            )

            if number in {10, 20}:
                snapshot = SnapshotManager(book).create(
                    label=f"m6.7-after-{chapter_id}", artifact_paths=_artifact_paths(book)
                )
                snapshots.append(
                    {
                        "after_chapter": chapter_id,
                        "snapshot_id": snapshot.snapshot_id,
                        "head_event_id": snapshot.head_event_id,
                        "lineage_event_count": snapshot.lineage_event_count,
                        "projection_state_hash": snapshot.projection_state_hash,
                        "restored": number == 10,
                    }
                )
                if number == 10:
                    target = Path(restore_target)
                    SnapshotManager.restore(snapshot.path, target)
                    book = target

        log = EventLog(book)
        verification = log.verify()
        projection = ProjectionStore(book).verify(log)
        projected = ProjectionStore(book).export_state()
        temporal = TemporalStateQuery().query(book, as_of="ch_030")
        lineage = log.read_lineage("main")
        committed = [event for event in lineage if event["event_type"] == "chapter.committed"]
        expected_chapters = [f"ch_{number:03d}" for number in range(1, 31)]
        expected_added = sum(row["event_count"] for row in rows)
        run_receipts = [book / "runs" / row["run_id"] / "chapter-commit-report.json" for row in rows]
        chapter_files = sorted((book / "chapters").glob("ch_*.md"))
        loss_checks = {
            "authority_count_conserved": verification.event_count == initial_count + expected_added,
            "authority_chain_contiguous": all(
                rows[index]["authority_parent"] == rows[index - 1]["commit_head"]
                for index in range(1, 30)
            ),
            "chapter_count_conserved": len(chapter_files) == 30 and len(committed) == 30,
            "chapter_ids_conserved": [event["payload"]["chapter_id"] for event in committed[-30:]]
            == expected_chapters,
            "chapter_hashes_conserved": all(
                sha256_file(book / "chapters" / f"{row['chapter_id']}.md") == row["chapter_hash"]
                for row in rows
            ),
            "fact_count_conserved": len(temporal.facts) >= 30,
            "projection_facts_conserved": {item["fact_id"] for item in projected["facts"]}
            == {item["fact_id"] for item in temporal.facts},
            "projection_head_conserved": projection.last_applied_event_id == verification.heads["main"],
            "run_receipts_conserved": all(path.is_file() for path in run_receipts),
            "snapshot_heads_conserved": snapshots[0]["head_event_id"] == rows[9]["commit_head"]
            and snapshots[1]["head_event_id"] == rows[19]["commit_head"],
        }
        windows = []
        for start in (1, 11, 21):
            selected = rows[start - 1 : start + 9]
            errors = sum(row["hard_error_count"] for row in selected)
            windows.append(
                {
                    "start": f"ch_{start:03d}",
                    "end": f"ch_{start + 9:03d}",
                    "chapter_count": 10,
                    "error_count": errors,
                    "density": errors / 10,
                }
            )
        advisory_count = sum(row["advisory_finding_count"] for row in rows)
        silent_data_loss = not all(loss_checks.values())
        base = {
            "schema_version": "thirty-chapter-soak-report.v1",
            "book_id": temporal.book_id,
            "chapter_count": 30,
            "chapters": rows,
            "initial_authority_event_count": initial_count,
            "authority_event_count": verification.event_count,
            "authority_head": verification.heads["main"],
            "fact_count": len(temporal.facts),
            "snapshots": snapshots,
            "snapshot_count": len(snapshots),
            "outage_recovery": {"after_chapter": "ch_010", "restored_to_empty_target": True, "continued": True},
            "transaction_recovery": {
                "chapter": "ch_020",
                "interruption_observed": interrupted,
                "recovered": interrupted,
            },
            "ced": {
                "definition": "hard consistency errors per chapter in fixed non-overlapping ten-chapter windows",
                "window_size": 10,
                "windows": windows,
                "total_error_count": sum(window["error_count"] for window in windows),
                "overall_density": sum(window["error_count"] for window in windows) / 30,
                "advisory_findings_excluded": advisory_count,
            },
            "loss_checks": loss_checks,
            "silent_data_loss": silent_data_loss,
            "elapsed_seconds_observed": time.monotonic() - started,
            "scope": {
                "performance_threshold_applied": False,
                "concurrent_writers_tested": False,
                "challenge_false_negatives_changed": False,
                "hard_gate_promoted": False,
                "reliability_claim": "controlled thirty-chapter sequential soak only",
            },
        }
        report_hash = sha256_json(base)
        document = {**base, "report_hash": report_hash}
        if report_path is not None:
            destination = Path(report_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(destination, document)
        return SoakReport(
            ok=not silent_data_loss and interrupted,
            schema_version=base["schema_version"],
            chapter_count=30,
            authority_event_count=verification.event_count,
            fact_count=len(temporal.facts),
            snapshot_count=2,
            interruption_recovered=interrupted,
            silent_data_loss=silent_data_loss,
            report_hash=report_hash,
        )
