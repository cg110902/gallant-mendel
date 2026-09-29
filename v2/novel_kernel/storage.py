"""Durable, standard-library-only file storage primitives.

M1.1 deliberately contains no event, projection, or story-domain behavior.  It provides
byte hashing, canonical JSON hashing, atomic replacement, and forensic quarantine.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HASH_PREFIX = "sha256:"
_COPY_CHUNK_SIZE = 1024 * 1024


class StorageError(Exception):
    """Base class for deterministic storage failures."""


class ConcurrentWriteError(StorageError):
    """The destination changed while an atomic replacement was prepared."""


class HashMismatchError(StorageError):
    """Stored bytes do not match the required SHA-256 digest."""


@dataclass(frozen=True)
class AtomicWriteResult:
    path: str
    previous_hash: str | None
    content_hash: str
    bytes_written: int
    directory_synced: bool


@dataclass(frozen=True)
class QuarantineRecord:
    source_path: str
    quarantined_path: str
    metadata_path: str
    reason: str
    content_hash: str
    quarantined_at: str


def sha256_bytes(data: bytes) -> str:
    """Return a protocol-form SHA-256 digest for raw bytes."""

    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    """Hash a file without loading the entire file into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(_COPY_CHUNK_SIZE):
            digest.update(chunk)
    return HASH_PREFIX + digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON exactly as required by the core.v3 hash policy."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def is_sha256(value: str) -> bool:
    if not value.startswith(HASH_PREFIX) or len(value) != len(HASH_PREFIX) + 64:
        return False
    return all(character in "0123456789abcdef" for character in value[len(HASH_PREFIX) :])


def verify_file_hash(path: Path | str, expected_hash: str) -> bool:
    if not is_sha256(expected_hash):
        raise ValueError("expected_hash must use sha256:<64 lowercase hex> format")
    return sha256_file(path) == expected_hash


def _fsync_directory(directory: Path) -> bool:
    """Persist a directory entry on platforms that expose directory fsync."""

    if os.name != "posix":
        return False
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def atomic_write_bytes(
    path: Path | str,
    data: bytes,
    *,
    mode: int | None = None,
    _before_replace: Callable[[], None] | None = None,
) -> AtomicWriteResult:
    """Durably replace *path* with *data* without exposing a partial destination.

    The temporary file is created in the destination directory, flushed and fsynced,
    then installed with ``os.replace``. Existing mode bits are preserved unless ``mode``
    is supplied. A private pre-replace callback exists solely for crash/fault injection;
    application code must not use it as a commit hook.
    """

    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    destination = Path(path)
    parent = destination.parent
    if not parent.is_dir():
        raise StorageError(f"destination directory does not exist: {parent}")
    if destination.exists() and not destination.is_file():
        raise StorageError(f"destination exists and is not a regular file: {destination}")

    existed = destination.exists()
    previous_hash = sha256_file(destination) if existed else None
    if mode is None:
        file_mode = stat.S_IMODE(destination.stat().st_mode) if existed else 0o600
    else:
        if mode < 0 or mode > 0o777:
            raise ValueError("mode must be between 0 and 0o777")
        file_mode = mode

    content_hash = sha256_bytes(data)
    temporary = parent / f".{destination.name}.atomic-{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, file_mode)  # type: ignore[attr-defined]
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

        # Detect a competing writer before replacement. M1.2 adds the stronger event-log lock.
        if existed:
            if not destination.is_file() or sha256_file(destination) != previous_hash:
                raise ConcurrentWriteError(f"destination changed during write: {destination}")
        elif destination.exists():
            raise ConcurrentWriteError(f"destination appeared during write: {destination}")

        if _before_replace is not None:
            _before_replace()
        os.replace(temporary, destination)
        directory_synced = _fsync_directory(parent)
        stored_hash = sha256_file(destination)
        if stored_hash != content_hash:
            raise HashMismatchError(
                f"post-write hash mismatch for {destination}: expected {content_hash}, got {stored_hash}"
            )
        return AtomicWriteResult(
            path=str(destination),
            previous_hash=previous_hash,
            content_hash=content_hash,
            bytes_written=len(data),
            directory_synced=directory_synced,
        )
    except OSError as exc:
        raise StorageError(f"atomic write failed for {destination}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # The original exception is more actionable. A hard crash may also leave this
            # recognizable temp file; verification records and removes such files explicitly.
            pass


def atomic_write_json(
    path: Path | str,
    value: Any,
    *,
    mode: int | None = None,
    _before_replace: Callable[[], None] | None = None,
) -> AtomicWriteResult:
    """Atomically write canonical JSON bytes (without a trailing newline)."""

    return atomic_write_bytes(
        path,
        canonical_json_bytes(value),
        mode=mode,
        _before_replace=_before_replace,
    )


def quarantine_file(
    source: Path | str,
    quarantine_directory: Path | str,
    *,
    reason: str,
    expected_hash: str | None = None,
) -> QuarantineRecord:
    """Move a suspect file out of service and write a forensic metadata sidecar.

    Quarantine never deletes the suspect bytes. The source and quarantine directory must
    share a filesystem so ``os.replace`` remains atomic.
    """

    source_path = Path(source)
    quarantine_path = Path(quarantine_directory)
    if not reason.strip():
        raise ValueError("reason must not be empty")
    if not source_path.is_file():
        raise StorageError(f"quarantine source is not a regular file: {source_path}")
    if expected_hash is not None and not is_sha256(expected_hash):
        raise ValueError("expected_hash must use sha256:<64 lowercase hex> format")

    quarantine_path.mkdir(parents=True, exist_ok=True)
    observed_hash = sha256_file(source_path)
    quarantine_id = uuid.uuid4().hex
    isolated = quarantine_path / f"quarantine_{quarantine_id}.bin"
    metadata = quarantine_path / f"quarantine_{quarantine_id}.json"
    quarantined_at = datetime.now(timezone.utc).isoformat()

    try:
        os.replace(source_path, isolated)
        _fsync_directory(source_path.parent)
        if source_path.parent.resolve() != quarantine_path.resolve():
            _fsync_directory(quarantine_path)
    except OSError as exc:
        raise StorageError(f"cannot quarantine {source_path}: {exc}") from exc

    metadata_value = {
        "schema_version": "storage.quarantine.v1",
        "source_path": str(source_path),
        "quarantined_path": str(isolated),
        "reason": reason,
        "expected_hash": expected_hash,
        "observed_hash": observed_hash,
        "hash_mismatch": expected_hash is not None and expected_hash != observed_hash,
        "quarantined_at": quarantined_at,
    }
    atomic_write_json(metadata, metadata_value)
    return QuarantineRecord(
        source_path=str(source_path),
        quarantined_path=str(isolated),
        metadata_path=str(metadata),
        reason=reason,
        content_hash=observed_hash,
        quarantined_at=quarantined_at,
    )


def quarantine_record_dict(record: QuarantineRecord) -> dict[str, Any]:
    """Return a JSON-compatible record without relying on Python repr."""

    return asdict(record)
