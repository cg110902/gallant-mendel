from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from novel_kernel.chapter_commit import ChapterCommitter
from novel_kernel.concurrency_guard import ConcurrencyGuardProbe
from novel_kernel.events import EventLog, ParentConflictError, ResourceGuardError
from novel_kernel.production import ProductionResourceGuardError


class ConcurrencyGuardTests(unittest.TestCase):
    def test_real_lock_contention_and_same_parent_race_fail_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "concurrency-report.json"
            report = ConcurrencyGuardProbe().run(Path(temp) / "book_concurrency", report_path=path)
            self.assertTrue(report.ok)
            self.assertEqual(report.winner_count, 1)
            self.assertEqual(report.conflict_count, 1)
            self.assertEqual(report.lock_timeout_exit_code, 7)
            self.assertEqual(report.parent_conflict_exit_code, 7)
            self.assertFalse(report.silent_overwrite)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(document["lock_contention"]["authority_bytes_unchanged"])
            self.assertTrue(document["projection"]["head_matches_authority"])
            self.assertEqual(document["authority"]["event_count"], 2)

    def test_chapter_commit_maps_append_race_to_resource_guard_exit_seven(self) -> None:
        from tests import test_chapter_commit as chapter_fixture
        fixture = chapter_fixture.ChapterCommitTests(methodName="test_commit_is_idempotent")
        fixture.setUp()
        try:
            error = ParentConflictError("injected same-parent race")
            with mock.patch.object(EventLog, "append_many", side_effect=error):
                with self.assertRaises(ProductionResourceGuardError) as caught:
                    ChapterCommitter().commit(fixture.book, run_id=fixture.run_id, actor="human.editor")
            self.assertEqual(caught.exception.exit_code, 7)
            status = json.loads((fixture.run / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "commit_prepared")
            self.assertFalse((fixture.book / "chapters" / "ch_001.md").exists())
        finally:
            fixture.tearDown()

    def test_resource_errors_use_frozen_exit_code(self) -> None:
        self.assertEqual(ResourceGuardError.exit_code, 7)
        self.assertEqual(ParentConflictError.exit_code, 7)
        self.assertEqual(ProductionResourceGuardError.exit_code, 7)


if __name__ == "__main__":
    unittest.main()
