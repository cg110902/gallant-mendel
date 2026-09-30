from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from novel_kernel.chapter_commit import ChapterCommitter
from novel_kernel.events import EventLog, EventLogError
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.thirty_chapter_soak import ThirtyChapterSoak

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "workspace" / "_fixture" / "outline" / "valid-semantic" / "outline"
THRESHOLDS = ROOT / "calibration" / "soft-v1" / "soft-threshold-bundle.v1.json"


class ThirtyChapterSoakTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.book = self.root / "book_demo"
        shutil.copytree(FIXTURE, self.book / "outline")
        manifest_path = self.book / "outline" / "00-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "approved"
        manifest["approval"] = {"owner": "author", "approved_at": "2026-09-30T10:00:00+08:00"}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        map_path = self.book / "outline" / "12-chapter-map.json"
        template = json.loads(map_path.read_text(encoding="utf-8"))[0]
        chapters = []
        for number in range(1, 31):
            chapter = json.loads(json.dumps(template))
            chapter["id"] = f"ch_{number:03d}"
            chapter["time"] = {
                "start": f"story:0019-04-{number:02d}T08:00",
                "end": f"story:0019-04-{number:02d}T12:00",
            }
            chapter["intent"]["required_changes"] = [f"char_lin_yun.soak_{number:03d}=observed"]
            chapter["beats"][0]["id"] = f"beat_{number:03d}_01"
            chapters.append(chapter)
        map_path.write_text(json.dumps(chapters, ensure_ascii=False), encoding="utf-8")
        OutlineCompiler().compile(self.book / "outline")
        OutlineBootstrapper().bootstrap(self.book / "outline")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def prose(number: int) -> str:
        sentence = "警钟回响。" * 4 if number % 10 == 0 else f"第{number}章的控制事实被观察。"
        payload = json.dumps(
            {"subject_id": "char_lin_yun", "predicate": f"soak_{number:03d}", "value": "observed"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sentence + f"<!-- novel:claim {payload} -->"

    @staticmethod
    def interrupt_after_prefix(book: Path, run_id: str) -> None:
        original = EventLog.append_many

        def partial(log: EventLog, candidates):
            events = tuple(candidates)
            original(log, events[:2])
            raise EventLogError("injected chapter-twenty interruption")

        EventLog.append_many = partial
        try:
            ChapterCommitter().commit(book, run_id=run_id, actor="human.editor")
        finally:
            EventLog.append_many = original

    def test_thirty_chapter_soak_survives_outage_and_commit_interruption(self) -> None:
        report_path = self.root / "thirty-chapter-soak-report.json"
        report = ThirtyChapterSoak().run(
            self.book,
            thresholds_path=THRESHOLDS,
            evaluated_at="2026-09-30T00:00:00+00:00",
            prose_for_chapter=self.prose,
            restore_target=self.root / "recovered" / "book_demo",
            interrupt=self.interrupt_after_prefix,
            report_path=report_path,
        )
        self.assertTrue(report.ok, report_path.read_text(encoding="utf-8"))
        self.assertEqual(report.chapter_count, 30)
        self.assertEqual(report.snapshot_count, 2)
        self.assertTrue(report.interruption_recovered)
        self.assertFalse(report.silent_data_loss)
        document = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(all(document["loss_checks"].values()))
        self.assertEqual(document["ced"]["total_error_count"], 0)
        self.assertEqual(document["ced"]["overall_density"], 0)
        self.assertEqual(len(document["ced"]["windows"]), 3)
        self.assertGreaterEqual(document["ced"]["advisory_findings_excluded"], 3)
        self.assertFalse(document["scope"]["performance_threshold_applied"])
        self.assertFalse(document["scope"]["concurrent_writers_tested"])


if __name__ == "__main__":
    unittest.main()
