from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from novel_kernel.events import EventLog
from novel_kernel.projection import ProjectionStore
from novel_kernel.snapshots import SnapshotError, SnapshotManager, SnapshotValidationError
from tests.test_projection import ten_event_sequence


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.book = Path(self.temp.name) / "book_demo"
        self.log = EventLog(self.book)
        self.log.append_many(ten_event_sequence())
        self.store = ProjectionStore(self.book)
        self.projection = self.store.rebuild(self.log)
        self.chapter = self.book / "chapters" / "ch_001.md"
        self.chapter.parent.mkdir(parents=True)
        self.chapter.write_text("# 第一章\n\n凌云走入山门。\n", encoding="utf-8")
        self.manager = SnapshotManager(self.book)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_snapshot(self):
        return self.manager.create(
            label="chapter-001",
            branch_id="main",
            artifact_paths=[Path("chapters/ch_001.md")],
        )

    def test_create_and_validate_complete_snapshot(self) -> None:
        before_count = len(self.log.read_events())
        report = self.create_snapshot()
        self.assertRegex(report.snapshot_id, r"^snapshot_[0-9a-f]{32}$")
        self.assertEqual(report.lineage_event_count, 10)
        self.assertEqual(report.head_event_id, ten_event_sequence()[-1]["event_id"])
        self.assertEqual(report.projection_state_hash, self.projection.state_hash)
        self.assertEqual(report.artifact_count, 1)
        self.assertEqual(len(self.log.read_events()), before_count, "infrastructure snapshot must not append authority")
        root = Path(report.path)
        self.assertTrue((root / "manifest.json").is_file())
        self.assertTrue((root / "ledger" / "events.jsonl").is_file())
        self.assertTrue((root / "state" / "state.db").is_file())
        self.assertEqual(
            (root / "artifacts" / "files" / "chapters" / "ch_001.md").read_text(encoding="utf-8"),
            self.chapter.read_text(encoding="utf-8"),
        )
        validated = SnapshotManager.validate(root)
        self.assertEqual(validated, report)

    def test_validation_is_read_only(self) -> None:
        report = self.create_snapshot()
        root = Path(report.path)
        before = {path.relative_to(root): (path.stat().st_size, path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()}
        SnapshotManager.validate(root)
        after = {path.relative_to(root): (path.stat().st_size, path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_event_artifact_and_sqlite_tampering_are_rejected(self) -> None:
        targets = [
            ("ledger/events.jsonl", b"tamper"),
            ("artifacts/files/chapters/ch_001.md", b"tamper"),
            ("state/state.db", b"not sqlite"),
        ]
        for relative, replacement in targets:
            with self.subTest(relative=relative):
                report = self.create_snapshot()
                root = Path(report.path)
                root.joinpath(*Path(relative).parts).write_bytes(replacement)
                with self.assertRaises(SnapshotValidationError):
                    SnapshotManager.validate(root)

    def test_undeclared_file_and_manifest_unknown_field_are_rejected(self) -> None:
        report = self.create_snapshot()
        root = Path(report.path)
        (root / "undeclared.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(SnapshotValidationError, "undeclared"):
            SnapshotManager.validate(root)

        report = self.create_snapshot()
        root = Path(report.path)
        manifest_path = root / "manifest.json"
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        value["invented"] = True
        manifest_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(SnapshotValidationError, "unknown fields"):
            SnapshotManager.validate(root)

    def test_restore_to_new_book_preserves_head_state_and_artifact(self) -> None:
        snapshot = self.create_snapshot()
        target = Path(self.temp.name) / "restored_book"
        restored = SnapshotManager.restore(snapshot.path, target)
        self.assertEqual(restored.head_event_id, snapshot.head_event_id)
        self.assertEqual(restored.lineage_event_count, snapshot.lineage_event_count)
        self.assertEqual(restored.projection_state_hash, snapshot.projection_state_hash)
        restored_log = EventLog(target)
        self.assertEqual(restored_log.verify().heads["main"], snapshot.head_event_id)
        restored_projection = ProjectionStore(target).verify(restored_log)
        self.assertEqual(restored_projection.state_hash, snapshot.projection_state_hash)
        self.assertEqual((target / "chapters" / "ch_001.md").read_bytes(), self.chapter.read_bytes())
        self.assertTrue((target / "snapshots" / snapshot.snapshot_id / "manifest.json").is_file())

    def test_restore_refuses_existing_target_without_modifying_it(self) -> None:
        snapshot = self.create_snapshot()
        target = Path(self.temp.name) / "existing"
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(SnapshotError, "refusing destructive overwrite"):
            SnapshotManager.restore(snapshot.path, target)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_artifact_boundary_rejects_reserved_outside_and_symlink(self) -> None:
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        with self.assertRaisesRegex(SnapshotError, "outside"):
            self.manager.create(label="bad", artifact_paths=[outside])
        with self.assertRaisesRegex(SnapshotError, "reserved"):
            self.manager.create(label="bad", artifact_paths=[self.store.database_path])
        if hasattr(os, "symlink"):
            link = self.book / "chapters" / "link.md"
            link.symlink_to(self.chapter)
            with self.assertRaisesRegex(SnapshotError, "non-symlink"):
                self.manager.create(label="bad", artifact_paths=[link])

    def test_failed_publish_cleans_temporary_snapshot_and_preserves_source(self) -> None:
        snapshots = self.book / "snapshots"
        with mock.patch.object(SnapshotManager, "validate", side_effect=SnapshotValidationError("injected")):
            with self.assertRaisesRegex(SnapshotValidationError, "injected"):
                self.manager.create(label="fault", artifact_paths=[self.chapter])
        self.assertEqual(list(snapshots.iterdir()), [])
        self.assertEqual(self.store.verify(self.log).state_hash, self.projection.state_hash)
        self.assertEqual(len(self.log.read_events()), 10)


class BatchAppendTests(unittest.TestCase):
    def test_batch_is_fully_validated_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log = EventLog(Path(temp_dir) / "book")
            sequence = ten_event_sequence()[:2]
            sequence[1]["parent_event_id"] = "event_ffffffffffffffffffffffffffffffff"
            with self.assertRaises(Exception):
                log.append_many(sequence)
            self.assertEqual(log.read_events(), ())

    def test_batch_results_have_contiguous_lines_and_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log = EventLog(Path(temp_dir) / "book")
            results = log.append_many(ten_event_sequence())
            self.assertEqual([result.line_number for result in results], list(range(1, 11)))
            for previous, current in zip(results, results[1:]):
                self.assertEqual(current.byte_offset, previous.byte_offset + previous.bytes_appended)
            self.assertEqual(log.verify().event_count, 10)


if __name__ == "__main__":
    unittest.main()
