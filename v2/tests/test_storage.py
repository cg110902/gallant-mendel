from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from novel_kernel.storage import (
    HASH_PREFIX,
    StorageError,
    atomic_write_bytes,
    atomic_write_json,
    canonical_json_bytes,
    is_sha256,
    quarantine_file,
    sha256_bytes,
    sha256_file,
    sha256_json,
    verify_file_hash,
)


class StorageHashTests(unittest.TestCase):
    def test_raw_byte_hash_uses_protocol_format(self) -> None:
        digest = sha256_bytes(b"abc")
        self.assertEqual(
            digest,
            "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertTrue(is_sha256(digest))
        self.assertFalse(is_sha256(digest.upper()))

    def test_canonical_json_is_stable_utf8_without_newline(self) -> None:
        left = {"中文": "值", "a": [2, 1]}
        right = {"a": [2, 1], "中文": "值"}
        expected = '{"a":[2,1],"中文":"值"}'.encode("utf-8")
        self.assertEqual(canonical_json_bytes(left), expected)
        self.assertEqual(canonical_json_bytes(right), expected)
        self.assertEqual(sha256_json(left), sha256_json(right))
        self.assertFalse(expected.endswith(b"\n"))

    def test_canonical_json_rejects_nonstandard_nan(self) -> None:
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("nan")})

    def test_file_hash_streams_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "large.bin"
            content = b"0123456789" * 200_000
            path.write_bytes(content)
            expected = sha256_bytes(content)
            self.assertEqual(sha256_file(path), expected)
            self.assertTrue(verify_file_hash(path, expected))
            self.assertFalse(verify_file_hash(path, HASH_PREFIX + "0" * 64))

    def test_verify_rejects_malformed_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "value"
            path.write_bytes(b"value")
            with self.assertRaises(ValueError):
                verify_file_hash(path, "abc")


class AtomicWriteTests(unittest.TestCase):
    def test_new_file_is_atomically_written_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "state.json"
            result = atomic_write_bytes(destination, b"complete")
            self.assertEqual(destination.read_bytes(), b"complete")
            self.assertIsNone(result.previous_hash)
            self.assertEqual(result.content_hash, sha256_bytes(b"complete"))
            self.assertEqual(result.bytes_written, 8)
            self.assertEqual(list(destination.parent.glob(".*.atomic-*.tmp")), [])
            if os.name == "posix":
                self.assertTrue(result.directory_synced)

    def test_replacement_reports_previous_hash_and_preserves_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "state.json"
            destination.write_bytes(b"old")
            destination.chmod(0o640)
            result = atomic_write_bytes(destination, b"new")
            self.assertEqual(result.previous_hash, sha256_bytes(b"old"))
            self.assertEqual(destination.read_bytes(), b"new")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)

    def test_explicit_mode_is_applied(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX mode assertion")
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "private"
            atomic_write_bytes(destination, b"secret", mode=0o600)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_fault_before_replace_preserves_old_file_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "state.json"
            destination.write_bytes(b"old-complete-state")

            def fail() -> None:
                raise RuntimeError("injected interruption")

            with self.assertRaisesRegex(RuntimeError, "injected interruption"):
                atomic_write_bytes(destination, b"partial-new-state", _before_replace=fail)
            self.assertEqual(destination.read_bytes(), b"old-complete-state")
            self.assertEqual(list(destination.parent.glob(".*.atomic-*.tmp")), [])

    def test_replace_failure_preserves_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "state.json"
            destination.write_bytes(b"old")
            with mock.patch("novel_kernel.storage.os.replace", side_effect=OSError("denied")):
                with self.assertRaisesRegex(StorageError, "atomic write failed"):
                    atomic_write_bytes(destination, b"new")
            self.assertEqual(destination.read_bytes(), b"old")
            self.assertEqual(list(destination.parent.glob(".*.atomic-*.tmp")), [])

    def test_missing_parent_is_rejected_without_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "missing" / "value"
            with self.assertRaisesRegex(StorageError, "directory does not exist"):
                atomic_write_bytes(destination, b"value")
            self.assertFalse(destination.exists())

    def test_non_file_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "directory"
            destination.mkdir()
            with self.assertRaisesRegex(StorageError, "not a regular file"):
                atomic_write_bytes(destination, b"value")

    def test_atomic_json_uses_canonical_protocol_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "value.json"
            value = {"z": 1, "a": "中文"}
            result = atomic_write_json(destination, value)
            self.assertEqual(destination.read_bytes(), canonical_json_bytes(value))
            self.assertEqual(result.content_hash, sha256_json(value))
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), value)


class QuarantineTests(unittest.TestCase):
    def test_quarantine_preserves_bytes_and_writes_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "suspect.json"
            content = b'{"damaged":true}'
            source.write_bytes(content)
            expected = HASH_PREFIX + "0" * 64
            record = quarantine_file(
                source,
                root / "quarantine",
                reason="fixture hash mismatch",
                expected_hash=expected,
            )
            isolated = Path(record.quarantined_path)
            metadata = Path(record.metadata_path)
            self.assertFalse(source.exists())
            self.assertEqual(isolated.read_bytes(), content)
            self.assertEqual(record.content_hash, sha256_bytes(content))
            value = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertTrue(value["hash_mismatch"])
            self.assertEqual(value["observed_hash"], sha256_bytes(content))
            self.assertEqual(value["reason"], "fixture hash mismatch")
            self.assertRegex(value["quarantined_at"], r"\+00:00$")

    def test_quarantine_rejects_empty_reason_without_moving_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "suspect"
            source.write_bytes(b"evidence")
            with self.assertRaises(ValueError):
                quarantine_file(source, Path(temp_dir) / "quarantine", reason=" ")
            self.assertEqual(source.read_bytes(), b"evidence")


if __name__ == "__main__":
    unittest.main()
