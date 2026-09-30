from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from novel_kernel.objects import (
    FACET_TYPES,
    ModelValidationError,
    ReferenceIntegrityError,
    validate_evidence,
    validate_facet,
    validate_fact,
    validate_model_bundle,
    validate_object,
    validate_relation,
)
from novel_kernel.storage import sha256_bytes

EVENT = "event_00000000000000000000000000000001"


def object_record(object_id: str = "char_lin_yun", object_type: str = "character") -> dict:
    return {
        "object_id": object_id,
        "type": object_type,
        "canonical_name": "凌云",
        "aliases": ["云舟"],
        "status": "active",
        "created_event": EVENT,
        "supersedes": None,
    }


def facet_record(facet_type: str, payload: dict, object_id: str = "char_lin_yun") -> dict:
    return {
        "object_id": object_id,
        "facet_type": facet_type,
        "facet_version": 1,
        "payload": payload,
        "valid_from": "story:0001-01-01T00:00",
        "valid_to": None,
        "source_refs": ["outline/cast.json#char_lin_yun"],
        "recorded_event": EVENT,
    }


def evidence_record(evidence_id: str = "evidence_ch001_p1") -> dict:
    return {
        "evidence_id": evidence_id,
        "source_type": "chapter",
        "source_ref": "chapters/ch_001.md",
        "locator": {"start": 0, "end": 12, "section": "p1"},
        "content_hash": sha256_bytes("凌云走进山门".encode("utf-8")),
        "excerpt": "凌云走进山门",
        "recorded_event": EVENT,
    }


def fact_record(fact_id: str = "fact_lin_identity", subject_id: str = "char_lin_yun") -> dict:
    return {
        "fact_id": fact_id,
        "subject_id": subject_id,
        "predicate": "true_identity",
        "value": "剑宗遗孤",
        "valid_from": "story:0001-01-01T00:00",
        "valid_to": None,
        "recorded_event": EVENT,
        "confidence": "confirmed",
        "status": "asserted",
        "evidence_refs": ["evidence_ch001_p1"],
    }


def relation_record() -> dict:
    return {
        "relation_id": "rel_lin_knows_identity",
        "subject_id": "char_lin_yun",
        "predicate": "knows",
        "object_id": "fact_lin_identity",
        "valid_from": "story:0007-06-03T10:00",
        "valid_to": None,
        "recorded_event": EVENT,
        "confidence": "confirmed",
        "evidence_refs": ["evidence_ch001_p1"],
    }


class ObjectValidationTests(unittest.TestCase):
    def test_valid_object_is_detached_and_unicode_safe(self) -> None:
        source = object_record()
        result = validate_object(source)
        source["aliases"].append("后来添加")
        self.assertEqual(result["aliases"], ["云舟"])
        self.assertEqual(result["canonical_name"], "凌云")

    def test_object_rejects_unknown_missing_and_bad_id(self) -> None:
        base = object_record()
        cases = []
        missing = dict(base)
        del missing["status"]
        cases.append(missing)
        cases.append(dict(base, invented=True))
        cases.append(dict(base, object_id="凌云"))
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ModelValidationError):
                    validate_object(value)

    def test_object_rejects_alias_collision_and_self_supersede(self) -> None:
        alias = object_record()
        alias["aliases"] = ["凌云"]
        with self.assertRaisesRegex(ModelValidationError, "canonical_name"):
            validate_object(alias)
        self_ref = object_record()
        self_ref["supersedes"] = self_ref["object_id"]
        with self.assertRaisesRegex(ModelValidationError, "itself"):
            validate_object(self_ref)


class FacetValidationTests(unittest.TestCase):
    MINIMAL_PAYLOADS = {
        "identity": {"identity_kind": "human"},
        "appearance": {"description": "黑衣负剑"},
        "psychology": {"current_motive": "寻找真相", "want": "真相", "fear": "背叛"},
        "capability": {"capabilities": ["基础剑术"]},
        "voice": {"style_markers": ["寡言"]},
        "knowledge": {"fact_ids": ["fact_lin_identity"]},
        "resource": {"resources": {"spirit_stone": 3}},
        "location": {"place_id": "place_sword_sect"},
        "relationship": {"relation_ids": ["rel_lin_knows_identity"]},
        "status": {"state": "active"},
        "arc": {"stage": "setup"},
        "style": {"directives": ["短句"]},
        "constraint": {"rules": ["不可泄露身份"]},
    }

    def test_every_frozen_facet_type_has_a_working_v1_schema(self) -> None:
        self.assertEqual(set(self.MINIMAL_PAYLOADS), set(FACET_TYPES))
        for facet_type, payload in self.MINIMAL_PAYLOADS.items():
            with self.subTest(facet_type=facet_type):
                result = validate_facet(facet_record(facet_type, payload))
                self.assertEqual(result["facet_type"], facet_type)
                self.assertEqual(result["facet_version"], 1)

    def test_unknown_facet_type_and_version_are_rejected(self) -> None:
        with self.assertRaisesRegex(ModelValidationError, "unsupported"):
            validate_facet(facet_record("magic", {"level": 1}))
        value = facet_record("status", {"state": "active"})
        value["facet_version"] = 2
        with self.assertRaisesRegex(ModelValidationError, "integer 1"):
            validate_facet(value)

    def test_payload_missing_or_unknown_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(ModelValidationError, "missing fields"):
            validate_facet(facet_record("psychology", {"want": "真相", "fear": "背叛"}))
        with self.assertRaisesRegex(ModelValidationError, "unknown fields"):
            validate_facet(facet_record("status", {"state": "active", "magic": 99}))

    def test_invalid_time_window_and_empty_source_are_rejected(self) -> None:
        value = facet_record("status", {"state": "active"})
        value["valid_to"] = "story:0000"
        with self.assertRaisesRegex(ModelValidationError, "sort before"):
            validate_facet(value)
        value = facet_record("status", {"state": "active"})
        value["source_refs"] = []
        with self.assertRaisesRegex(ModelValidationError, "must not be empty"):
            validate_facet(value)

    def test_numeric_fields_reject_bool_nan_and_out_of_range(self) -> None:
        for invalid in (True, math.nan, 1.1, -0.1):
            value = facet_record(
                "psychology",
                {"current_motive": "真相", "want": "真相", "fear": "背叛", "fear_threshold": invalid},
            )
            with self.subTest(invalid=invalid):
                with self.assertRaises(ModelValidationError):
                    validate_facet(value)


class RelationFactEvidenceTests(unittest.TestCase):
    def test_valid_relation_fact_and_evidence(self) -> None:
        self.assertEqual(validate_relation(relation_record())["predicate"], "knows")
        self.assertEqual(validate_fact(fact_record())["status"], "asserted")
        self.assertEqual(validate_evidence(evidence_record())["source_type"], "chapter")

    def test_relation_rejects_natural_language_predicate_and_no_evidence(self) -> None:
        value = relation_record()
        value["predicate"] = "知道这个秘密"
        with self.assertRaisesRegex(ModelValidationError, "unsupported"):
            validate_relation(value)
        value = relation_record()
        value["evidence_refs"] = []
        with self.assertRaisesRegex(ModelValidationError, "must not be empty"):
            validate_relation(value)

    def test_fact_rejects_nan_and_natural_language_predicate(self) -> None:
        value = fact_record()
        value["value"] = float("nan")
        with self.assertRaisesRegex(ModelValidationError, "canonical JSON"):
            validate_fact(value)
        value = fact_record()
        value["predicate"] = "真实 身份"
        with self.assertRaisesRegex(ModelValidationError, "invalid format"):
            validate_fact(value)

    def test_evidence_rejects_bad_hash_locator_and_unknown_locator_field(self) -> None:
        bad_hash = evidence_record()
        bad_hash["content_hash"] = "abc"
        with self.assertRaisesRegex(ModelValidationError, "sha256"):
            validate_evidence(bad_hash)
        backward = evidence_record()
        backward["locator"] = {"start": 10, "end": 2}
        with self.assertRaisesRegex(ModelValidationError, "less than"):
            validate_evidence(backward)
        unknown = evidence_record()
        unknown["locator"] = {"page": 1}
        with self.assertRaisesRegex(ModelValidationError, "unknown fields"):
            validate_evidence(unknown)


class ModelBundleTests(unittest.TestCase):
    def valid_bundle(self):
        objects = [
            object_record(),
            {**object_record("place_sword_sect", "place"), "canonical_name": "剑宗", "aliases": []},
        ]
        facts = [fact_record()]
        evidence = [evidence_record()]
        relations = [relation_record()]
        facets = [
            facet_record("knowledge", {"fact_ids": ["fact_lin_identity"]}),
            facet_record("location", {"place_id": "place_sword_sect"}),
            facet_record("relationship", {"relation_ids": ["rel_lin_knows_identity"]}),
        ]
        return objects, facets, relations, facts, evidence

    def test_complete_bundle_resolves_all_references(self) -> None:
        objects, facets, relations, facts, evidence = self.valid_bundle()
        result = validate_model_bundle(
            objects=objects, facets=facets, relations=relations, facts=facts, evidence=evidence
        )
        self.assertEqual(len(result.objects), 2)
        self.assertEqual(len(result.facets), 3)
        objects[0]["canonical_name"] = "被调用方修改"
        self.assertEqual(result.objects[0]["canonical_name"], "凌云")

    def test_duplicate_ids_are_rejected(self) -> None:
        value = object_record()
        with self.assertRaisesRegex(ReferenceIntegrityError, "duplicate object"):
            validate_model_bundle(objects=[value, value])

    def test_unknown_object_fact_relation_and_evidence_refs_are_rejected(self) -> None:
        objects, facets, relations, facts, evidence = self.valid_bundle()
        mutations = []
        bad_facet = [dict(facets[0], object_id="char_missing"), *facets[1:]]
        mutations.append((bad_facet, relations, facts, evidence, "unknown object"))
        bad_knowledge = [facet_record("knowledge", {"fact_ids": ["fact_missing"]}), *facets[1:]]
        mutations.append((bad_knowledge, relations, facts, evidence, "unknown fact"))
        bad_relationship = [*facets[:2], facet_record("relationship", {"relation_ids": ["rel_missing"]})]
        mutations.append((bad_relationship, relations, facts, evidence, "unknown relation"))
        bad_relation = [dict(relations[0], evidence_refs=["evidence_missing"])]
        mutations.append((facets, bad_relation, facts, evidence, "unknown evidence"))
        for changed_facets, changed_relations, changed_facts, changed_evidence, message in mutations:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ReferenceIntegrityError, message):
                    validate_model_bundle(
                        objects=objects,
                        facets=changed_facets,
                        relations=changed_relations,
                        facts=changed_facts,
                        evidence=changed_evidence,
                    )


class SchemaArtifactTests(unittest.TestCase):
    def test_all_model_schemas_are_parseable_strict_draft_2020_documents(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        for name in ("event", "object", "facet", "relation", "fact", "evidence"):
            with self.subTest(name=name):
                value = json.loads((schema_root / f"{name}.schema.json").read_text(encoding="utf-8"))
                self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertFalse(value["additionalProperties"])
                self.assertTrue(value["required"])


if __name__ == "__main__":
    unittest.main()
