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
from novel_kernel.three_chapter_smoke import ThreeChapterSmoke

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "workspace" / "_fixture" / "outline" / "valid-semantic" / "outline"
THRESHOLDS = ROOT / "calibration" / "soft-v1" / "soft-threshold-bundle.v1.json"


class ThreeChapterSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.book = self.root / "book_demo"
        shutil.copytree(FIXTURE, self.book / "outline")
        manifest_path = self.book / "outline" / "00-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "approved"
        manifest["approval"] = {"owner": "author", "approved_at": "2026-09-30T09:00:00+08:00"}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        chapter_map_path = self.book / "outline" / "12-chapter-map.json"
        first = json.loads(chapter_map_path.read_text(encoding="utf-8"))[0]
        chapters = []
        for number, (predicate, value) in enumerate(
            (("smoke_one", "observed"), ("smoke_two", "observed"), ("smoke_three", "observed")), 1
        ):
            chapter = json.loads(json.dumps(first))
            chapter["id"] = f"ch_{number:03d}"
            chapter["time"] = {
                "start": f"story:0019-04-0{number}T08:00",
                "end": f"story:0019-04-0{number}T12:00",
            }
            chapter["intent"]["required_events"] = ["event_first_attack"]
            chapter["intent"]["required_changes"] = [f"char_lin_yun.{predicate}={value}"]
            chapter["beats"][0]["id"] = f"beat_{number:03d}_01"
            chapters.append(chapter)
        chapter_map_path.write_text(json.dumps(chapters, ensure_ascii=False), encoding="utf-8")
        OutlineCompiler().compile(self.book / "outline")
        OutlineBootstrapper().bootstrap(self.book / "outline")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _prose() -> dict[str, str]:
        def claim(predicate: str) -> str:
            payload = json.dumps(
                {"subject_id": "char_lin_yun", "predicate": predicate, "value": "observed"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            return f'<!-- novel:claim {payload} -->'

        return {
            "ch_001": "第一章事实被观察。" + claim("smoke_one"),
            "ch_002": "警钟回响。警钟回响。警钟回响。警钟回响。" + claim("smoke_two"),
            "ch_003": "恢复后第三章事实仍被观察。" + claim("smoke_three"),
        }

    @staticmethod
    def _interrupt_after_prefix(book: Path, run_id: str) -> None:
        original = EventLog.append_many

        def append_prefix_then_fail(log: EventLog, candidates):
            events = tuple(candidates)
            original(log, events[:2])
            raise EventLogError("injected interruption after deterministic authority prefix")

        EventLog.append_many = append_prefix_then_fail
        try:
            ChapterCommitter().commit(book, run_id=run_id, actor="human.editor")
        finally:
            EventLog.append_many = original

    def test_three_chapter_restore_and_interrupted_commit_have_no_silent_loss(self) -> None:
        report_path = self.root / "three-chapter-smoke-report.json"
        restored = self.root / "recovered" / "book_demo"
        report = ThreeChapterSmoke().run(
            self.book,
            thresholds_path=THRESHOLDS,
            evaluated_at="2026-09-30T00:00:00+00:00",
            prose_by_chapter=self._prose(),
            interrupt=self._interrupt_after_prefix,
            restore_target=restored,
            report_path=report_path,
        )
        self.assertTrue(report.ok, report_path.read_text(encoding="utf-8"))
        self.assertTrue(report.interruption_recovered)
        self.assertFalse(report.silent_data_loss)
        self.assertEqual(report.chapter_count, 3)
        self.assertGreaterEqual(report.fact_count, 3)
        self.assertEqual(report.ced["window_size"], 3)
        self.assertEqual(report.ced["error_count"], 0)
        self.assertGreaterEqual(report.ced["advisory_findings_excluded"], 1)
        document = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(all(document["loss_checks"].values()))
        self.assertTrue(document["snapshot"]["restored_before_chapter_three"])
        self.assertFalse(document["scope"]["challenge_false_negatives_changed"])
        self.assertFalse(document["scope"]["hard_gate_promoted"])
        self.assertEqual(len(list((restored / "chapters").glob("ch_*.md"))), 3)


if __name__ == "__main__":
    unittest.main()
