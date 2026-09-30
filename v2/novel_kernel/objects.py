"""Versioned core.v3 Object, Facet, Relation, Fact, and Evidence validators.

The models remain JSON dictionaries so event payloads, future SQLite projections, and IDE
artifacts share one deterministic representation. No persistence or projection logic lives
in this M1.3 module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from .events import EVENT_ID_RE
from .storage import canonical_json_bytes, is_sha256

OBJECT_ID_RE = re.compile(
    r"^(?:book|vol|arc|ch|scene|beat|char|place|item|faction|thread|ob|obj)_[a-z0-9][a-z0-9_-]{0,95}$"
)
FACT_ID_RE = re.compile(r"^fact_[a-z0-9][a-z0-9_-]{0,95}$")
RELATION_ID_RE = re.compile(r"^rel_[a-z0-9][a-z0-9_-]{0,95}$")
EVIDENCE_ID_RE = re.compile(r"^evidence_[a-z0-9][a-z0-9_-]{0,95}$")
STABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
STORY_TIME_RE = re.compile(r"^story:[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")

OBJECT_FIELDS = frozenset(
    {"object_id", "type", "canonical_name", "aliases", "status", "created_event", "supersedes"}
)
FACET_FIELDS = frozenset(
    {"object_id", "facet_type", "facet_version", "payload", "valid_from", "valid_to", "source_refs", "recorded_event"}
)
RELATION_FIELDS = frozenset(
    {"relation_id", "subject_id", "predicate", "object_id", "valid_from", "valid_to", "recorded_event", "confidence", "evidence_refs"}
)
FACT_FIELDS = frozenset(
    {"fact_id", "subject_id", "predicate", "value", "valid_from", "valid_to", "recorded_event", "confidence", "status", "evidence_refs"}
)
EVIDENCE_FIELDS = frozenset(
    {"evidence_id", "source_type", "source_ref", "locator", "content_hash", "excerpt", "recorded_event"}
)

OBJECT_STATUSES = frozenset({"active", "retired", "superseded"})
FACET_TYPES = frozenset(
    {
        "identity", "appearance", "psychology", "capability", "voice", "knowledge",
        "resource", "location", "relationship", "status", "arc", "style", "constraint",
    }
)
RELATION_PREDICATES = frozenset(
    {"belongs_to", "knows", "owes", "located_at", "opposes", "possesses", "affects"}
)
CONFIDENCE_VALUES = frozenset({"confirmed", "probable", "disputed", "candidate"})
FACT_STATUSES = frozenset({"asserted", "disputed", "superseded"})
EVIDENCE_SOURCE_TYPES = frozenset({"outline", "chapter", "run", "human", "event"})


class ModelValidationError(ValueError):
    """A core model record violates its versioned schema."""


class ReferenceIntegrityError(ModelValidationError):
    """A validated record references an absent or wrong-kind record."""


@dataclass(frozen=True)
class ValidatedBundle:
    objects: tuple[dict[str, Any], ...]
    facets: tuple[dict[str, Any], ...]
    relations: tuple[dict[str, Any], ...]
    facts: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]


def _detach_json(value: Any, label: str) -> Any:
    try:
        import json

        return json.loads(canonical_json_bytes(value).decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ModelValidationError(f"{label} is not canonical JSON: {exc}") from exc


def _strict_record(value: Mapping[str, Any], fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelValidationError(f"{label} must be a JSON object")
    keys = set(value)
    missing = fields - keys
    extra = keys - fields
    if missing:
        raise ModelValidationError(f"{label} is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ModelValidationError(f"{label} has unknown fields: {', '.join(sorted(extra))}")
    detached = _detach_json(dict(value), label)
    if not isinstance(detached, dict):  # defensive; Mapping above already implies an object
        raise ModelValidationError(f"{label} must serialize to a JSON object")
    return detached


def _string(value: Any, label: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ModelValidationError(f"{label} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ModelValidationError(f"{label} has invalid format: {value!r}")
    return value


def _nullable_id(value: Any, label: str, pattern: re.Pattern[str]) -> str | None:
    if value is None:
        return None
    return _string(value, label, pattern)


def _string_list(value: Any, label: str, *, allow_empty: bool = True, pattern: re.Pattern[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        raise ModelValidationError(f"{label} must be a list")
    if not allow_empty and not value:
        raise ModelValidationError(f"{label} must not be empty")
    result = [_string(item, f"{label}[]", pattern) for item in value]
    if len(set(result)) != len(result):
        raise ModelValidationError(f"{label} must not contain duplicates")
    return result


def _enum(value: Any, label: str, allowed: frozenset[str]) -> str:
    result = _string(value, label)
    if result not in allowed:
        raise ModelValidationError(f"{label} has unsupported value: {result}")
    return result


def _number_0_1(value: Any, label: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ModelValidationError(f"{label} must be a number between 0 and 1")
    return value


def _story_time(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    result = _string(value, label)
    if result != "unknown" and STORY_TIME_RE.fullmatch(result) is None:
        raise ModelValidationError(f"{label} must be 'unknown' or a story:<ordered-key>")
    return result


def _time_window(record: Mapping[str, Any]) -> None:
    start = _story_time(record["valid_from"], "valid_from")
    end = _story_time(record["valid_to"], "valid_to", nullable=True)
    if start not in {None, "unknown"} and end not in {None, "unknown"} and end < start:
        raise ModelValidationError("valid_to must not sort before valid_from")


def _event_id(value: Any, label: str) -> str:
    return _string(value, label, EVENT_ID_RE)


def _source_refs(value: Any, label: str = "source_refs") -> list[str]:
    return _string_list(value, label, allow_empty=False)


def validate_object(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _strict_record(value, OBJECT_FIELDS, "object")
    object_id = _string(record["object_id"], "object_id", OBJECT_ID_RE)
    _string(record["type"], "type", STABLE_NAME_RE)
    _string(record["canonical_name"], "canonical_name")
    aliases = _string_list(record["aliases"], "aliases")
    if record["canonical_name"] in aliases:
        raise ModelValidationError("aliases must not repeat canonical_name")
    _enum(record["status"], "status", OBJECT_STATUSES)
    _event_id(record["created_event"], "created_event")
    supersedes = _nullable_id(record["supersedes"], "supersedes", OBJECT_ID_RE)
    if supersedes == object_id:
        raise ModelValidationError("object must not supersede itself")
    return record


def _payload_identity(payload: dict[str, Any]) -> None:
    _string(payload["identity_kind"], "payload.identity_kind", STABLE_NAME_RE)
    if "legal_name" in payload:
        _string(payload["legal_name"], "payload.legal_name")
    if "pronouns" in payload:
        _string_list(payload["pronouns"], "payload.pronouns")


def _payload_appearance(payload: dict[str, Any]) -> None:
    _string(payload["description"], "payload.description")
    if "markers" in payload:
        _string_list(payload["markers"], "payload.markers")


def _payload_psychology(payload: dict[str, Any]) -> None:
    for field in ("current_motive", "want", "fear"):
        _string(payload[field], f"payload.{field}")
    if "fear_threshold" in payload:
        _number_0_1(payload["fear_threshold"], "payload.fear_threshold")
    if "cognitive_bias" in payload:
        _string(payload["cognitive_bias"], "payload.cognitive_bias", STABLE_NAME_RE)


def _payload_capability(payload: dict[str, Any]) -> None:
    _string_list(payload["capabilities"], "payload.capabilities", allow_empty=False)
    if "limitations" in payload:
        _string_list(payload["limitations"], "payload.limitations")


def _payload_voice(payload: dict[str, Any]) -> None:
    _string_list(payload["style_markers"], "payload.style_markers", allow_empty=False)
    if "forbidden_patterns" in payload:
        _string_list(payload["forbidden_patterns"], "payload.forbidden_patterns")


def _payload_knowledge(payload: dict[str, Any]) -> None:
    _string_list(payload["fact_ids"], "payload.fact_ids", pattern=FACT_ID_RE)
    if "uncertain_fact_ids" in payload:
        _string_list(payload["uncertain_fact_ids"], "payload.uncertain_fact_ids", pattern=FACT_ID_RE)


def _payload_resource(payload: dict[str, Any]) -> None:
    resources = payload["resources"]
    if not isinstance(resources, dict) or not resources:
        raise ModelValidationError("payload.resources must be a non-empty JSON object")
    for key in resources:
        _string(key, "payload.resources key", STABLE_NAME_RE)
    _detach_json(resources, "payload.resources")
    if "unit" in payload:
        _string(payload["unit"], "payload.unit")


def _payload_location(payload: dict[str, Any]) -> None:
    place_id = _string(payload["place_id"], "payload.place_id", OBJECT_ID_RE)
    if not place_id.startswith("place_"):
        raise ModelValidationError("payload.place_id must identify a place")
    if "arrival_story_seq" in payload:
        _story_time(payload["arrival_story_seq"], "payload.arrival_story_seq")


def _payload_relationship(payload: dict[str, Any]) -> None:
    _string_list(payload["relation_ids"], "payload.relation_ids", pattern=RELATION_ID_RE)


def _payload_status(payload: dict[str, Any]) -> None:
    _string(payload["state"], "payload.state", STABLE_NAME_RE)
    if "detail" in payload:
        _string(payload["detail"], "payload.detail")


def _payload_arc(payload: dict[str, Any]) -> None:
    _string(payload["stage"], "payload.stage", STABLE_NAME_RE)
    if "goal" in payload:
        _string(payload["goal"], "payload.goal")
    if "progress" in payload:
        _number_0_1(payload["progress"], "payload.progress")


def _payload_style(payload: dict[str, Any]) -> None:
    _string_list(payload["directives"], "payload.directives", allow_empty=False)
    if "avoid" in payload:
        _string_list(payload["avoid"], "payload.avoid")


def _payload_constraint(payload: dict[str, Any]) -> None:
    _string_list(payload["rules"], "payload.rules", allow_empty=False)
    if "severity" in payload:
        _enum(payload["severity"], "payload.severity", frozenset({"warning", "hard"}))


# required fields, optional fields, and semantic validator for every frozen v1 Facet.
FACET_PAYLOAD_SCHEMAS: dict[str, tuple[frozenset[str], frozenset[str], Callable[[dict[str, Any]], None]]] = {
    "identity": (frozenset({"identity_kind"}), frozenset({"legal_name", "pronouns"}), _payload_identity),
    "appearance": (frozenset({"description"}), frozenset({"markers"}), _payload_appearance),
    "psychology": (frozenset({"current_motive", "want", "fear"}), frozenset({"fear_threshold", "cognitive_bias"}), _payload_psychology),
    "capability": (frozenset({"capabilities"}), frozenset({"limitations"}), _payload_capability),
    "voice": (frozenset({"style_markers"}), frozenset({"forbidden_patterns"}), _payload_voice),
    "knowledge": (frozenset({"fact_ids"}), frozenset({"uncertain_fact_ids"}), _payload_knowledge),
    "resource": (frozenset({"resources"}), frozenset({"unit"}), _payload_resource),
    "location": (frozenset({"place_id"}), frozenset({"arrival_story_seq"}), _payload_location),
    "relationship": (frozenset({"relation_ids"}), frozenset(), _payload_relationship),
    "status": (frozenset({"state"}), frozenset({"detail"}), _payload_status),
    "arc": (frozenset({"stage"}), frozenset({"goal", "progress"}), _payload_arc),
    "style": (frozenset({"directives"}), frozenset({"avoid"}), _payload_style),
    "constraint": (frozenset({"rules"}), frozenset({"severity"}), _payload_constraint),
}


def validate_facet(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _strict_record(value, FACET_FIELDS, "facet")
    _string(record["object_id"], "object_id", OBJECT_ID_RE)
    facet_type = _enum(record["facet_type"], "facet_type", FACET_TYPES)
    version = record["facet_version"]
    if isinstance(version, bool) or version != 1:
        raise ModelValidationError("facet_version must be integer 1")
    payload = record["payload"]
    if not isinstance(payload, dict):
        raise ModelValidationError("payload must be a JSON object")
    required, optional, validator = FACET_PAYLOAD_SCHEMAS[facet_type]
    keys = set(payload)
    missing = required - keys
    extra = keys - required - optional
    if missing:
        raise ModelValidationError(f"{facet_type} payload is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ModelValidationError(f"{facet_type} payload has unknown fields: {', '.join(sorted(extra))}")
    validator(payload)
    _time_window(record)
    _source_refs(record["source_refs"])
    _event_id(record["recorded_event"], "recorded_event")
    return record


def _endpoint(value: Any, label: str) -> str:
    result = _string(value, label)
    if OBJECT_ID_RE.fullmatch(result) is None and FACT_ID_RE.fullmatch(result) is None:
        raise ModelValidationError(f"{label} must be an Object or Fact ID")
    return result


def validate_relation(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _strict_record(value, RELATION_FIELDS, "relation")
    _string(record["relation_id"], "relation_id", RELATION_ID_RE)
    _endpoint(record["subject_id"], "subject_id")
    _enum(record["predicate"], "predicate", RELATION_PREDICATES)
    _endpoint(record["object_id"], "object_id")
    _time_window(record)
    _event_id(record["recorded_event"], "recorded_event")
    _enum(record["confidence"], "confidence", CONFIDENCE_VALUES)
    _source_refs(record["evidence_refs"], "evidence_refs")
    return record


def validate_fact(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _strict_record(value, FACT_FIELDS, "fact")
    _string(record["fact_id"], "fact_id", FACT_ID_RE)
    _string(record["subject_id"], "subject_id", OBJECT_ID_RE)
    _string(record["predicate"], "predicate", STABLE_NAME_RE)
    _detach_json(record["value"], "value")
    _time_window(record)
    _event_id(record["recorded_event"], "recorded_event")
    _enum(record["confidence"], "confidence", CONFIDENCE_VALUES)
    _enum(record["status"], "status", FACT_STATUSES)
    _source_refs(record["evidence_refs"], "evidence_refs")
    return record


def validate_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _strict_record(value, EVIDENCE_FIELDS, "evidence")
    _string(record["evidence_id"], "evidence_id", EVIDENCE_ID_RE)
    _enum(record["source_type"], "source_type", EVIDENCE_SOURCE_TYPES)
    _string(record["source_ref"], "source_ref")
    locator = record["locator"]
    if not isinstance(locator, dict) or not locator:
        raise ModelValidationError("locator must be a non-empty JSON object")
    allowed = {"start", "end", "section"}
    extra = set(locator) - allowed
    if extra:
        raise ModelValidationError(f"locator has unknown fields: {', '.join(sorted(extra))}")
    for field in ("start", "end"):
        if field in locator and (isinstance(locator[field], bool) or not isinstance(locator[field], int) or locator[field] < 0):
            raise ModelValidationError(f"locator.{field} must be a non-negative integer")
    if "start" in locator and "end" in locator and locator["end"] < locator["start"]:
        raise ModelValidationError("locator.end must not be less than locator.start")
    if "section" in locator:
        _string(locator["section"], "locator.section")
    content_hash = _string(record["content_hash"], "content_hash")
    if not is_sha256(content_hash):
        raise ModelValidationError("content_hash must use sha256:<64 lowercase hex> format")
    if record["excerpt"] is not None:
        _string(record["excerpt"], "excerpt")
    _event_id(record["recorded_event"], "recorded_event")
    return record


def _unique(records: Sequence[dict[str, Any]], id_field: str, label: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        identifier = record[id_field]
        if identifier in index:
            raise ReferenceIntegrityError(f"duplicate {label} ID: {identifier}")
        index[identifier] = record
    return index


def _check_evidence_refs(records: Iterable[dict[str, Any]], evidence_ids: set[str]) -> None:
    for record in records:
        for reference in record["evidence_refs"]:
            if reference.startswith("evidence_") and reference not in evidence_ids:
                raise ReferenceIntegrityError(f"unknown evidence reference: {reference}")


def validate_model_bundle(
    *,
    objects: Sequence[Mapping[str, Any]] = (),
    facets: Sequence[Mapping[str, Any]] = (),
    relations: Sequence[Mapping[str, Any]] = (),
    facts: Sequence[Mapping[str, Any]] = (),
    evidence: Sequence[Mapping[str, Any]] = (),
) -> ValidatedBundle:
    validated_objects = tuple(validate_object(item) for item in objects)
    validated_facets = tuple(validate_facet(item) for item in facets)
    validated_relations = tuple(validate_relation(item) for item in relations)
    validated_facts = tuple(validate_fact(item) for item in facts)
    validated_evidence = tuple(validate_evidence(item) for item in evidence)

    object_index = _unique(validated_objects, "object_id", "object")
    fact_index = _unique(validated_facts, "fact_id", "fact")
    relation_index = _unique(validated_relations, "relation_id", "relation")
    evidence_index = _unique(validated_evidence, "evidence_id", "evidence")
    endpoints = set(object_index) | set(fact_index)

    for item in validated_objects:
        supersedes = item["supersedes"]
        if supersedes is not None and supersedes not in object_index:
            raise ReferenceIntegrityError(f"object supersedes unknown object: {supersedes}")
    for item in validated_facets:
        if item["object_id"] not in object_index:
            raise ReferenceIntegrityError(f"facet references unknown object: {item['object_id']}")
        payload = item["payload"]
        if item["facet_type"] == "knowledge":
            for fact_id in payload["fact_ids"] + payload.get("uncertain_fact_ids", []):
                if fact_id not in fact_index:
                    raise ReferenceIntegrityError(f"knowledge facet references unknown fact: {fact_id}")
        elif item["facet_type"] == "location" and payload["place_id"] not in object_index:
            raise ReferenceIntegrityError(f"location facet references unknown place: {payload['place_id']}")
        elif item["facet_type"] == "relationship":
            for relation_id in payload["relation_ids"]:
                if relation_id not in relation_index:
                    raise ReferenceIntegrityError(f"relationship facet references unknown relation: {relation_id}")
    for item in validated_facts:
        if item["subject_id"] not in object_index:
            raise ReferenceIntegrityError(f"fact references unknown subject: {item['subject_id']}")
    for item in validated_relations:
        if item["subject_id"] not in endpoints:
            raise ReferenceIntegrityError(f"relation references unknown subject: {item['subject_id']}")
        if item["object_id"] not in endpoints:
            raise ReferenceIntegrityError(f"relation references unknown object: {item['object_id']}")
    _check_evidence_refs((*validated_relations, *validated_facts), set(evidence_index))

    return ValidatedBundle(
        objects=validated_objects,
        facets=validated_facets,
        relations=validated_relations,
        facts=validated_facts,
        evidence=validated_evidence,
    )
