from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from novel_kernel.events import EventLog, build_event
from novel_kernel.knowledge import KnowledgeBoundaryQuery
from novel_kernel.temporal import TemporalQueryIntegrityError

ROOT = Path(__file__).resolve().parents[1]


def eid(number: int) -> str:
    return f"event_{number:032x}"


def event(number: int, kind: str, payload: dict, parent: str | None, seq: int) -> dict:
    return build_event(
        event_id=eid(number),
        event_type=kind,
        book_id="book_knowledge",
        branch_id="main",
        parent_event_id=parent,
        story_seq=seq,
        recorded_at=f"2026-09-29T01:{number:02d}:00+00:00",
        actor_type="reconciler",
        actor_id="studio.knowledge-test",
        source_run_id="run_knowledge_tests",
        payload=payload,
    )


def fact(number: int, fact_id: str) -> dict:
    return {
        "fact": {
            "fact_id": fact_id,
            "subject_id": "char_hero",
            "predicate": "has_secret",
            "value": fact_id,
            "valid_from": "story:initial",
            "valid_to": None,
            "recorded_event": eid(number),
            "confidence": "confirmed",
            "status": "asserted",
            "evidence_refs": [f"outline:fact:{number}"],
        },
        "evidence": [],
    }


def grant(holder: str, knowledge_id: str, state: str, source_event: str | None) -> dict:
    prefix = "outline:cast#hero" if source_event is None else "chapter:ch_001#p1"
    return {
        "knowledge": {
            "holder_id": holder,
            "knowledge_id": knowledge_id,
            "state": state,
            "confidence": 0.75,
            "source_refs": [prefix],
            "source_event_id": source_event,
        },
        "evidence": [],
    }


def tree_hash(root: Path) -> str:
    values = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        values.append((str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


class KnowledgeBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.book = Path(self.temp.name) / "book_knowledge"
        log = EventLog(self.book)
        obj = {
            "object_id": "char_hero",
            "type": "character",
            "canonical_name": "Hero",
            "aliases": [],
            "status": "active",
            "created_event": eid(1),
            "supersedes": None,
        }
        events = [
            event(1, "object.created", {"object": obj, "evidence": []}, None, 0),
            event(2, "fact.asserted", fact(2, "fact_shared"), eid(1), 0),
            event(3, "fact.asserted", fact(3, "fact_holder"), eid(2), 0),
            event(4, "fact.asserted", fact(4, "fact_hidden"), eid(3), 0),
            event(5, "chapter.committed", {"chapter_id": "ch_001"}, eid(4), 1),
            event(6, "knowledge.granted", grant("_reader", "fact_shared", "confirmed", eid(5)), eid(5), 1),
            event(7, "knowledge.granted", grant("char_hero", "fact_holder", "believed", None), eid(6), 1),
            event(8, "knowledge.granted", grant("char_hero", "fact_shared", "confirmed", eid(5)), eid(7), 1),
            event(9, "knowledge.granted", grant("_reader", "fact_holder", "clue", eid(5)), eid(8), 2),
            event(10, "knowledge.retracted", {
                "holder_id": "char_hero", "knowledge_id": "fact_shared",
                "reason": "memory_corrected", "source_refs": ["chapter:ch_002#p2"], "evidence": []
            }, eid(9), 2),
        ]
        for item in events:
            log.append(item)
        self.query = KnowledgeBoundaryQuery()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_chapter_diff_keeps_truth_and_knowledge_separate(self) -> None:
        report = self.query.query(self.book, holder_id="char_hero", as_of="ch_001")
        self.assertEqual(report.shared, ("fact_shared",))
        self.assertEqual(report.holder_only, ("fact_holder",))
        self.assertEqual(report.reader_only, ())
        self.assertEqual(report.hidden_truth, ("fact_hidden",))

    def test_future_recorded_knowledge_does_not_leak_backward(self) -> None:
        before = self.query.query(self.book, holder_id="char_hero", as_of=eid(8))
        self.assertEqual([item["knowledge_id"] for item in before.reader_edges], ["fact_shared"])
        after = self.query.query(self.book, holder_id="char_hero", as_of=eid(9))
        self.assertEqual([item["knowledge_id"] for item in after.reader_edges], ["fact_holder", "fact_shared"])

    def test_retraction_changes_diff_without_deleting_history(self) -> None:
        head = self.query.query(self.book, holder_id="char_hero", as_of="head")
        self.assertEqual(head.reader_only, ("fact_shared",))
        old = self.query.query(self.book, holder_id="char_hero", as_of=eid(8))
        self.assertEqual(old.shared, ("fact_shared",))

    def test_reader_cannot_learn_from_outline_or_scene(self) -> None:
        bad_book = Path(self.temp.name) / "bad_reader"
        log = EventLog(bad_book)
        source = list(EventLog(self.book).read_lineage("main"))[:4]
        for item in source:
            log.append(item)
        bad = event(5, "knowledge.granted", grant("_reader", "fact_shared", "confirmed", None), eid(4), 1)
        log.append(bad)
        with self.assertRaisesRegex(TemporalQueryIntegrityError, "only character outline"):
            self.query.query(bad_book, holder_id="char_hero", as_of="head")

    def test_duplicate_grant_and_orphan_retraction_are_integrity_errors(self) -> None:
        duplicate = event(11, "knowledge.granted", grant("_reader", "fact_holder", "clue", eid(5)), eid(10), 3)
        EventLog(self.book).append(duplicate)
        with self.assertRaisesRegex(TemporalQueryIntegrityError, "already active"):
            self.query.query(self.book, holder_id="char_hero", as_of="head")

        orphan_book = Path(self.temp.name) / "orphan"
        log = EventLog(orphan_book)
        for item in list(EventLog(self.book).read_lineage("main"))[:4]:
            log.append(item)
        orphan = event(5, "knowledge.retracted", {
            "holder_id": "char_hero", "knowledge_id": "fact_shared", "reason": "invalid",
            "source_refs": ["outline:test"], "evidence": []
        }, eid(4), 1)
        log.append(orphan)
        with self.assertRaisesRegex(TemporalQueryIntegrityError, "no active edge"):
            self.query.query(orphan_book, holder_id="char_hero", as_of="head")

    def test_disputed_truth_remains_known_but_is_not_truth_set(self) -> None:
        disputed = event(11, "fact.disputed", {
            "fact_id": "fact_shared", "evidence": []
        }, eid(10), 3)
        EventLog(self.book).append(disputed)
        report = self.query.query(self.book, holder_id="char_hero", as_of="head")
        self.assertIn("fact_shared", report.known_false_or_disputed)
        self.assertNotIn("fact_shared", report.hidden_truth)

    def test_branch_inherits_ancestors_without_main_suffix_leak(self) -> None:
        branch_event = build_event(
            event_id=eid(20), event_type="knowledge.granted", book_id="book_knowledge",
            branch_id="feature", parent_event_id=eid(8), story_seq=2,
            recorded_at="2026-09-29T02:20:00+00:00", actor_type="reconciler",
            actor_id="studio.knowledge-test", source_run_id="run_knowledge_branch",
            payload=grant("_reader", "fact_hidden", "clue", eid(5)),
        )
        EventLog(self.book).append(branch_event)
        branch = self.query.query(self.book, holder_id="char_hero", as_of="head", branch_id="feature")
        main = self.query.query(self.book, holder_id="char_hero", as_of="head", branch_id="main")
        self.assertEqual([item["knowledge_id"] for item in branch.reader_edges], ["fact_hidden", "fact_shared"])
        self.assertEqual([item["knowledge_id"] for item in main.reader_edges], ["fact_holder", "fact_shared"])
        self.assertEqual(branch.shared, ("fact_shared",))
        self.assertEqual(main.reader_only, ("fact_shared",))

    def test_query_is_read_only_and_hash_is_deterministic(self) -> None:
        before = tree_hash(self.book)
        first = self.query.query(self.book, holder_id="char_hero", as_of="ch_001")
        second = self.query.query(self.book, holder_id="char_hero", as_of="ch_001")
        self.assertEqual(before, tree_hash(self.book))
        self.assertEqual(first.knowledge_hash, second.knowledge_hash)

    def test_cli_json_success_and_invalid_holder(self) -> None:
        good = subprocess.run(
            [sys.executable, str(ROOT / "studio.py"), "knowledge", "diff", "--path", str(self.book),
             "--holder", "char_hero", "--as-of", "ch_001", "--json"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)["schema_version"], "knowledge-diff.v1")
        bad = subprocess.run(
            [sys.executable, str(ROOT / "studio.py"), "knowledge", "diff", "--path", str(self.book),
             "--holder", "_reader", "--as-of", "head", "--json"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(bad.returncode, 1)


if __name__ == "__main__":
    unittest.main()
