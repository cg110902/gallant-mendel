"""M3.3 deterministic Future Obligation lifecycle and as-of queries."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .events import EVENT_ID_RE, EventLog, EventLogError
from .storage import canonical_json_bytes, sha256_json
from .temporal import TemporalQueryInputError, TemporalQueryIntegrityError, TemporalStateQuery

OBLIGATION_ID_RE = re.compile(r"^ob_[A-Za-z0-9_-]+$")
ACTIVE = frozenset({"open", "touched", "deferred"})
TERMINAL = frozenset({"fulfilled", "subverted", "retired"})
RESOLUTIONS = frozenset({"fulfilled", "subverted", "deferred", "retired"})
COMMITTED_SOURCES = frozenset({"scene.committed", "chapter.committed"})
STATUS_FILTERS = ACTIVE | TERMINAL | {"active", "terminal", "due", "overdue"}


@dataclass(frozen=True)
class ObligationStateReport:
    ok: bool
    schema_version: str
    book_id: str
    branch_id: str
    cutoff: dict[str, Any]
    status_filter: str | None
    obligations: tuple[dict[str, Any], ...]
    active_count: int
    terminal_count: int
    due_count: int
    overdue_count: int
    obligation_hash: str


def _copy(value: Any) -> Any:
    import json
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _exact(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    if set(value) != fields:
        raise ValueError(
            f"{label} fields mismatch; missing={sorted(fields-set(value))}, "
            f"unknown={sorted(set(value)-fields)}"
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _refs(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("source_refs must be a non-empty array")
    refs = [_text(item, "source_refs item") for item in value]
    if len(set(refs)) != len(refs):
        raise ValueError("source_refs must be unique")
    return refs


def _window(value: Any, label: str = "expected_window") -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    _exact(value, {"earliest", "latest"}, label)
    earliest, latest = value["earliest"], value["latest"]
    if isinstance(earliest, bool) or isinstance(latest, bool) or not isinstance(earliest, int) or not isinstance(latest, int):
        raise ValueError(f"{label} bounds must be integers")
    if earliest <= 0 or latest <= 0 or earliest > latest:
        raise ValueError(f"{label} must be a positive ordered window")
    return {"earliest": earliest, "latest": latest}


def validate_obligation(value: Mapping[str, Any], story_seq: int) -> dict[str, Any]:
    fields = {
        "obligation_id", "kind", "owner_id", "created_at_story_seq", "expected_window",
        "weight", "status", "last_touched_seq", "payoff_event_id", "allowed_resolution",
        "reader_visibility", "evidence_requirement", "source_refs",
    }
    _exact(value, fields, "obligation")
    obligation_id = _text(value["obligation_id"], "obligation_id")
    if OBLIGATION_ID_RE.fullmatch(obligation_id) is None:
        raise ValueError("obligation_id has an invalid format")
    created = value["created_at_story_seq"]
    if isinstance(created, bool) or not isinstance(created, int) or created != story_seq:
        raise ValueError("created_at_story_seq must equal carrying event story_seq")
    weight = value["weight"]
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(float(weight)) or not 0 <= weight <= 1:
        raise ValueError("weight must be finite and within [0,1]")
    if value["status"] != "open" or value["last_touched_seq"] is not None or value["payoff_event_id"] is not None:
        raise ValueError("new obligation must start open without touch or payoff")
    resolutions = value["allowed_resolution"]
    if not isinstance(resolutions, list) or not resolutions or len(set(resolutions)) != len(resolutions):
        raise ValueError("allowed_resolution must be a non-empty unique array")
    if any(item not in RESOLUTIONS for item in resolutions):
        raise ValueError("allowed_resolution contains an unsupported value")
    requirement = value["evidence_requirement"]
    _exact(requirement, {"min_clues", "payoff_requires"}, "evidence_requirement")
    min_clues = requirement["min_clues"]
    payoff_requires = requirement["payoff_requires"]
    if isinstance(min_clues, bool) or not isinstance(min_clues, int) or min_clues <= 0:
        raise ValueError("min_clues must be a positive integer")
    if not isinstance(payoff_requires, list) or not payoff_requires:
        raise ValueError("payoff_requires must be a non-empty array")
    requirements = [_text(item, "payoff requirement") for item in payoff_requires]
    if len(set(requirements)) != len(requirements):
        raise ValueError("payoff_requires must be unique")
    return {
        "obligation_id": obligation_id,
        "kind": _text(value["kind"], "kind"),
        "owner_id": _text(value["owner_id"], "owner_id"),
        "created_at_story_seq": created,
        "expected_window": _window(value["expected_window"]),
        "weight": weight,
        "status": "open",
        "last_touched_seq": None,
        "payoff_event_id": None,
        "allowed_resolution": list(resolutions),
        "reader_visibility": _text(value["reader_visibility"], "reader_visibility"),
        "evidence_requirement": {"min_clues": min_clues, "payoff_requires": requirements},
        "source_refs": _refs(value["source_refs"]),
        "clue_count": 0,
        "touch_count": 0,
        "defer_count": 0,
    }


class ObligationStateQuery:
    def query(
        self,
        book_root: Path | str,
        *,
        as_of: str,
        status: str | None = None,
        branch_id: str = "main",
    ) -> ObligationStateReport:
        if status is not None and status not in STATUS_FILTERS:
            raise TemporalQueryInputError(f"unsupported obligation status filter: {status}")
        temporal = TemporalStateQuery()
        state = temporal.query(book_root, as_of=as_of, branch_id=branch_id)
        try:
            lineage = list(EventLog(book_root).read_lineage(branch_id))
        except EventLogError as exc:
            raise TemporalQueryIntegrityError(f"cannot read obligation lineage: {exc}") from exc
        prefix, _ = temporal._cutoff(lineage, as_of)
        prior: dict[str, str] = {}
        obligations: dict[str, dict[str, Any]] = {}

        for event in prefix:
            event_id, kind, payload = event["event_id"], event["event_type"], event["payload"]
            try:
                if kind == "obligation.created":
                    _exact(payload, {"obligation", "evidence"}, "obligation.created payload")
                    record = validate_obligation(payload["obligation"], event["story_seq"])
                    oid = record["obligation_id"]
                    if oid in obligations:
                        raise ValueError("duplicate obligation")
                    record["created_event"] = event_id
                    obligations[oid] = record
                elif kind.startswith("obligation."):
                    self._transition(obligations, prior, event)
            except (KeyError, TypeError, ValueError) as exc:
                raise TemporalQueryIntegrityError(
                    f"cannot fold obligation event {event_id} ({kind}): {exc}"
                ) from exc
            prior[event_id] = kind

        position = state.cutoff["story_seq"]
        results: list[dict[str, Any]] = []
        for record in obligations.values():
            item = _copy(record)
            if item["status"] in TERMINAL:
                item["schedule_state"] = "closed"
            elif position < item["expected_window"]["earliest"]:
                item["schedule_state"] = "scheduled"
            elif position <= item["expected_window"]["latest"]:
                item["schedule_state"] = "due"
            else:
                item["schedule_state"] = "overdue"
            if self._matches(item, status):
                results.append(item)
        ordered = tuple(sorted(results, key=lambda item: item["obligation_id"]))
        all_records = list(obligations.values())
        schedule = []
        for item in all_records:
            if item["status"] in TERMINAL:
                schedule.append("closed")
            elif position < item["expected_window"]["earliest"]:
                schedule.append("scheduled")
            elif position <= item["expected_window"]["latest"]:
                schedule.append("due")
            else:
                schedule.append("overdue")
        base = {
            "schema_version": "obligation-state.v1",
            "book_id": state.book_id,
            "branch_id": branch_id,
            "cutoff": state.cutoff,
            "status_filter": status,
            "obligations": ordered,
            "active_count": sum(item["status"] in ACTIVE for item in all_records),
            "terminal_count": sum(item["status"] in TERMINAL for item in all_records),
            "due_count": schedule.count("due"),
            "overdue_count": schedule.count("overdue"),
        }
        return ObligationStateReport(ok=True, **base, obligation_hash=sha256_json(base))

    @staticmethod
    def _source(prior: dict[str, str], event_id: Any, *, retired: bool = False) -> str:
        if not isinstance(event_id, str) or EVENT_ID_RE.fullmatch(event_id) is None:
            raise ValueError("source event must be an event ID")
        allowed = COMMITTED_SOURCES | ({"audit.completed"} if retired else set())
        kind = prior.get(event_id)
        if kind not in allowed:
            raise ValueError("source event must reference an earlier committed narrative event")
        return event_id

    def _transition(
        self,
        obligations: dict[str, dict[str, Any]],
        prior: dict[str, str],
        event: dict[str, Any],
    ) -> None:
        kind, payload = event["event_type"], event["payload"]
        common = {"obligation_id", "source_refs", "evidence"}
        if kind == "obligation.touched":
            _exact(payload, common | {"touch_kind", "source_event_id"}, "touched payload")
        elif kind == "obligation.deferred":
            _exact(payload, common | {"new_expected_window", "reason", "source_event_id"}, "deferred payload")
        elif kind in {"obligation.fulfilled", "obligation.subverted"}:
            _exact(payload, common | {"payoff_event_id", "satisfied_requirements"}, "payoff payload")
        elif kind == "obligation.retired":
            _exact(payload, common | {"reason", "source_event_id"}, "retired payload")
        else:
            raise ValueError("unsupported obligation transition event")
        oid = _text(payload["obligation_id"], "obligation_id")
        record = obligations.get(oid)
        if record is None:
            raise ValueError("unknown obligation")
        if record["status"] in TERMINAL:
            raise ValueError("terminal obligation cannot transition")
        _refs(payload["source_refs"])

        if kind == "obligation.touched":
            if record["status"] not in ACTIVE:
                raise ValueError("touch requires active obligation")
            self._source(prior, payload["source_event_id"])
            touch_kind = payload["touch_kind"]
            if touch_kind not in {"clue", "reminder", "escalation"}:
                raise ValueError("unsupported touch_kind")
            record["status"] = "touched"
            record["last_touched_seq"] = event["story_seq"]
            record["touch_count"] += 1
            if touch_kind == "clue":
                record["clue_count"] += 1
        elif kind == "obligation.deferred":
            if record["status"] not in {"open", "touched"}:
                raise ValueError("defer requires open or touched obligation")
            if "deferred" not in record["allowed_resolution"]:
                raise ValueError("deferred resolution is not allowed")
            self._source(prior, payload["source_event_id"])
            _text(payload["reason"], "reason")
            window = _window(payload["new_expected_window"], "new_expected_window")
            if window["latest"] <= record["expected_window"]["latest"]:
                raise ValueError("deferred latest must move strictly later")
            record["expected_window"] = window
            record["status"] = "deferred"
            record["defer_count"] += 1
        elif kind in {"obligation.fulfilled", "obligation.subverted"}:
            resolution = kind.split(".", 1)[1]
            if record["status"] != "touched":
                raise ValueError("payoff requires touched obligation")
            if resolution not in record["allowed_resolution"]:
                raise ValueError(f"{resolution} resolution is not allowed")
            payoff = self._source(prior, payload["payoff_event_id"])
            requirements = payload["satisfied_requirements"]
            if not isinstance(requirements, list) or any(not isinstance(item, str) or not item for item in requirements):
                raise ValueError("satisfied_requirements must be a string array")
            if not set(record["evidence_requirement"]["payoff_requires"]).issubset(requirements):
                raise ValueError("payoff requirements are not satisfied")
            if record["clue_count"] < record["evidence_requirement"]["min_clues"]:
                raise ValueError("payoff has insufficient clue evidence")
            record["status"] = resolution
            record["payoff_event_id"] = payoff
        else:
            if "retired" not in record["allowed_resolution"]:
                raise ValueError("retired resolution is not allowed")
            source = self._source(prior, payload["source_event_id"], retired=True)
            _text(payload["reason"], "reason")
            record["status"] = "retired"
            record["payoff_event_id"] = source

    @staticmethod
    def _matches(record: dict[str, Any], status: str | None) -> bool:
        if status is None:
            return True
        if status == "active":
            return record["status"] in ACTIVE
        if status == "terminal":
            return record["status"] in TERMINAL
        if status in {"due", "overdue"}:
            return record["schedule_state"] == status
        return record["status"] == status
