from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from novel_kernel.events import (
    DuplicateEventError,
    EventIntegrityError,
    EventLog,
    EventValidationError,
    HeadMismatchError,
    HeadUpdateError,
    ParentConflictError,
    build_event,
    validate_event,
)
from novel_kernel.storage import canonical_json_bytes, sha256_json


def event_id(number: int) -> str:
    return f"event_{number:032x}"


def make_event(
    number: int,
    *,
    parent: str | None,
    branch: str = "main",
    book_id: str = "book_demo",
    payload: dict | None = None,
    event_type: str = "fact.asserted",
    supersedes: str | None = None,
) -> dict:
    return build_event(
        event_id=event_id(number),
        event_type=event_type,
        book_id=book_id,
        branch_id=branch,
        parent_event_id=parent,
        story_seq=number,
        recorded_at=f"2026-09-29T08:{number % 60:02d}:00+00:00",
        actor_type="reconciler",
        actor_id="studio.reconcile",
        source_run_id="run_20260929_001",
        payload=payload or {"number": number},
        evidence_refs=[f"fixture#{number}"],
        supersedes=supersedes,
    )


class EventEnvelopeTests(unittest.TestCase):
    def test_builder_creates_core_v3_id_time_and_payload_hash(self) -> None:
        event = build_event(
            event_type="fact.asserted",
            book_id="book_demo",
            branch_id="main",
            parent_event_id=None,
            story_seq=0,
            actor_type="reconciler",
            actor_id="studio.reconcile",
            payload={"中文": "值", "a": 1},
        )
        self.assertRegex(event["event_id"], r"^event_[0-9a-f]{32}$")
        self.assertRegex(event["recorded_at"], r"\+00:00$")
        self.assertEqual(event["payload_hash"], sha256_json(event["payload"]))

    def test_validation_rejects_missing_and_unknown_fields(self) -> None:
        event = make_event(1, parent=None)
        missing = dict(event)
        del missing["actor_id"]
        with self.assertRaisesRegex(EventValidationError, "missing fields"):
            validate_event(missing)
        extra = dict(event, invented=True)
        with self.assertRaisesRegex(EventValidationError, "unknown fields"):
            validate_event(extra)

    def test_validation_rejects_payload_hash_mismatch(self) -> None:
        event = make_event(1, parent=None)
        event["payload"]["tampered"] = True
        with self.assertRaisesRegex(EventValidationError, "payload_hash mismatch"):
            validate_event(event)

    def test_validation_rejects_naive_time_bool_sequence_and_forbidden_actor(self) -> None:
        base = make_event(1, parent=None)
        cases = [
            ("recorded_at", "2026-09-29T08:00:00", "timezone-aware"),
            ("story_seq", True, "non-negative integer"),
            ("actor_type", "writer", "not authorized"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                event = dict(base)
                event[field] = value
                with self.assertRaisesRegex(EventValidationError, message):
                    validate_event(event)

    def test_builder_detaches_mutable_payload_and_evidence(self) -> None:
        payload = {"nested": {"value": 1}}
        evidence = ["source#1"]
        event = build_event(
            event_id=event_id(1), event_type="fact.asserted", book_id="book_demo",
            branch_id="main", parent_event_id=None, story_seq=1,
            actor_type="reconciler", actor_id="studio.reconcile",
            payload=payload, evidence_refs=evidence,
        )
        payload["nested"]["value"] = 2
        evidence.append("source#2")
        self.assertEqual(event["payload"]["nested"]["value"], 1)
        self.assertEqual(event["evidence_refs"], ["source#1"])


class EventLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.book = Path(self.temp.name) / "book_demo"
        self.log = EventLog(self.book)
        self.log.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_empty_log_verifies(self) -> None:
        report = self.log.verify()
        self.assertTrue(report.ok)
        self.assertEqual(report.event_count, 0)
        self.assertEqual(report.heads, {})
        self.assertEqual(self.log.log_path.read_bytes(), b"")

    def test_append_is_canonical_jsonl_and_updates_head(self) -> None:
        event = make_event(1, parent=None)
        result = self.log.append(event)
        self.assertEqual(result.line_number, 1)
        self.assertEqual(result.byte_offset, 0)
        self.assertEqual(self.log.log_path.read_bytes(), canonical_json_bytes(event) + b"\n")
        report = self.log.verify()
        self.assertEqual(report.event_count, 1)
        self.assertEqual(report.heads, {"main": event_id(1)})
        head = json.loads((self.log.heads_directory / "main.json").read_text(encoding="utf-8"))
        self.assertEqual(head["event_id"], event_id(1))
        self.assertEqual(head["event_count"], 1)

    def test_sequential_append_and_read(self) -> None:
        first = make_event(1, parent=None)
        second = make_event(2, parent=first["event_id"])
        self.log.append(first)
        self.log.append(second)
        self.assertEqual(self.log.read_events(), (first, second))
        self.assertEqual(self.log.verify().heads["main"], second["event_id"])

    def test_parent_conflict_does_not_modify_log(self) -> None:
        first = make_event(1, parent=None)
        self.log.append(first)
        before = self.log.log_path.read_bytes()
        conflicting = make_event(2, parent=event_id(99))
        with self.assertRaises(ParentConflictError):
            self.log.append(conflicting)
        self.assertEqual(self.log.log_path.read_bytes(), before)

    def test_duplicate_event_is_rejected(self) -> None:
        first = make_event(1, parent=None)
        self.log.append(first)
        duplicate = make_event(1, parent=first["event_id"])
        with self.assertRaises(DuplicateEventError):
            self.log.append(duplicate)

    def test_book_id_cannot_change(self) -> None:
        first = make_event(1, parent=None)
        self.log.append(first)
        wrong_book = make_event(2, parent=first["event_id"], book_id="book_other")
        with self.assertRaisesRegex(EventValidationError, "does not match"):
            self.log.append(wrong_book)

    def test_new_branch_must_fork_from_existing_event(self) -> None:
        first = make_event(1, parent=None)
        self.log.append(first)
        orphan = make_event(2, parent=None, branch="rewrite")
        with self.assertRaisesRegex(ParentConflictError, "must fork"):
            self.log.append(orphan)
        branch_event = make_event(3, parent=first["event_id"], branch="rewrite", event_type="branch.created")
        self.log.append(branch_event)
        next_branch = make_event(4, parent=branch_event["event_id"], branch="rewrite")
        self.log.append(next_branch)
        self.assertEqual(
            self.log.verify().heads,
            {"main": first["event_id"], "rewrite": next_branch["event_id"]},
        )

    def test_supersedes_must_reference_prior_event(self) -> None:
        first = make_event(1, parent=None, supersedes=event_id(99))
        with self.assertRaisesRegex(EventValidationError, "non-prior"):
            self.log.append(first)
        first = make_event(1, parent=None)
        self.log.append(first)
        correction = make_event(2, parent=first["event_id"], supersedes=first["event_id"])
        self.log.append(correction)
        self.assertEqual(self.log.verify().event_count, 2)

    def test_payload_tampering_is_detected(self) -> None:
        first = make_event(1, parent=None)
        self.log.append(first)
        value = json.loads(self.log.log_path.read_text(encoding="utf-8"))
        value["payload"]["tampered"] = True
        self.log.log_path.write_bytes(canonical_json_bytes(value) + b"\n")
        with self.assertRaisesRegex(EventIntegrityError, "payload_hash mismatch"):
            self.log.verify(verify_heads=False)

    def test_truncated_tail_is_detected(self) -> None:
        first = make_event(1, parent=None)
        self.log.append(first)
        raw = self.log.log_path.read_bytes()
        self.log.log_path.write_bytes(raw[:-1])
        with self.assertRaisesRegex(EventIntegrityError, "truncated final line"):
            self.log.verify(verify_heads=False)

    def test_parent_chain_tampering_is_detected_even_with_valid_hash(self) -> None:
        first = make_event(1, parent=None)
        second = make_event(2, parent=first["event_id"])
        self.log.append(first)
        self.log.append(second)
        lines = self.log.log_path.read_text(encoding="utf-8").splitlines()
        value = json.loads(lines[1])
        value["parent_event_id"] = event_id(99)
        lines[1] = canonical_json_bytes(value).decode("utf-8")
        self.log.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(EventIntegrityError, "parent chain mismatch"):
            self.log.verify(verify_heads=False)

    def test_stale_head_is_detected_and_rebuilt(self) -> None:
        first = make_event(1, parent=None)
        self.log.append(first)
        head = self.log.heads_directory / "main.json"
        head.write_text("{}", encoding="utf-8")
        with self.assertRaises(HeadMismatchError):
            self.log.verify()
        self.assertEqual(self.log.rebuild_heads(), {"main": first["event_id"]})
        self.assertTrue(self.log.verify().ok)

    def test_head_update_failure_keeps_authoritative_event_for_recovery(self) -> None:
        first = make_event(1, parent=None)
        with mock.patch("novel_kernel.events.atomic_write_json", side_effect=OSError("injected")):
            with self.assertRaises(HeadUpdateError):
                self.log.append(first)
        self.assertEqual(self.log.read_events(), (first,))
        self.assertEqual(self.log.rebuild_heads(), {"main": first["event_id"]})
        self.assertTrue(self.log.verify().ok)


if __name__ == "__main__":
    unittest.main()
