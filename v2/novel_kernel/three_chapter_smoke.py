"""M6.6 three-chapter continuity, recovery, and silent-data-loss smoke harness."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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
from .writer_runtime import WriterRunController


@dataclass(frozen=True)
class SmokeReport:
    ok: bool
    schema_version: str
    book_id: str
    chapter_count: int
    authority_event_count: int
    authority_head: str
    fact_count: int
    snapshot_id: str
    interruption_recovered: bool
    silent_data_loss: bool
    ced: dict[str, Any]
    report_hash: str


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _artifact_paths(book: Path) -> tuple[Path, ...]:
    """Select all continuation inputs while excluding snapshot core roots."""
    excluded = {"ledger", "state", "snapshots"}
    return tuple(
        path
        for path in sorted(book.rglob("*"))
        if path.is_file() and path.relative_to(book).parts[0] not in excluded
    )


def _assert_published_run(book: Path, run_id: str) -> dict[str, Any]:
    run = book / "runs" / run_id
    status = _read(run / "status.json")
    commit = _read(run / "chapter-commit-report.json")
    advisory = _read(run / "advisory-audit-report.json")
    if status.get("state") != "published":
        raise RuntimeError(f"run is not published: {run_id}")
    if status.get("commit_hash") != commit.get("commit_hash"):
        raise RuntimeError(f"commit report is not bound by status: {run_id}")
    if status.get("advisory_audit_hash") != advisory.get("advisory_audit_hash"):
        raise RuntimeError(f"advisory report is not bound by status: {run_id}")
    chapter = book / commit["chapter_path"]
    if not chapter.is_file() or sha256_file(chapter) != commit.get("chapter_hash"):
        raise RuntimeError(f"published chapter bytes are missing or changed: {run_id}")
    if advisory.get("advisory_only") is not True or advisory.get("blocking") is not False:
        raise RuntimeError(f"advisory authority boundary changed: {run_id}")
    return {"status": status, "commit": commit, "advisory": advisory}


class ThreeChapterSmoke:
    """Execute a frozen three-chapter pipeline against a prepared three-chapter book.

    ``interrupt`` is a verifier-only callback invoked immediately before chapter two's
    commit. It may fault-inject the journaled authority append; normal callers omit it.
    """

    def run(
        self,
        book_root: Path | str,
        *,
        thresholds_path: Path | str,
        evaluated_at: str,
        prose_by_chapter: dict[str, str],
        actor: str = "human.editor",
        interrupt: Callable[[Path, str], None] | None = None,
        restore_target: Path | str | None = None,
        report_path: Path | str | None = None,
    ) -> SmokeReport:
        book = Path(book_root)
        expected_chapters = ("ch_001", "ch_002", "ch_003")
        if tuple(prose_by_chapter) != expected_chapters:
            raise ValueError("prose_by_chapter must contain ch_001..ch_003 in order")
        initial_count = len(EventLog(book).read_events())
        rows: list[dict[str, Any]] = []
        interrupted = False
        snapshot = None

        for index, chapter_id in enumerate(expected_chapters, 1):
            plan = ProductionPlanner().plan(book, chapter_id=chapter_id)
            ContextPackBuilder().build(book, run_id=plan.run_id)
            writer = WriterRunController()
            writer.start_task(book, task_id=plan.task_id)
            run = Path(plan.run_path)
            (run / "prose.md").write_text(prose_by_chapter[chapter_id], encoding="utf-8")
            writer.request_review(book, run_id=plan.run_id)
            writer.decide_review(book, run_id=plan.run_id, decision="approve", actor="editor")
            CandidateExtractor().extract(book, run_id=plan.run_id)
            reconcile = CandidateReconciler().reconcile(book, run_id=plan.run_id)
            hard = HardInvariantAuditor().audit(book, run_id=plan.run_id)
            if hard.has_hard_violation or reconcile.has_hard_violation:
                raise RuntimeError(f"hard consistency failure in smoke chapter: {chapter_id}")
            SoftAuditor().semantic(book, run_id=plan.run_id)
            SoftAuditor().style(book, run_id=plan.run_id)
            AdvisoryAuditor().audit(
                book, run_id=plan.run_id, thresholds_path=thresholds_path, evaluated_at=evaluated_at
            )
            SoftAuditor().gate(book, run_id=plan.run_id, decision="approve", actor="editor")
            if index == 2 and interrupt is not None:
                try:
                    interrupt(book, plan.run_id)
                except Exception:
                    interrupted = True
                if not interrupted:
                    raise RuntimeError("fault injector did not interrupt chapter two commit")
            commit = ChapterCommitter().commit(book, run_id=plan.run_id, actor=actor)
            checked = _assert_published_run(book, plan.run_id)
            events = EventLog(book).read_events()
            event_map = {event["event_id"]: event for event in events}
            if any(event_id not in event_map for event_id in commit.event_ids):
                raise RuntimeError(f"commit report references missing authority: {chapter_id}")
            rows.append(
                {
                    "chapter_id": chapter_id,
                    "run_id": plan.run_id,
                    "authority_parent": _read(run / "request.json")["authority_head"],
                    "commit_head": commit.commit_head,
                    "event_ids": list(commit.event_ids),
                    "event_count": len(commit.event_ids),
                    "hard_error_count": hard.counts["hard"],
                    "advisory_finding_count": checked["advisory"]["finding_count"],
                    "chapter_hash": commit.chapter_hash,
                    "commit_hash": commit.commit_hash,
                }
            )
            if index == 2:
                snapshot = SnapshotManager(book).create(
                    label="m6.6-after-chapter-two", artifact_paths=_artifact_paths(book)
                )
                if restore_target is not None:
                    target = Path(restore_target)
                    SnapshotManager.restore(snapshot.path, target)
                    book = target

        if snapshot is None:
            raise RuntimeError("chapter-two snapshot was not created")
        log = EventLog(book)
        verified = log.verify()
        projection = ProjectionStore(book).verify(log)
        state = TemporalStateQuery().query(book, as_of="ch_003")
        projected_state = ProjectionStore(book).export_state()
        chapter_files = sorted((book / "chapters").glob("ch_*.md"))
        committed = [event for event in log.read_lineage("main") if event["event_type"] == "chapter.committed"]
        expected_added = sum(row["event_count"] for row in rows)
        loss_checks = {
            "authority_count_conserved": verified.event_count == initial_count + expected_added,
            "authority_chain_contiguous": all(
                rows[i]["authority_parent"] == rows[i - 1]["commit_head"] for i in range(1, 3)
            ),
            "chapter_count_conserved": len(chapter_files) == 3 and len(committed) == 3,
            "chapter_ids_conserved": [event["payload"]["chapter_id"] for event in committed[-3:]]
            == list(expected_chapters),
            "fact_count_conserved": len(state.facts) >= 3,
            "projection_head_conserved": projection.last_applied_event_id == verified.heads["main"],
            "projection_facts_conserved": {
                item["fact_id"] for item in projected_state["facts"]
            } == {item["fact_id"] for item in state.facts},
            "run_receipts_conserved": all((book / "runs" / row["run_id"] / "chapter-commit-report.json").is_file() for row in rows),
        }
        silent_data_loss = not all(loss_checks.values())
        ced = {
            "definition": "hard consistency errors per chapter in one fixed contiguous three-chapter window",
            "window_size": 3,
            "start": "ch_001",
            "end": "ch_003",
            "chapter_count": 3,
            "error_count": sum(row["hard_error_count"] for row in rows),
            "density": sum(row["hard_error_count"] for row in rows) / 3,
            "advisory_findings_excluded": sum(row["advisory_finding_count"] for row in rows),
        }
        base = {
            "schema_version": "three-chapter-smoke-report.v1",
            "book_id": state.book_id,
            "chapters": rows,
            "chapter_count": 3,
            "initial_authority_event_count": initial_count,
            "authority_event_count": verified.event_count,
            "authority_head": verified.heads["main"],
            "fact_count": len(state.facts),
            "snapshot": {
                "snapshot_id": snapshot.snapshot_id,
                "head_event_id": snapshot.head_event_id,
                "lineage_event_count": snapshot.lineage_event_count,
                "projection_state_hash": snapshot.projection_state_hash,
                "restored_before_chapter_three": restore_target is not None,
            },
            "transaction_recovery": {
                "interruption_injected": interrupt is not None,
                "interruption_observed": interrupted,
                "recovered": interrupt is None or interrupted,
            },
            "ced": ced,
            "loss_checks": loss_checks,
            "silent_data_loss": silent_data_loss,
            "scope": {
                "challenge_false_negatives_changed": False,
                "hard_gate_promoted": False,
                "reliability_claim": "three-chapter smoke only",
            },
        }
        report_hash = sha256_json(base)
        document = {**base, "report_hash": report_hash}
        if report_path is not None:
            destination = Path(report_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(destination, document)
        return SmokeReport(
            ok=not silent_data_loss,
            schema_version=base["schema_version"],
            book_id=state.book_id,
            chapter_count=3,
            authority_event_count=verified.event_count,
            authority_head=verified.heads["main"],
            fact_count=len(state.facts),
            snapshot_id=snapshot.snapshot_id,
            interruption_recovered=interrupt is None or interrupted,
            silent_data_loss=silent_data_loss,
            ced=ced,
            report_hash=report_hash,
        )
