"""Validated append-only event log for the core.v3 protocol.

M1.2 implements only Event Envelope validation, JSONL persistence, branch heads,
advisory process locking, and integrity checks. Domain objects and projections belong to
later M1 tasks.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .storage import atomic_write_json, canonical_json_bytes, sha256_json

EVENT_TYPES = frozenset(
    {
        "object.created",
        "object.renamed",
        "object.retired",
        "facet.asserted",
        "facet.superseded",
        "relation.asserted",
        "relation.invalidated",
        "fact.asserted",
        "fact.disputed",
        "obligation.created",
        "obligation.touched",
        "obligation.fulfilled",
        "obligation.deferred",
        "obligation.subverted",
        "obligation.retired",
        "knowledge.granted",
        "knowledge.retracted",
        "intent.registered",
        "reality.observed",
        "scene.committed",
        "chapter.committed",
        "state.reconciled",
        "audit.completed",
        "snapshot.created",
        "branch.created",
        "branch.merged",
    }
)
EVENT_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "book_id",
        "branch_id",
        "parent_event_id",
        "story_seq",
        "recorded_at",
        "actor_type",
        "actor_id",
        "source_run_id",
        "payload_hash",
        "payload",
        "evidence_refs",
        "supersedes",
    }
)
EVENT_ID_RE = re.compile(r"^event_[0-9a-f]{32}$")
BOOK_ID_RE = re.compile(r"^book_[a-z0-9][a-z0-9_-]{0,62}$")
BRANCH_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
ACTOR_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
RUN_ID_RE = re.compile(r"^run_[a-zA-Z0-9_.-]{1,120}$")
FORBIDDEN_ACTORS = frozenset({"writer", "extractor", "auditor", "librarian"})


class EventLogError(Exception):
    """Base class for event protocol and persistence errors."""


class EventValidationError(EventLogError):
    """An Event Envelope violates core.v3."""


class EventIntegrityError(EventLogError):
    """Persisted JSONL is malformed, truncated, reordered, or hash-invalid."""


class ParentConflictError(EventLogError):
    """An append did not name the current branch head."""

    exit_code = 7


class DuplicateEventError(EventLogError):
    """An event ID already exists in the authoritative log."""


class HeadMismatchError(EventLogError):
    """A derived branch-head file does not match authoritative JSONL."""


class ResourceGuardError(EventLogError):
    """The event-log lock could not be acquired within the allowed time."""

    exit_code = 7


class HeadUpdateError(EventLogError):
    """The event was appended but the derived head could not be updated."""


@dataclass(frozen=True)
class LogState:
    events: tuple[dict[str, Any], ...]
    heads: dict[str, str]
    event_ids: frozenset[str]
    book_id: str | None


@dataclass(frozen=True)
class AppendResult:
    event_id: str
    branch_id: str
    parent_event_id: str | None
    line_number: int
    byte_offset: int
    bytes_appended: int
    payload_hash: str


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    event_count: int
    branch_count: int
    heads: dict[str, str]
    book_id: str | None
    log_size: int


class _FileLock(AbstractContextManager["_FileLock"]):
    def __init__(self, path: Path, timeout: float) -> None:
        if timeout < 0:
            raise ValueError("lock timeout must be non-negative")
        self.path = path
        self.timeout = timeout
        self._stream: Any = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._acquire_nonblocking()
                return self
            except (BlockingIOError, OSError) as exc:
                if isinstance(exc, OSError) and exc.errno not in {11, 13, 35}:  # EAGAIN/EACCES variants
                    self._stream.close()
                    self._stream = None
                    raise ResourceGuardError(f"cannot lock event log: {exc}") from exc
                if time.monotonic() >= deadline:
                    self._stream.close()
                    self._stream = None
                    raise ResourceGuardError(f"event-log lock timeout after {self.timeout:.3f}s") from None
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))

    def _acquire_nonblocking(self) -> None:
        if os.name == "posix":
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif os.name == "nt":  # pragma: no cover - exercised on Windows CI
            import msvcrt

            self._stream.seek(0)
            if self._stream.read(1) == b"":
                self._stream.write(b"\0")
                self._stream.flush()
            self._stream.seek(0)
            msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - unsupported runtime
            raise ResourceGuardError(f"file locking is unsupported on os.name={os.name!r}")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._stream is None:
            return None
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
            elif os.name == "nt":  # pragma: no cover - exercised on Windows CI
                import msvcrt

                self._stream.seek(0)
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._stream.close()
            self._stream = None
        return None


def new_event_id() -> str:
    return "event_" + uuid.uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_timezone_aware(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _require_string(event: Mapping[str, Any], field: str, pattern: re.Pattern[str] | None = None) -> str:
    value = event[field]
    if not isinstance(value, str) or not value:
        raise EventValidationError(f"{field} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise EventValidationError(f"{field} has invalid format: {value!r}")
    return value


def validate_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a detached JSON-compatible Event Envelope."""

    if not isinstance(event, Mapping):
        raise EventValidationError("event must be a JSON object")
    missing = EVENT_FIELDS - event.keys()
    extra = event.keys() - EVENT_FIELDS
    if missing:
        raise EventValidationError(f"event is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise EventValidationError(f"event has unknown fields: {', '.join(sorted(extra))}")

    event_id = _require_string(event, "event_id", EVENT_ID_RE)
    event_type = _require_string(event, "event_type")
    if event_type not in EVENT_TYPES:
        raise EventValidationError(f"unsupported event_type: {event_type}")
    _require_string(event, "book_id", BOOK_ID_RE)
    _require_string(event, "branch_id", BRANCH_ID_RE)

    parent = event["parent_event_id"]
    if parent is not None and (not isinstance(parent, str) or EVENT_ID_RE.fullmatch(parent) is None):
        raise EventValidationError("parent_event_id must be null or a core.v3 event ID")
    story_seq = event["story_seq"]
    if isinstance(story_seq, bool) or not isinstance(story_seq, int) or story_seq < 0:
        raise EventValidationError("story_seq must be a non-negative integer")
    recorded_at = _require_string(event, "recorded_at")
    if not _is_timezone_aware(recorded_at):
        raise EventValidationError("recorded_at must be timezone-aware ISO 8601")

    actor_type = _require_string(event, "actor_type", ACTOR_RE)
    if actor_type in FORBIDDEN_ACTORS:
        raise EventValidationError(f"actor_type is not authorized to append events: {actor_type}")
    _require_string(event, "actor_id", ACTOR_RE)
    source_run = event["source_run_id"]
    if source_run is not None and (not isinstance(source_run, str) or RUN_ID_RE.fullmatch(source_run) is None):
        raise EventValidationError("source_run_id must be null or a stable run ID")

    payload = event["payload"]
    if not isinstance(payload, dict):
        raise EventValidationError("payload must be a JSON object")
    try:
        expected_payload_hash = sha256_json(payload)
    except (TypeError, ValueError) as exc:
        raise EventValidationError(f"payload is not canonical JSON: {exc}") from exc
    payload_hash = _require_string(event, "payload_hash")
    if payload_hash != expected_payload_hash:
        raise EventValidationError(
            f"payload_hash mismatch for {event_id}: expected {expected_payload_hash}, got {payload_hash}"
        )

    evidence_refs = event["evidence_refs"]
    if not isinstance(evidence_refs, list) or any(not isinstance(ref, str) or not ref for ref in evidence_refs):
        raise EventValidationError("evidence_refs must be a list of non-empty strings")
    supersedes = event["supersedes"]
    if supersedes is not None and (not isinstance(supersedes, str) or EVENT_ID_RE.fullmatch(supersedes) is None):
        raise EventValidationError("supersedes must be null or a core.v3 event ID")

    # A canonical JSON round trip rejects non-JSON values and detaches caller-owned containers.
    try:
        detached = json.loads(canonical_json_bytes(dict(event)).decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise EventValidationError(f"event is not canonical JSON: {exc}") from exc
    return detached


def build_event(
    *,
    event_type: str,
    book_id: str,
    branch_id: str,
    parent_event_id: str | None,
    story_seq: int,
    actor_type: str,
    actor_id: str,
    payload: Mapping[str, Any],
    source_run_id: str | None = None,
    evidence_refs: Sequence[str] = (),
    supersedes: str | None = None,
    event_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    detached_payload = json.loads(canonical_json_bytes(dict(payload)).decode("utf-8"))
    event = {
        "event_id": event_id or new_event_id(),
        "event_type": event_type,
        "book_id": book_id,
        "branch_id": branch_id,
        "parent_event_id": parent_event_id,
        "story_seq": story_seq,
        "recorded_at": recorded_at or utc_now(),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "source_run_id": source_run_id,
        "payload_hash": sha256_json(detached_payload),
        "payload": detached_payload,
        "evidence_refs": list(evidence_refs),
        "supersedes": supersedes,
    }
    return validate_event(event)


class EventLog:
    """One book's authoritative append-only JSONL and derived branch heads."""

    def __init__(self, book_root: Path | str, *, lock_timeout: float = 5.0) -> None:
        self.book_root = Path(book_root)
        self.ledger = self.book_root / "ledger"
        self.log_path = self.ledger / "events.jsonl"
        self.heads_directory = self.ledger / "heads"
        self.lock_path = self.ledger / "events.lock"
        self.lock_timeout = lock_timeout

    def initialize(self) -> None:
        self.ledger.mkdir(parents=True, exist_ok=True)
        self.heads_directory.mkdir(exist_ok=True)
        with self._locked():
            if not self.log_path.exists():
                descriptor = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self._fsync_ledger()
            elif not self.log_path.is_file():
                raise EventLogError(f"event log is not a regular file: {self.log_path}")

    def _fsync_ledger(self) -> None:
        if os.name != "posix":
            return
        descriptor = os.open(self.ledger, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _locked(self) -> _FileLock:
        return _FileLock(self.lock_path, self.lock_timeout)

    def _read_state_unlocked(self) -> LogState:
        if not self.log_path.is_file():
            raise EventIntegrityError(f"event log does not exist: {self.log_path}")
        raw = self.log_path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise EventIntegrityError("event log has a truncated final line (missing newline)")

        events: list[dict[str, Any]] = []
        heads: dict[str, str] = {}
        event_ids: set[str] = set()
        book_id: str | None = None
        for line_number, raw_line in enumerate(raw.splitlines(), start=1):
            try:
                value = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise EventIntegrityError(f"invalid JSON at event log line {line_number}: {exc}") from exc
            try:
                event = validate_event(value)
            except EventValidationError as exc:
                raise EventIntegrityError(f"invalid event at line {line_number}: {exc}") from exc
            event_id = event["event_id"]
            if event_id in event_ids:
                raise EventIntegrityError(f"duplicate event_id at line {line_number}: {event_id}")
            if book_id is None:
                book_id = event["book_id"]
            elif event["book_id"] != book_id:
                raise EventIntegrityError(
                    f"book_id changed at line {line_number}: {book_id} -> {event['book_id']}"
                )
            branch = event["branch_id"]
            parent = event["parent_event_id"]
            current = heads.get(branch)
            if current is not None and parent != current:
                raise EventIntegrityError(
                    f"parent chain mismatch at line {line_number} on {branch}: expected {current}, got {parent}"
                )
            if current is None:
                if events and parent is None:
                    raise EventIntegrityError(
                        f"new branch {branch} must fork from an existing event at line {line_number}"
                    )
                if parent is not None and parent not in event_ids:
                    raise EventIntegrityError(
                        f"first event on branch {branch} references unknown parent at line {line_number}: {parent}"
                    )
            supersedes = event["supersedes"]
            if supersedes is not None and supersedes not in event_ids:
                raise EventIntegrityError(
                    f"supersedes references a non-prior event at line {line_number}: {supersedes}"
                )
            event_ids.add(event_id)
            heads[branch] = event_id
            events.append(event)
        return LogState(tuple(events), heads, frozenset(event_ids), book_id)

    def read_events(self) -> tuple[dict[str, Any], ...]:
        with self._locked():
            return self._read_state_unlocked().events

    def read_lineage(self, branch_id: str = "main") -> tuple[dict[str, Any], ...]:
        """Return root-to-head ancestry for one branch, including inherited ancestors."""

        if BRANCH_ID_RE.fullmatch(branch_id) is None:
            raise EventValidationError(f"invalid branch_id: {branch_id!r}")
        with self._locked():
            state = self._read_state_unlocked()
            head = state.heads.get(branch_id)
            if head is None:
                if not state.events:
                    return ()
                raise EventLogError(f"branch does not exist: {branch_id}")
            by_id = {event["event_id"]: event for event in state.events}
            reverse_lineage: list[dict[str, Any]] = []
            seen: set[str] = set()
            current: str | None = head
            while current is not None:
                if current in seen:
                    raise EventIntegrityError(f"cycle detected in event ancestry at {current}")
                seen.add(current)
                event = by_id.get(current)
                if event is None:
                    raise EventIntegrityError(f"event ancestry references missing event: {current}")
                reverse_lineage.append(event)
                current = event["parent_event_id"]
            reverse_lineage.reverse()
            return tuple(reverse_lineage)

    def _head_path(self, branch_id: str) -> Path:
        if BRANCH_ID_RE.fullmatch(branch_id) is None:
            raise EventValidationError(f"invalid branch_id: {branch_id!r}")
        return self.heads_directory / f"{branch_id}.json"

    def _head_value(self, branch: str, event_id: str, event_count: int, book_id: str) -> dict[str, Any]:
        return {
            "schema_version": "core.v3.branch-head.v1",
            "book_id": book_id,
            "branch_id": branch,
            "event_id": event_id,
            "event_count": event_count,
        }

    def _verify_heads_unlocked(self, state: LogState) -> None:
        expected_files = {f"{branch}.json" for branch in state.heads}
        actual_files = {path.name for path in self.heads_directory.glob("*.json")}
        if actual_files != expected_files:
            raise HeadMismatchError(
                f"branch-head file set mismatch: expected {sorted(expected_files)}, got {sorted(actual_files)}"
            )
        branch_counts: dict[str, int] = {}
        for event in state.events:
            branch_counts[event["branch_id"]] = branch_counts.get(event["branch_id"], 0) + 1
        for branch, event_id in state.heads.items():
            path = self._head_path(branch)
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise HeadMismatchError(f"cannot read branch head {path}: {exc}") from exc
            expected = self._head_value(branch, event_id, branch_counts[branch], state.book_id or "")
            if value != expected:
                raise HeadMismatchError(f"branch head does not match authoritative log: {path}")

    def verify(self, *, verify_heads: bool = True) -> VerificationReport:
        with self._locked():
            state = self._read_state_unlocked()
            if verify_heads:
                self._verify_heads_unlocked(state)
            return VerificationReport(
                ok=True,
                event_count=len(state.events),
                branch_count=len(state.heads),
                heads=dict(state.heads),
                book_id=state.book_id,
                log_size=self.log_path.stat().st_size,
            )

    def append(self, candidate: Mapping[str, Any]) -> AppendResult:
        return self.append_many((candidate,))[0]

    def rebuild_heads(self) -> dict[str, str]:
        """Rebuild derived head files from authoritative JSONL after an interrupted update."""

        self.initialize()
        with self._locked():
            state = self._read_state_unlocked()
            branch_counts: dict[str, int] = {}
            for event in state.events:
                branch_counts[event["branch_id"]] = branch_counts.get(event["branch_id"], 0) + 1
            expected = {f"{branch}.json" for branch in state.heads}
            for stale in self.heads_directory.glob("*.json"):
                if stale.name not in expected:
                    stale.unlink()
            for branch, event_id in state.heads.items():
                atomic_write_json(
                    self._head_path(branch),
                    self._head_value(branch, event_id, branch_counts[branch], state.book_id or ""),
                )
            return dict(state.heads)

    def append_many(self, candidates: Iterable[Mapping[str, Any]]) -> tuple[AppendResult, ...]:
        """Validate and append a sequential batch under one process lock and one fsync.

        The entire batch is validated against an in-memory successor state before any bytes are
        written. JSONL remains authoritative; if a later derived-head update fails, callers must
        run ``rebuild_heads`` before another append.
        """

        events = tuple(validate_event(candidate) for candidate in candidates)
        if not events:
            return ()
        self.initialize()
        with self._locked():
            state = self._read_state_unlocked()
            self._verify_heads_unlocked(state)
            known_ids = set(state.event_ids)
            heads = dict(state.heads)
            branch_counts: dict[str, int] = {}
            for existing in state.events:
                branch = existing["branch_id"]
                branch_counts[branch] = branch_counts.get(branch, 0) + 1
            book_id = state.book_id
            prepared: list[tuple[dict[str, Any], bytes, int, int]] = []
            next_offset = self.log_path.stat().st_size
            next_line = len(state.events) + 1

            for event in events:
                if book_id is None:
                    book_id = event["book_id"]
                elif event["book_id"] != book_id:
                    raise EventValidationError(
                        f"event book_id {event['book_id']} does not match log book_id {book_id}"
                    )
                event_id = event["event_id"]
                if event_id in known_ids:
                    raise DuplicateEventError(f"event_id already exists: {event_id}")
                branch = event["branch_id"]
                current = heads.get(branch)
                parent = event["parent_event_id"]
                if current is not None and parent != current:
                    raise ParentConflictError(
                        f"parent conflict on {branch}: current head is {current}, candidate parent is {parent}"
                    )
                if current is None:
                    if known_ids and parent is None:
                        raise ParentConflictError(f"new branch {branch} must fork from an existing event")
                    if parent is not None and parent not in known_ids:
                        raise ParentConflictError(
                            f"new branch {branch} references unknown parent event: {parent}"
                        )
                supersedes = event["supersedes"]
                if supersedes is not None and supersedes not in known_ids:
                    raise EventValidationError(
                        f"supersedes references an unknown or non-prior event: {supersedes}"
                    )
                line = canonical_json_bytes(event) + b"\n"
                prepared.append((event, line, next_line, next_offset))
                next_line += 1
                next_offset += len(line)
                known_ids.add(event_id)
                heads[branch] = event_id
                branch_counts[branch] = branch_counts.get(branch, 0) + 1

            payload = b"".join(line for _, line, _, _ in prepared)
            descriptor = os.open(self.log_path, os.O_WRONLY | os.O_APPEND)
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise EventLogError("event batch append made no progress")
                    view = view[written:]
                os.fsync(descriptor)
            except OSError as exc:
                raise EventLogError(f"cannot append event batch: {exc}") from exc
            finally:
                os.close(descriptor)

            try:
                touched_branches = {event["branch_id"] for event in events}
                for branch in sorted(touched_branches):
                    atomic_write_json(
                        self._head_path(branch),
                        self._head_value(branch, heads[branch], branch_counts[branch], book_id or ""),
                    )
            except Exception as exc:
                raise HeadUpdateError(
                    "event batch was appended but a branch head update failed; rebuild heads before continuing: "
                    f"{exc}"
                ) from exc

            return tuple(
                AppendResult(
                    event_id=event["event_id"],
                    branch_id=event["branch_id"],
                    parent_event_id=event["parent_event_id"],
                    line_number=line_number,
                    byte_offset=byte_offset,
                    bytes_appended=len(line),
                    payload_hash=event["payload_hash"],
                )
                for event, line, line_number, byte_offset in prepared
            )
