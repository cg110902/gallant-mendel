"""M3.2 deterministic character/reader knowledge-boundary queries."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .events import EVENT_ID_RE, EventLog, EventLogError
from .storage import canonical_json_bytes, sha256_json
from .temporal import (
    TemporalQueryInputError,
    TemporalQueryIntegrityError,
    TemporalStateQuery,
)

CHARACTER_STATES = frozenset({"suspected", "believed", "confirmed", "false_belief"})
READER_STATES = frozenset({"clue", "suspected", "confirmed", "misled"})
SOURCE_EVENT_TYPES = frozenset({"scene.committed", "chapter.committed"})


@dataclass(frozen=True)
class KnowledgeDiffReport:
    ok: bool
    schema_version: str
    book_id: str
    branch_id: str
    cutoff: dict[str, Any]
    valid_at: str | None
    holder_id: str
    holder_edges: tuple[dict[str, Any], ...]
    reader_edges: tuple[dict[str, Any], ...]
    reader_only: tuple[str, ...]
    holder_only: tuple[str, ...]
    shared: tuple[str, ...]
    hidden_truth: tuple[str, ...]
    known_false_or_disputed: tuple[str, ...]
    knowledge_hash: str


def _copy(value: Any) -> Any:
    import json
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _exact(record: Mapping[str, Any], required: set[str], label: str) -> None:
    if set(record) != required:
        missing = sorted(required - set(record))
        unknown = sorted(set(record) - required)
        raise ValueError(f"{label} fields mismatch; missing={missing}, unknown={unknown}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _source_refs(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("source_refs must be a non-empty array")
    refs = [_nonempty_string(item, "source_refs item") for item in value]
    if len(set(refs)) != len(refs):
        raise ValueError("source_refs must be unique")
    return refs


def validate_knowledge_grant(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("knowledge must be an object")
    _exact(
        value,
        {"holder_id", "knowledge_id", "state", "confidence", "source_refs", "source_event_id"},
        "knowledge",
    )
    holder_id = _nonempty_string(value["holder_id"], "holder_id")
    knowledge_id = _nonempty_string(value["knowledge_id"], "knowledge_id")
    if not knowledge_id.startswith("fact_"):
        raise ValueError("knowledge_id must reference a fact")
    state = _nonempty_string(value["state"], "state")
    allowed = READER_STATES if holder_id == "_reader" else CHARACTER_STATES
    if state not in allowed:
        raise ValueError(f"state is invalid for holder {holder_id}")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be numeric")
    if not math.isfinite(float(confidence)) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be finite and within [0,1]")
    source_event_id = value["source_event_id"]
    if source_event_id is not None and (
        not isinstance(source_event_id, str) or EVENT_ID_RE.fullmatch(source_event_id) is None
    ):
        raise ValueError("source_event_id must be null or an event ID")
    return {
        "holder_id": holder_id,
        "knowledge_id": knowledge_id,
        "state": state,
        "confidence": confidence,
        "source_refs": _source_refs(value["source_refs"]),
        "source_event_id": source_event_id,
    }


class KnowledgeBoundaryQuery:
    def query(
        self,
        book_root: Path | str,
        *,
        holder_id: str,
        as_of: str,
        valid_at: str | None = None,
        branch_id: str = "main",
    ) -> KnowledgeDiffReport:
        if not isinstance(holder_id, str) or not holder_id or holder_id == "_reader":
            raise TemporalQueryInputError("--holder must identify a character, not _reader")

        temporal = TemporalStateQuery()
        truth_report = temporal.query(
            book_root, as_of=as_of, valid_at=valid_at, branch_id=branch_id
        )
        try:
            lineage = list(EventLog(book_root).read_lineage(branch_id))
        except EventLogError as exc:
            raise TemporalQueryIntegrityError(f"cannot read knowledge lineage: {exc}") from exc
        prefix, _ = temporal._cutoff(lineage, as_of)

        objects: dict[str, dict[str, Any]] = {}
        facts: set[str] = set()
        prior_events: dict[str, str] = {}
        edges: dict[tuple[str, str], dict[str, Any]] = {}

        for event in prefix:
            event_id = event["event_id"]
            kind = event["event_type"]
            payload = event["payload"]
            try:
                if kind == "object.created":
                    obj = payload["object"]
                    objects[obj["object_id"]] = obj
                elif kind == "fact.asserted":
                    facts.add(payload["fact"]["fact_id"])
                elif kind == "knowledge.granted":
                    _exact(payload, {"knowledge", "evidence"}, "knowledge.granted payload")
                    record = validate_knowledge_grant(payload["knowledge"])
                    holder = record["holder_id"]
                    knowledge_id = record["knowledge_id"]
                    if knowledge_id not in facts:
                        raise ValueError("knowledge_id does not reference a previously accepted fact")
                    if holder != "_reader":
                        obj = objects.get(holder)
                        if obj is None or obj.get("type") != "character":
                            raise ValueError("knowledge holder is not an accepted character")
                    source_event_id = record["source_event_id"]
                    if source_event_id is None:
                        if holder == "_reader" or not all(
                            ref.startswith("outline:") for ref in record["source_refs"]
                        ):
                            raise ValueError("only character outline knowledge may omit source_event_id")
                    else:
                        source_type = prior_events.get(source_event_id)
                        if source_type not in SOURCE_EVENT_TYPES:
                            raise ValueError("source_event_id must reference an earlier committed scene/chapter")
                        if holder == "_reader" and source_type != "chapter.committed":
                            raise ValueError("reader knowledge requires an earlier committed chapter")
                    key = (holder, knowledge_id)
                    if key in edges:
                        raise ValueError("knowledge edge is already active; retract before regrant")
                    edges[key] = {
                        **record,
                        "granted_event": event_id,
                        "known_at_seq": event["story_seq"],
                    }
                elif kind == "knowledge.retracted":
                    _exact(
                        payload,
                        {"holder_id", "knowledge_id", "reason", "source_refs", "evidence"},
                        "knowledge.retracted payload",
                    )
                    holder = _nonempty_string(payload["holder_id"], "holder_id")
                    knowledge_id = _nonempty_string(payload["knowledge_id"], "knowledge_id")
                    _nonempty_string(payload["reason"], "reason")
                    _source_refs(payload["source_refs"])
                    key = (holder, knowledge_id)
                    if key not in edges:
                        raise ValueError("knowledge retraction has no active edge")
                    del edges[key]
            except (KeyError, TypeError, ValueError) as exc:
                raise TemporalQueryIntegrityError(
                    f"cannot fold knowledge event {event_id} ({kind}): {exc}"
                ) from exc
            prior_events[event_id] = kind

        holder_object = objects.get(holder_id)
        if holder_object is None or holder_object.get("type") != "character":
            raise TemporalQueryInputError(f"holder is not a character in selected history: {holder_id}")

        holder_edges = tuple(
            sorted(
                (_copy(record) for (holder, _), record in edges.items() if holder == holder_id),
                key=lambda item: item["knowledge_id"],
            )
        )
        reader_edges = tuple(
            sorted(
                (_copy(record) for (holder, _), record in edges.items() if holder == "_reader"),
                key=lambda item: item["knowledge_id"],
            )
        )
        character_set = {item["knowledge_id"] for item in holder_edges}
        reader_set = {item["knowledge_id"] for item in reader_edges}
        truth_set = {item["fact_id"] for item in truth_report.facts if item["status"] == "asserted"}

        base = {
            "schema_version": "knowledge-diff.v1",
            "book_id": truth_report.book_id,
            "branch_id": branch_id,
            "cutoff": truth_report.cutoff,
            "valid_at": valid_at,
            "holder_id": holder_id,
            "holder_edges": holder_edges,
            "reader_edges": reader_edges,
            "reader_only": tuple(sorted(reader_set - character_set)),
            "holder_only": tuple(sorted(character_set - reader_set)),
            "shared": tuple(sorted(character_set & reader_set)),
            "hidden_truth": tuple(sorted(truth_set - (reader_set | character_set))),
            "known_false_or_disputed": tuple(sorted((reader_set | character_set) - truth_set)),
        }
        return KnowledgeDiffReport(
            ok=True,
            **base,
            knowledge_hash=sha256_json(base),
        )
