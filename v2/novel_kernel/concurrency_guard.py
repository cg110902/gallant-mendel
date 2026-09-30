"""M6.8 executable concurrency conflict and resource-guard probe."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .events import EventLog, ParentConflictError, ResourceGuardError, build_event
from .projection import ProjectionStore
from .storage import atomic_write_json, sha256_bytes, sha256_json


@dataclass(frozen=True)
class ConcurrencyReport:
    ok: bool
    schema_version: str
    winner_count: int
    conflict_count: int
    lock_timeout_exit_code: int
    parent_conflict_exit_code: int
    silent_overwrite: bool
    report_hash: str


def _event(event_id: str, parent: str | None, actor: str, *, story_seq: int = 1) -> dict[str, Any]:
    return build_event(
        event_id=event_id,
        event_type="audit.completed",
        book_id="book_concurrency",
        branch_id="main",
        parent_event_id=parent,
        story_seq=story_seq,
        recorded_at="2026-09-30T00:00:00+00:00",
        actor_type="human",
        actor_id=actor,
        source_run_id=f"run_{actor}",
        payload={"probe": actor},
    )


class ConcurrencyGuardProbe:
    def run(self, book_root: Path | str, *, report_path: Path | str | None = None) -> ConcurrencyReport:
        book = Path(book_root)
        log = EventLog(book)
        log.initialize()
        root = _event("event_" + "0" * 31 + "1", None, "root")
        log.append(root)
        root_bytes = log.log_path.read_bytes()

        # Hold the real advisory lock and require a bounded contender to fail without writing.
        held = threading.Event()
        release = threading.Event()

        def holder() -> None:
            with log._locked():
                held.set()
                release.wait(5)

        owner = threading.Thread(target=holder, name="event-lock-holder")
        owner.start()
        if not held.wait(2):
            raise RuntimeError("lock holder did not acquire event-log lock")
        timeout_error: ResourceGuardError | None = None
        try:
            EventLog(book, lock_timeout=0.05).append(
                _event("event_" + "0" * 31 + "2", root["event_id"], "timeout")
            )
        except ResourceGuardError as exc:
            timeout_error = exc
        finally:
            release.set()
            owner.join(2)
        if owner.is_alive() or timeout_error is None:
            raise RuntimeError("bounded lock contention was not exposed")
        timeout_preserved = log.log_path.read_bytes() == root_bytes

        # Two valid candidates race from one parent. Lock serialization must yield one winner
        # and one explicit parent conflict; automatic reparenting would hide a lost update.
        barrier = threading.Barrier(3)
        candidates = (
            _event("event_" + "a" * 32, root["event_id"], "contender_a"),
            _event("event_" + "b" * 32, root["event_id"], "contender_b"),
        )
        outcomes: list[dict[str, Any]] = []
        outcome_lock = threading.Lock()

        def contender(candidate: dict[str, Any]) -> None:
            barrier.wait()
            try:
                EventLog(book, lock_timeout=2).append(candidate)
                result = {"event_id": candidate["event_id"], "outcome": "winner", "exit_code": 0}
            except ParentConflictError as exc:
                result = {
                    "event_id": candidate["event_id"],
                    "outcome": "parent_conflict",
                    "exit_code": exc.exit_code,
                    "error": str(exc),
                }
            with outcome_lock:
                outcomes.append(result)

        threads = [threading.Thread(target=contender, args=(candidate,)) for candidate in candidates]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(5)
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError("concurrent append did not terminate")

        outcomes.sort(key=lambda row: row["event_id"])
        winners = [row for row in outcomes if row["outcome"] == "winner"]
        conflicts = [row for row in outcomes if row["outcome"] == "parent_conflict"]
        verification = log.verify()
        events = log.read_events()
        winner_id = winners[0]["event_id"] if len(winners) == 1 else None
        silent_overwrite = not (
            len(winners) == 1
            and len(conflicts) == 1
            and len(events) == 2
            and verification.heads.get("main") == winner_id
            and conflicts[0]["exit_code"] == 7
        )
        projection = ProjectionStore(book).update(log)
        projected = ProjectionStore(book).verify(log)
        base = {
            "schema_version": "concurrency-guard-report.v1",
            "book_id": "book_concurrency",
            "lock_contention": {
                "timeout_seconds": 0.05,
                "outcome": "resource_guard",
                "exit_code": timeout_error.exit_code,
                "authority_bytes_unchanged": timeout_preserved,
                "error": str(timeout_error),
            },
            "same_parent_race": {
                "parent_event_id": root["event_id"],
                "contenders": list(candidates),
                "outcomes": outcomes,
                "winner_count": len(winners),
                "conflict_count": len(conflicts),
                "winner_event_id": winner_id,
            },
            "authority": {
                "event_count": verification.event_count,
                "head_event_id": verification.heads["main"],
                "log_hash": sha256_bytes(log.log_path.read_bytes()),
            },
            "projection": {
                "last_applied_event_id": projected.last_applied_event_id,
                "state_hash": projection.state_hash,
                "head_matches_authority": projected.last_applied_event_id == verification.heads["main"],
            },
            "silent_overwrite": silent_overwrite,
            "scope": {
                "single_book": True,
                "single_process_threads": True,
                "multi_process_tested": False,
                "distributed_lock_tested": False,
                "throughput_claim": False,
            },
        }
        report_hash = sha256_json(base)
        document = {**base, "report_hash": report_hash}
        if report_path is not None:
            destination = Path(report_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(destination, document)
        return ConcurrencyReport(
            ok=not silent_overwrite and timeout_preserved and projected.last_applied_event_id == winner_id,
            schema_version=base["schema_version"],
            winner_count=len(winners),
            conflict_count=len(conflicts),
            lock_timeout_exit_code=timeout_error.exit_code,
            parent_conflict_exit_code=conflicts[0]["exit_code"] if conflicts else -1,
            silent_overwrite=silent_overwrite,
            report_hash=report_hash,
        )
