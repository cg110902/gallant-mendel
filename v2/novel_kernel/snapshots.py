"""Verified, atomically published snapshots and non-destructive restore (M1.5)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .events import EventLog, validate_event
from .projection import PROJECTION_SCHEMA_VERSION, ProjectionStore
from .storage import atomic_write_bytes, atomic_write_json, is_sha256, sha256_file, sha256_json

SNAPSHOT_ID_RE = re.compile(r"^snapshot_[0-9a-f]{32}$")
BRANCH_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
MANIFEST_FIELDS = frozenset(
    {
        "schema_version", "snapshot_id", "book_id", "branch_id", "label", "created_at",
        "head_event_id", "lineage_event_count", "projection_state_hash", "files",
    }
)
FILE_FIELDS = frozenset({"path", "role", "bytes", "sha256"})
ARTIFACT_MANIFEST_FIELDS = frozenset({"schema_version", "artifacts"})
ARTIFACT_FIELDS = frozenset({"source_path", "snapshot_path", "bytes", "sha256"})
CORE_ARTIFACT_ROOTS = frozenset({"ledger", "state", "snapshots"})


class SnapshotError(Exception):
    """Snapshot creation, verification, or restore failed safely."""


class SnapshotValidationError(SnapshotError):
    """Snapshot bytes do not satisfy the v1 manifest."""


@dataclass(frozen=True)
class SnapshotReport:
    snapshot_id: str
    path: str
    book_id: str
    branch_id: str
    head_event_id: str
    lineage_event_count: int
    projection_state_hash: str
    artifact_count: int


@dataclass(frozen=True)
class RestoreReport:
    snapshot_id: str
    target_path: str
    branch_id: str
    head_event_id: str
    lineage_event_count: int
    projection_state_hash: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _aware_datetime(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise SnapshotValidationError(f"{label} must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotValidationError(f"{label} must be ISO 8601: {exc}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotValidationError(f"{label} must include a timezone")
    return value


def _strict(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SnapshotValidationError(f"{label} must be a JSON object")
    keys = set(value)
    missing = fields - keys
    extra = keys - fields
    if missing:
        raise SnapshotValidationError(f"{label} is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise SnapshotValidationError(f"{label} has unknown fields: {', '.join(sorted(extra))}")
    return value


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise SnapshotValidationError(f"{label} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise SnapshotValidationError(f"{label} must not be absolute or traverse parents: {value}")
    return path


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SnapshotError(f"snapshot tree contains a symbolic link: {path}")
        if path.is_file():
            _fsync_file(path)
    if os.name == "posix":
        directories = [path for path in root.rglob("*") if path.is_dir()]
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True) + [root]:
            descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _copy_and_fsync(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination, follow_symlinks=False)
    os.chmod(destination, 0o600)
    _fsync_file(destination)


def _database_state_hash(database: Path, branch_id: str) -> tuple[str, int, str | None]:
    uri = f"file:{database.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SnapshotValidationError(f"snapshot SQLite integrity_check failed: {integrity}")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise SnapshotValidationError("snapshot SQLite foreign_key_check failed")
        row = connection.execute(
            "SELECT schema_version,branch_id,authority,last_applied_event_id,applied_event_count "
            "FROM projection_meta WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise SnapshotValidationError("snapshot SQLite projection metadata is missing")
        if row[0] != PROJECTION_SCHEMA_VERSION or row[1] != branch_id or row[2] != "derived":
            raise SnapshotValidationError("snapshot SQLite projection metadata does not match manifest")
        count, head = row[4], row[3]
        state: dict[str, Any] = {}
        for table, order_by in (
            ("objects", "object_id"), ("facets", "object_id, facet_type"),
            ("relations", "relation_id"), ("facts", "fact_id"), ("evidence", "evidence_id"),
        ):
            rows = []
            for item in connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}"):
                value = dict(item)
                for field in list(value):
                    if field.endswith("_json"):
                        value[field[:-5]] = json.loads(value.pop(field))
                rows.append(value)
            state[table] = rows
        state_hash = sha256_json(state)
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        raise SnapshotValidationError(f"cannot inspect snapshot SQLite: {exc}") from exc
    finally:
        connection.close()
    return state_hash, count, head


def _read_snapshot_lineage(path: Path) -> tuple[dict[str, Any], ...]:
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise SnapshotValidationError("snapshot event log has a truncated final line")
    events: list[dict[str, Any]] = []
    previous: str | None = None
    book_id: str | None = None
    for line_number, line in enumerate(raw.splitlines(), start=1):
        try:
            event = validate_event(json.loads(line))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise SnapshotValidationError(f"invalid snapshot event at line {line_number}: {exc}") from exc
        if events and event["parent_event_id"] != previous:
            raise SnapshotValidationError(
                f"snapshot lineage parent mismatch at line {line_number}: expected {previous}"
            )
        if not events and event["parent_event_id"] is not None:
            raise SnapshotValidationError("snapshot lineage does not begin at a root event")
        if book_id is None:
            book_id = event["book_id"]
        elif event["book_id"] != book_id:
            raise SnapshotValidationError("snapshot lineage mixes book IDs")
        previous = event["event_id"]
        events.append(event)
    return tuple(events)


class SnapshotManager:
    def __init__(self, book_root: Path | str) -> None:
        self.book_root = Path(book_root)
        self.snapshots_directory = self.book_root / "snapshots"

    def _artifact_sources(self, artifact_paths: Iterable[Path | str]) -> tuple[tuple[Path, PurePosixPath], ...]:
        root = self.book_root.resolve()
        seen: set[str] = set()
        result: list[tuple[Path, PurePosixPath]] = []
        for candidate in artifact_paths:
            raw = Path(candidate)
            source = raw if raw.is_absolute() else self.book_root / raw
            if source.is_symlink() or not source.is_file():
                raise SnapshotError(f"artifact must be a regular non-symlink file: {candidate}")
            resolved = source.resolve()
            try:
                relative = resolved.relative_to(root)
            except ValueError as exc:
                raise SnapshotError(f"artifact is outside the book root: {candidate}") from exc
            posix = PurePosixPath(relative.as_posix())
            if not posix.parts or posix.parts[0] in CORE_ARTIFACT_ROOTS:
                raise SnapshotError(f"artifact path is reserved for core state: {posix}")
            key = posix.as_posix()
            if key in seen:
                raise SnapshotError(f"duplicate artifact path: {key}")
            seen.add(key)
            result.append((resolved, posix))
        return tuple(sorted(result, key=lambda item: item[1].as_posix()))

    def create(
        self,
        *,
        label: str,
        branch_id: str = "main",
        artifact_paths: Iterable[Path | str] = (),
    ) -> SnapshotReport:
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise SnapshotError("label must be 1-200 non-whitespace characters")
        if BRANCH_ID_RE.fullmatch(branch_id) is None:
            raise SnapshotError(f"invalid branch_id: {branch_id}")
        event_log = EventLog(self.book_root)
        event_log.verify()
        lineage = event_log.read_lineage(branch_id)
        if not lineage:
            raise SnapshotError("cannot snapshot an empty event lineage")
        projection = ProjectionStore(self.book_root, branch_id=branch_id)
        projection_report = projection.verify(event_log)
        if projection_report.last_applied_event_id != lineage[-1]["event_id"]:
            raise SnapshotError("projection head does not match event lineage")
        artifacts = self._artifact_sources(artifact_paths)

        snapshot_id = "snapshot_" + uuid.uuid4().hex
        self.snapshots_directory.mkdir(parents=True, exist_ok=True)
        final = self.snapshots_directory / snapshot_id
        temporary = self.snapshots_directory / f".{snapshot_id}.tmp"
        if final.exists() or temporary.exists():
            raise SnapshotError(f"snapshot path collision: {snapshot_id}")
        try:
            (temporary / "ledger").mkdir(parents=True)
            (temporary / "state").mkdir()
            (temporary / "artifacts" / "files").mkdir(parents=True)
            event_bytes = b"".join(
                canonical_line(event) for event in lineage
            )
            atomic_write_bytes(temporary / "ledger" / "events.jsonl", event_bytes)

            source = sqlite3.connect(projection.database_path)
            destination = sqlite3.connect(temporary / "state" / "state.db")
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
                source.close()
            os.chmod(temporary / "state" / "state.db", 0o600)
            _fsync_file(temporary / "state" / "state.db")

            artifact_entries: list[dict[str, Any]] = []
            for source_path, relative in artifacts:
                snapshot_relative = PurePosixPath("artifacts") / "files" / relative
                destination_path = temporary.joinpath(*snapshot_relative.parts)
                _copy_and_fsync(source_path, destination_path)
                artifact_entries.append(
                    {
                        "source_path": relative.as_posix(),
                        "snapshot_path": snapshot_relative.as_posix(),
                        "bytes": destination_path.stat().st_size,
                        "sha256": sha256_file(destination_path),
                    }
                )
            artifacts_value = {
                "schema_version": "snapshot-artifacts.v1",
                "artifacts": artifact_entries,
            }
            atomic_write_json(temporary / "artifacts.json", artifacts_value)

            files = []
            for relative, role in (
                ("ledger/events.jsonl", "event-lineage"),
                ("state/state.db", "sqlite-projection"),
                ("artifacts.json", "artifact-manifest"),
            ):
                path = temporary.joinpath(*PurePosixPath(relative).parts)
                files.append(
                    {"path": relative, "role": role, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
                )
            manifest = {
                "schema_version": "snapshot.v1",
                "snapshot_id": snapshot_id,
                "book_id": lineage[0]["book_id"],
                "branch_id": branch_id,
                "label": label,
                "created_at": _utc_now(),
                "head_event_id": lineage[-1]["event_id"],
                "lineage_event_count": len(lineage),
                "projection_state_hash": projection_report.state_hash,
                "files": files,
            }
            atomic_write_json(temporary / "manifest.json", manifest)
            report = self.validate(temporary)
            _fsync_tree(temporary)
            os.replace(temporary, final)
            self._fsync_snapshots_directory()
            return SnapshotReport(
                snapshot_id=report.snapshot_id,
                path=str(final),
                book_id=report.book_id,
                branch_id=report.branch_id,
                head_event_id=report.head_event_id,
                lineage_event_count=report.lineage_event_count,
                projection_state_hash=report.projection_state_hash,
                artifact_count=report.artifact_count,
            )
        except SnapshotError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise SnapshotError(f"snapshot creation failed: {exc}") from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def _fsync_snapshots_directory(self) -> None:
        if os.name != "posix":
            return
        descriptor = os.open(self.snapshots_directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def validate(snapshot_path: Path | str) -> SnapshotReport:
        root = Path(snapshot_path)
        if root.is_symlink() or not root.is_dir():
            raise SnapshotValidationError(f"snapshot path is not a regular directory: {root}")
        manifest_path = root / "manifest.json"
        try:
            manifest = _strict(json.loads(manifest_path.read_text(encoding="utf-8")), MANIFEST_FIELDS, "manifest")
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SnapshotValidationError(f"cannot read snapshot manifest: {exc}") from exc
        if manifest["schema_version"] != "snapshot.v1":
            raise SnapshotValidationError("unsupported snapshot schema_version")
        snapshot_id = manifest["snapshot_id"]
        if not isinstance(snapshot_id, str) or SNAPSHOT_ID_RE.fullmatch(snapshot_id) is None:
            raise SnapshotValidationError("invalid snapshot_id")
        if not isinstance(manifest["book_id"], str) or not manifest["book_id"].startswith("book_"):
            raise SnapshotValidationError("invalid book_id")
        branch_id = manifest["branch_id"]
        if not isinstance(branch_id, str) or BRANCH_ID_RE.fullmatch(branch_id) is None:
            raise SnapshotValidationError("invalid branch_id")
        if not isinstance(manifest["label"], str) or not manifest["label"].strip():
            raise SnapshotValidationError("invalid snapshot label")
        _aware_datetime(manifest["created_at"], "created_at")
        if not isinstance(manifest["lineage_event_count"], int) or isinstance(manifest["lineage_event_count"], bool) or manifest["lineage_event_count"] <= 0:
            raise SnapshotValidationError("lineage_event_count must be a positive integer")
        if not is_sha256(manifest["projection_state_hash"]):
            raise SnapshotValidationError("invalid projection_state_hash")

        files = manifest["files"]
        if not isinstance(files, list) or len(files) != 3:
            raise SnapshotValidationError("manifest files must contain exactly three core files")
        core_paths: set[str] = set()
        expected_roles = {
            "ledger/events.jsonl": "event-lineage",
            "state/state.db": "sqlite-projection",
            "artifacts.json": "artifact-manifest",
        }
        for raw in files:
            entry = _strict(raw, FILE_FIELDS, "manifest file entry")
            relative = _safe_relative(entry["path"], "manifest file path").as_posix()
            if relative in core_paths or expected_roles.get(relative) != entry["role"]:
                raise SnapshotValidationError(f"unexpected or duplicate core file entry: {relative}")
            path = root.joinpath(*PurePosixPath(relative).parts)
            if path.is_symlink() or not path.is_file():
                raise SnapshotValidationError(f"snapshot core file is missing: {relative}")
            if not isinstance(entry["bytes"], int) or entry["bytes"] != path.stat().st_size:
                raise SnapshotValidationError(f"snapshot byte size mismatch: {relative}")
            if not is_sha256(entry["sha256"]) or sha256_file(path) != entry["sha256"]:
                raise SnapshotValidationError(f"snapshot hash mismatch: {relative}")
            core_paths.add(relative)
        if core_paths != set(expected_roles):
            raise SnapshotValidationError("snapshot core file set is incomplete")

        try:
            artifact_manifest = _strict(
                json.loads((root / "artifacts.json").read_text(encoding="utf-8")),
                ARTIFACT_MANIFEST_FIELDS,
                "artifact manifest",
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SnapshotValidationError(f"cannot read artifact manifest: {exc}") from exc
        if artifact_manifest["schema_version"] != "snapshot-artifacts.v1":
            raise SnapshotValidationError("unsupported artifact manifest schema_version")
        if not isinstance(artifact_manifest["artifacts"], list):
            raise SnapshotValidationError("artifact manifest artifacts must be a list")
        artifact_files: set[str] = set()
        source_files: set[str] = set()
        for raw in artifact_manifest["artifacts"]:
            entry = _strict(raw, ARTIFACT_FIELDS, "artifact entry")
            source_relative = _safe_relative(entry["source_path"], "artifact source_path").as_posix()
            snapshot_relative = _safe_relative(entry["snapshot_path"], "artifact snapshot_path").as_posix()
            expected = (PurePosixPath("artifacts") / "files" / PurePosixPath(source_relative)).as_posix()
            if snapshot_relative != expected:
                raise SnapshotValidationError("artifact snapshot_path does not match source_path")
            if source_relative in source_files or snapshot_relative in artifact_files:
                raise SnapshotValidationError("duplicate artifact path")
            path = root.joinpath(*PurePosixPath(snapshot_relative).parts)
            if path.is_symlink() or not path.is_file():
                raise SnapshotValidationError(f"snapshot artifact is missing: {snapshot_relative}")
            if not isinstance(entry["bytes"], int) or entry["bytes"] != path.stat().st_size:
                raise SnapshotValidationError(f"artifact byte size mismatch: {snapshot_relative}")
            if not is_sha256(entry["sha256"]) or sha256_file(path) != entry["sha256"]:
                raise SnapshotValidationError(f"artifact hash mismatch: {snapshot_relative}")
            source_files.add(source_relative)
            artifact_files.add(snapshot_relative)

        actual_files: set[str] = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise SnapshotValidationError(f"snapshot contains symbolic link: {path}")
            if path.is_file():
                actual_files.add(path.relative_to(root).as_posix())
        expected_files = {"manifest.json", *core_paths, *artifact_files}
        if actual_files != expected_files:
            raise SnapshotValidationError(
                f"snapshot contains undeclared files: {sorted(actual_files - expected_files)}"
            )

        lineage = _read_snapshot_lineage(root / "ledger" / "events.jsonl")
        if len(lineage) != manifest["lineage_event_count"]:
            raise SnapshotValidationError("snapshot lineage event count mismatch")
        if not lineage or lineage[-1]["event_id"] != manifest["head_event_id"]:
            raise SnapshotValidationError("snapshot lineage head mismatch")
        if lineage[-1]["branch_id"] != branch_id or lineage[0]["book_id"] != manifest["book_id"]:
            raise SnapshotValidationError("snapshot lineage identity does not match manifest")

        state_hash, state_count, state_head = _database_state_hash(root / "state" / "state.db", branch_id)
        if state_count != len(lineage) or state_head != manifest["head_event_id"]:
            raise SnapshotValidationError("snapshot SQLite head/count does not match lineage")
        if state_hash != manifest["projection_state_hash"]:
            raise SnapshotValidationError("snapshot SQLite logical state hash mismatch")
        return SnapshotReport(
            snapshot_id=snapshot_id,
            path=str(root),
            book_id=manifest["book_id"],
            branch_id=branch_id,
            head_event_id=manifest["head_event_id"],
            lineage_event_count=len(lineage),
            projection_state_hash=state_hash,
            artifact_count=len(artifact_files),
        )

    @staticmethod
    def restore(snapshot_path: Path | str, target_book_root: Path | str) -> RestoreReport:
        snapshot = Path(snapshot_path)
        report = SnapshotManager.validate(snapshot)
        target = Path(target_book_root)
        if target.exists():
            raise SnapshotError(f"restore target already exists; refusing destructive overwrite: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.restore-{uuid.uuid4().hex}.tmp"
        try:
            (temporary / "ledger").mkdir(parents=True)
            (temporary / "state").mkdir()
            _copy_and_fsync(snapshot / "ledger" / "events.jsonl", temporary / "ledger" / "events.jsonl")
            _copy_and_fsync(snapshot / "state" / "state.db", temporary / "state" / "state.db")
            artifact_manifest = json.loads((snapshot / "artifacts.json").read_text(encoding="utf-8"))
            for entry in artifact_manifest["artifacts"]:
                source = snapshot.joinpath(*PurePosixPath(entry["snapshot_path"]).parts)
                destination = temporary.joinpath(*PurePosixPath(entry["source_path"]).parts)
                _copy_and_fsync(source, destination)
            archive = temporary / "snapshots" / report.snapshot_id
            shutil.copytree(snapshot, archive)

            log = EventLog(temporary)
            heads = log.rebuild_heads()
            if heads.get(report.branch_id) != report.head_event_id:
                raise SnapshotError("restored branch head does not match snapshot")
            restored_projection = ProjectionStore(temporary, branch_id=report.branch_id).verify(log)
            if (
                restored_projection.applied_event_count != report.lineage_event_count
                or restored_projection.last_applied_event_id != report.head_event_id
                or restored_projection.state_hash != report.projection_state_hash
            ):
                raise SnapshotError("restored projection does not match snapshot manifest")
            _fsync_tree(temporary)
            os.replace(temporary, target)
            if os.name == "posix":
                descriptor = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return RestoreReport(
                snapshot_id=report.snapshot_id,
                target_path=str(target),
                branch_id=report.branch_id,
                head_event_id=report.head_event_id,
                lineage_event_count=report.lineage_event_count,
                projection_state_hash=report.projection_state_hash,
            )
        except SnapshotError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise SnapshotError(f"snapshot restore failed: {exc}") from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)


def canonical_line(event: dict[str, Any]) -> bytes:
    """Return one canonical JSONL event line without importing EventLog internals."""

    from .storage import canonical_json_bytes

    return canonical_json_bytes(event) + b"\n"
