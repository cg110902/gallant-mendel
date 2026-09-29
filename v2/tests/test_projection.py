from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from novel_kernel.events import EventLog, build_event
from novel_kernel.projection import (
    PROJECTION_SCHEMA_VERSION,
    ProjectionApplyError,
    ProjectionStaleError,
    ProjectionStore,
)
from novel_kernel.storage import sha256_bytes, sha256_file


def eid(number: int) -> str:
    return f"event_{number:032x}"


def evidence(number: int, excerpt: str) -> dict:
    return {
        "evidence_id": f"evidence_{number:03d}",
        "source_type": "chapter",
        "source_ref": "chapters/ch_001.md",
        "locator": {"start": number * 10, "end": number * 10 + len(excerpt)},
        "content_hash": sha256_bytes(excerpt.encode("utf-8")),
        "excerpt": excerpt,
        "recorded_event": eid(number),
    }


def event(number: int, event_type: str, payload: dict, parent: str | None, branch: str = "main") -> dict:
    return build_event(
        event_id=eid(number),
        event_type=event_type,
        book_id="book_demo",
        branch_id=branch,
        parent_event_id=parent,
        story_seq=number,
        recorded_at=f"2026-09-29T09:{number:02d}:00+00:00",
        actor_type="reconciler",
        actor_id="studio.reconcile",
        source_run_id="run_20260929_projection",
        payload=payload,
    )


def object_value(number: int, object_id: str, kind: str, name: str) -> dict:
    return {
        "object_id": object_id,
        "type": kind,
        "canonical_name": name,
        "aliases": [],
        "status": "active",
        "created_event": eid(number),
        "supersedes": None,
    }


def ten_event_sequence() -> list[dict]:
    events: list[dict] = []
    parent = None
    values = [
        (1, "object.created", {"object": object_value(1, "char_lin_yun", "character", "凌云"), "evidence": []}),
        (2, "object.created", {"object": object_value(2, "place_sword_sect", "place", "剑宗"), "evidence": []}),
        (3, "fact.asserted", {
            "fact": {
                "fact_id": "fact_lin_identity", "subject_id": "char_lin_yun", "predicate": "true_identity",
                "value": "剑宗遗孤", "valid_from": "story:0001", "valid_to": None,
                "recorded_event": eid(3), "confidence": "confirmed", "status": "asserted",
                "evidence_refs": ["evidence_003"],
            },
            "evidence": [evidence(3, "他是剑宗遗孤")],
        }),
        (4, "relation.asserted", {
            "relation": {
                "relation_id": "rel_lin_knows_identity", "subject_id": "char_lin_yun", "predicate": "knows",
                "object_id": "fact_lin_identity", "valid_from": "story:0007", "valid_to": None,
                "recorded_event": eid(4), "confidence": "confirmed", "evidence_refs": ["evidence_003"],
            },
            "evidence": [],
        }),
        (5, "facet.asserted", {
            "facet": {
                "object_id": "char_lin_yun", "facet_type": "location", "facet_version": 1,
                "payload": {"place_id": "place_sword_sect"}, "valid_from": "story:0001", "valid_to": None,
                "source_refs": ["outline/cast.json#char_lin_yun"], "recorded_event": eid(5),
            },
            "evidence": [],
        }),
        (6, "facet.asserted", {
            "facet": {
                "object_id": "char_lin_yun", "facet_type": "psychology", "facet_version": 1,
                "payload": {"current_motive": "寻找真相", "want": "真相", "fear": "背叛"},
                "valid_from": "story:0001", "valid_to": None,
                "source_refs": ["outline/cast.json#char_lin_yun"], "recorded_event": eid(6),
            },
            "evidence": [],
        }),
        (7, "object.renamed", {"object_id": "char_lin_yun", "canonical_name": "凌云舟", "aliases": ["凌云"]}),
        (8, "fact.disputed", {"fact_id": "fact_lin_identity", "evidence": [evidence(8, "身份记录可能被伪造")]}),
        (9, "relation.invalidated", {"relation_id": "rel_lin_knows_identity", "valid_to": "story:0009"}),
        (10, "facet.superseded", {"object_id": "char_lin_yun", "facet_type": "psychology"}),
    ]
    for number, kind, payload in values:
        item = event(number, kind, payload, parent)
        events.append(item)
        parent = item["event_id"]
    return events


class ProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.book = Path(self.temp.name) / "book_demo"
        self.log = EventLog(self.book)
        for item in ten_event_sequence():
            self.log.append(item)
        self.store = ProjectionStore(self.book)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_rebuild_applies_ten_events_and_current_state(self) -> None:
        report = self.store.rebuild(self.log)
        self.assertTrue(report.ok)
        self.assertEqual(report.applied_event_count, 10)
        self.assertEqual(report.last_applied_event_id, eid(10))
        state = self.store.export_state()
        self.assertEqual(len(state["objects"]), 2)
        self.assertEqual(state["objects"][0]["canonical_name"], "凌云舟")
        self.assertEqual(state["facts"][0]["status"], "disputed")
        self.assertEqual(state["facts"][0]["evidence_refs"], ["evidence_003", "evidence_008"])
        self.assertEqual(state["relations"][0]["valid_to"], "story:0009")
        self.assertEqual([item["facet_type"] for item in state["facets"]], ["location"])
        self.assertEqual(len(state["evidence"]), 2)
        self.assertTrue(all(item["authority"] == "derived" for values in state.values() for item in values))

    def test_schema_metadata_and_foreign_keys_are_frozen(self) -> None:
        self.store.rebuild(self.log)
        connection = sqlite3.connect(self.store.database_path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            meta = connection.execute(
                "SELECT schema_version,branch_id,authority,applied_event_count FROM projection_meta"
            ).fetchone()
            self.assertEqual(meta, (PROJECTION_SCHEMA_VERSION, "main", "derived", 10))
        finally:
            connection.close()

    def test_rebuild_is_logically_deterministic_and_survives_database_deletion(self) -> None:
        first = self.store.rebuild(self.log)
        first_state = self.store.export_state()
        self.store.database_path.unlink()
        second = self.store.rebuild(self.log)
        self.assertEqual(first.state_hash, second.state_hash)
        self.assertEqual(first_state, self.store.export_state())

    def test_incremental_update_applies_only_new_suffix(self) -> None:
        initial = EventLog(Path(self.temp.name) / "incremental")
        sequence = ten_event_sequence()
        for item in sequence[:3]:
            initial.append(item)
        store = ProjectionStore(initial.book_root)
        self.assertEqual(store.rebuild(initial).applied_event_count, 3)
        for item in sequence[3:]:
            initial.append(item)
        report = store.update(initial)
        self.assertEqual(report.applied_event_count, 10)
        self.assertEqual(report.state_hash, self.store.rebuild(self.log).state_hash)

    def test_invalid_incremental_event_rolls_back_entire_transaction(self) -> None:
        before = self.store.rebuild(self.log)
        before_state = self.store.export_state()
        bad = event(
            11,
            "object.renamed",
            {"object_id": "char_missing", "canonical_name": "不存在", "aliases": []},
            eid(10),
        )
        self.log.append(bad)
        with self.assertRaisesRegex(ProjectionApplyError, "unknown object"):
            self.store.update(self.log)
        self.assertEqual(self.store.export_state(), before_state)
        connection = sqlite3.connect(self.store.database_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM projected_events").fetchone()[0], 10)
        finally:
            connection.close()
        self.assertEqual(before.applied_event_count, 10)

    def test_failed_rebuild_preserves_old_database_bytes(self) -> None:
        self.store.rebuild(self.log)
        before_hash = sha256_file(self.store.database_path)
        bad = event(11, "object.retired", {"object_id": "char_missing"}, eid(10))
        self.log.append(bad)
        with self.assertRaisesRegex(ProjectionApplyError, "unknown object"):
            self.store.rebuild(self.log)
        self.assertEqual(sha256_file(self.store.database_path), before_hash)

    def test_stale_metadata_is_rejected(self) -> None:
        self.store.rebuild(self.log)
        connection = sqlite3.connect(self.store.database_path)
        try:
            connection.execute("UPDATE projection_meta SET applied_event_count=9")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ProjectionStaleError, "event count"):
            self.store.verify(self.log)

    def test_get_object_decodes_json_fields(self) -> None:
        self.store.rebuild(self.log)
        value = self.store.get_object("char_lin_yun")
        self.assertIsNotNone(value)
        self.assertEqual(value["aliases"], ["凌云"])
        self.assertNotIn("aliases_json", value)
        self.assertIsNone(self.store.get_object("char_missing"))

    def test_branch_projection_inherits_only_lineage_ancestors(self) -> None:
        branch_book = Path(self.temp.name) / "branch"
        log = EventLog(branch_book)
        sequence = ten_event_sequence()
        for item in sequence:
            log.append(item)
        branch_created = event(
            11,
            "branch.created",
            {"from_event_id": eid(5), "name": "rewrite"},
            eid(5),
            branch="rewrite",
        )
        log.append(branch_created)
        renamed = event(
            12,
            "object.renamed",
            {"object_id": "char_lin_yun", "canonical_name": "分支凌云", "aliases": []},
            eid(11),
            branch="rewrite",
        )
        log.append(renamed)
        lineage = log.read_lineage("rewrite")
        self.assertEqual([item["event_id"] for item in lineage], [eid(i) for i in range(1, 6)] + [eid(11), eid(12)])
        branch_store = ProjectionStore(branch_book, branch_id="rewrite")
        report = branch_store.rebuild(log)
        self.assertEqual(report.applied_event_count, 7)
        self.assertEqual(branch_store.get_object("char_lin_yun")["canonical_name"], "分支凌云")
        self.assertEqual(branch_store.export_state()["facts"][0]["status"], "asserted")

    def test_non_business_event_is_audited_without_changing_domain_tables(self) -> None:
        self.store.rebuild(self.log)
        before = self.store.export_state()
        audit = event(11, "audit.completed", {"report": "ok"}, eid(10))
        self.log.append(audit)
        report = self.store.update(self.log)
        self.assertEqual(report.applied_event_count, 11)
        self.assertEqual(self.store.export_state(), before)


if __name__ == "__main__":
    unittest.main()
