"""SQLite derived projection and deterministic EventLog replay (M1.4)."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .events import EventLog
from .objects import (
    EVIDENCE_ID_RE,
    FACET_TYPES,
    FACT_ID_RE,
    OBJECT_ID_RE,
    RELATION_ID_RE,
    STORY_TIME_RE,
    ModelValidationError,
    validate_evidence,
    validate_facet,
    validate_fact,
    validate_object,
    validate_relation,
)
from .storage import canonical_json_bytes, sha256_json

PROJECTION_SCHEMA_VERSION = "core.v3.sqlite.v1"
SQLITE_USER_VERSION = 1
PROJECTABLE_EVENTS = frozenset(
    {
        "object.created",
        "object.renamed",
        "object.retired",
        "facet.asserted",
        "facet.superseded",
        "relation.asserted",
        "relation.invalidated",
        "fact.asserted",
        "fact.disputed",
    }
)


class ProjectionError(Exception):
    """Base class for derived-state failures."""


class ProjectionStaleError(ProjectionError):
    """The database is not a prefix projection of the selected event lineage."""


class ProjectionApplyError(ProjectionError):
    """An event cannot be deterministically applied; the transaction is rolled back."""


@dataclass(frozen=True)
class ProjectionReport:
    ok: bool
    branch_id: str
    applied_event_count: int
    last_applied_event_id: str | None
    state_hash: str


_SCHEMA = """
PRAGMA user_version = 1;
CREATE TABLE projection_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    authority TEXT NOT NULL CHECK (authority = 'derived'),
    last_applied_event_id TEXT,
    applied_event_count INTEGER NOT NULL CHECK (applied_event_count >= 0)
);
CREATE TABLE projected_events (
    line_index INTEGER PRIMARY KEY CHECK (line_index > 0),
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    parent_event_id TEXT,
    payload_hash TEXT NOT NULL,
    canonical_json TEXT NOT NULL,
    authority TEXT NOT NULL CHECK (authority = 'derived')
);
CREATE TABLE objects (
    object_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_event TEXT NOT NULL REFERENCES projected_events(event_id),
    supersedes TEXT,
    last_event_id TEXT NOT NULL REFERENCES projected_events(event_id),
    authority TEXT NOT NULL CHECK (authority = 'derived')
);
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    locator_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    excerpt TEXT,
    recorded_event TEXT NOT NULL REFERENCES projected_events(event_id),
    authority TEXT NOT NULL CHECK (authority = 'derived')
);
CREATE TABLE facts (
    fact_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES objects(object_id),
    predicate TEXT NOT NULL,
    value_json TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    recorded_event TEXT NOT NULL REFERENCES projected_events(event_id),
    confidence TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    last_event_id TEXT NOT NULL REFERENCES projected_events(event_id),
    authority TEXT NOT NULL CHECK (authority = 'derived')
);
CREATE TABLE relations (
    relation_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    recorded_event TEXT NOT NULL REFERENCES projected_events(event_id),
    confidence TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    last_event_id TEXT NOT NULL REFERENCES projected_events(event_id),
    authority TEXT NOT NULL CHECK (authority = 'derived')
);
CREATE TABLE facets (
    object_id TEXT NOT NULL REFERENCES objects(object_id),
    facet_type TEXT NOT NULL,
    facet_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    source_refs_json TEXT NOT NULL,
    recorded_event TEXT NOT NULL REFERENCES projected_events(event_id),
    last_event_id TEXT NOT NULL REFERENCES projected_events(event_id),
    authority TEXT NOT NULL CHECK (authority = 'derived'),
    PRIMARY KEY (object_id, facet_type)
);
CREATE INDEX idx_projected_events_type ON projected_events(event_type);
CREATE INDEX idx_objects_type ON objects(type);
CREATE INDEX idx_facts_subject ON facts(subject_id);
CREATE INDEX idx_relations_subject ON relations(subject_id);
CREATE INDEX idx_relations_object ON relations(object_id);
CREATE INDEX idx_facets_type ON facets(facet_type);
"""


def _json_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _strict_payload(payload: Any, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProjectionApplyError("event payload must be a JSON object")
    optional = optional or set()
    keys = set(payload)
    missing = required - keys
    extra = keys - required - optional
    if missing:
        raise ProjectionApplyError(f"event payload is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ProjectionApplyError(f"event payload has unknown fields: {', '.join(sorted(extra))}")
    return payload


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectionApplyError(f"{label} must be a non-empty string")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ProjectionApplyError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ProjectionApplyError(f"{label} must not contain duplicates")
    return value


class ProjectionStore:
    def __init__(self, book_root: Path | str, *, branch_id: str = "main") -> None:
        self.book_root = Path(book_root)
        self.branch_id = branch_id
        self.state_directory = self.book_root / "state"
        self.database_path = self.state_directory / "state.db"

    def _connect(self, path: Path | None = None) -> sqlite3.Connection:
        connection = sqlite3.connect(path or self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA journal_mode = DELETE")
        return connection

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO projection_meta VALUES (1, ?, ?, 'derived', NULL, 0)",
            (PROJECTION_SCHEMA_VERSION, self.branch_id),
        )
        connection.commit()

    def _metadata(self, connection: sqlite3.Connection) -> sqlite3.Row:
        if connection.execute("PRAGMA user_version").fetchone()[0] != SQLITE_USER_VERSION:
            raise ProjectionStaleError("unsupported SQLite projection user_version")
        row = connection.execute("SELECT * FROM projection_meta WHERE singleton = 1").fetchone()
        if row is None:
            raise ProjectionStaleError("projection metadata is missing")
        if row["schema_version"] != PROJECTION_SCHEMA_VERSION:
            raise ProjectionStaleError(f"unsupported projection schema: {row['schema_version']}")
        if row["branch_id"] != self.branch_id:
            raise ProjectionStaleError(
                f"projection branch mismatch: database={row['branch_id']} requested={self.branch_id}"
            )
        if row["authority"] != "derived":
            raise ProjectionStaleError("projection authority marker is invalid")
        return row

    def _exists(self, connection: sqlite3.Connection, table: str, field: str, identifier: str) -> bool:
        if table not in {"objects", "facts", "relations", "evidence"}:
            raise AssertionError("unsafe internal table")
        return connection.execute(f"SELECT 1 FROM {table} WHERE {field} = ?", (identifier,)).fetchone() is not None

    def _insert_evidence(self, connection: sqlite3.Connection, records: Any, event_id: str) -> list[str]:
        if not isinstance(records, list):
            raise ProjectionApplyError("payload.evidence must be a list")
        inserted: list[str] = []
        for raw in records:
            try:
                record = validate_evidence(raw)
            except ModelValidationError as exc:
                raise ProjectionApplyError(f"invalid evidence: {exc}") from exc
            if record["recorded_event"] != event_id:
                raise ProjectionApplyError("evidence.recorded_event must equal the carrying event_id")
            try:
                connection.execute(
                    "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, 'derived')",
                    (
                        record["evidence_id"], record["source_type"], record["source_ref"],
                        _json_text(record["locator"]), record["content_hash"], record["excerpt"],
                        record["recorded_event"],
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ProjectionApplyError(f"cannot insert evidence {record['evidence_id']}: {exc}") from exc
            inserted.append(record["evidence_id"])
        return inserted

    def _check_evidence_refs(self, connection: sqlite3.Connection, refs: Sequence[str]) -> None:
        for reference in refs:
            if EVIDENCE_ID_RE.fullmatch(reference) and not self._exists(
                connection, "evidence", "evidence_id", reference
            ):
                raise ProjectionApplyError(f"unknown evidence reference: {reference}")

    def _check_facet_refs(self, connection: sqlite3.Connection, record: dict[str, Any]) -> None:
        payload = record["payload"]
        if record["facet_type"] == "knowledge":
            for fact_id in payload["fact_ids"] + payload.get("uncertain_fact_ids", []):
                if not self._exists(connection, "facts", "fact_id", fact_id):
                    raise ProjectionApplyError(f"knowledge facet references unknown fact: {fact_id}")
        elif record["facet_type"] == "location":
            if not self._exists(connection, "objects", "object_id", payload["place_id"]):
                raise ProjectionApplyError(f"location facet references unknown place: {payload['place_id']}")
        elif record["facet_type"] == "relationship":
            for relation_id in payload["relation_ids"]:
                if not self._exists(connection, "relations", "relation_id", relation_id):
                    raise ProjectionApplyError(f"relationship facet references unknown relation: {relation_id}")

    def _apply_business_event(self, connection: sqlite3.Connection, event: dict[str, Any]) -> None:
        event_type = event["event_type"]
        event_id = event["event_id"]
        payload = event["payload"]

        if event_type == "object.created":
            payload = _strict_payload(payload, {"object", "evidence"})
            self._insert_evidence(connection, payload["evidence"], event_id)
            try:
                record = validate_object(payload["object"])
            except ModelValidationError as exc:
                raise ProjectionApplyError(f"invalid object: {exc}") from exc
            if record["created_event"] != event_id:
                raise ProjectionApplyError("object.created_event must equal the carrying event_id")
            if record["supersedes"] is not None and not self._exists(
                connection, "objects", "object_id", record["supersedes"]
            ):
                raise ProjectionApplyError(f"object supersedes unknown object: {record['supersedes']}")
            try:
                connection.execute(
                    "INSERT INTO objects VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'derived')",
                    (
                        record["object_id"], record["type"], record["canonical_name"],
                        _json_text(record["aliases"]), record["status"], record["created_event"],
                        record["supersedes"], event_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ProjectionApplyError(f"cannot create object {record['object_id']}: {exc}") from exc

        elif event_type == "object.renamed":
            payload = _strict_payload(payload, {"object_id", "canonical_name", "aliases"})
            object_id = _nonempty_string(payload["object_id"], "object_id")
            if OBJECT_ID_RE.fullmatch(object_id) is None:
                raise ProjectionApplyError("object_id has invalid format")
            name = _nonempty_string(payload["canonical_name"], "canonical_name")
            aliases = _string_list(payload["aliases"], "aliases")
            if name in aliases:
                raise ProjectionApplyError("aliases must not repeat canonical_name")
            cursor = connection.execute(
                "UPDATE objects SET canonical_name=?, aliases_json=?, last_event_id=? WHERE object_id=?",
                (name, _json_text(aliases), event_id, object_id),
            )
            if cursor.rowcount != 1:
                raise ProjectionApplyError(f"cannot rename unknown object: {object_id}")

        elif event_type == "object.retired":
            payload = _strict_payload(payload, {"object_id"})
            object_id = _nonempty_string(payload["object_id"], "object_id")
            cursor = connection.execute(
                "UPDATE objects SET status='retired', last_event_id=? WHERE object_id=?",
                (event_id, object_id),
            )
            if cursor.rowcount != 1:
                raise ProjectionApplyError(f"cannot retire unknown object: {object_id}")

        elif event_type == "facet.asserted":
            payload = _strict_payload(payload, {"facet", "evidence"})
            self._insert_evidence(connection, payload["evidence"], event_id)
            try:
                record = validate_facet(payload["facet"])
            except ModelValidationError as exc:
                raise ProjectionApplyError(f"invalid facet: {exc}") from exc
            if record["recorded_event"] != event_id:
                raise ProjectionApplyError("facet.recorded_event must equal the carrying event_id")
            if not self._exists(connection, "objects", "object_id", record["object_id"]):
                raise ProjectionApplyError(f"facet references unknown object: {record['object_id']}")
            self._check_facet_refs(connection, record)
            connection.execute(
                """INSERT INTO facets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'derived')
                   ON CONFLICT(object_id, facet_type) DO UPDATE SET
                     facet_version=excluded.facet_version, payload_json=excluded.payload_json,
                     valid_from=excluded.valid_from, valid_to=excluded.valid_to,
                     source_refs_json=excluded.source_refs_json, recorded_event=excluded.recorded_event,
                     last_event_id=excluded.last_event_id, authority='derived'""",
                (
                    record["object_id"], record["facet_type"], record["facet_version"],
                    _json_text(record["payload"]), record["valid_from"], record["valid_to"],
                    _json_text(record["source_refs"]), record["recorded_event"], event_id,
                ),
            )

        elif event_type == "facet.superseded":
            payload = _strict_payload(payload, {"object_id", "facet_type"})
            facet_type = _nonempty_string(payload["facet_type"], "facet_type")
            if facet_type not in FACET_TYPES:
                raise ProjectionApplyError(f"unsupported facet_type: {facet_type}")
            cursor = connection.execute(
                "DELETE FROM facets WHERE object_id=? AND facet_type=?",
                (payload["object_id"], facet_type),
            )
            if cursor.rowcount != 1:
                raise ProjectionApplyError("cannot supersede an unknown current facet")

        elif event_type == "fact.asserted":
            payload = _strict_payload(payload, {"fact", "evidence"})
            self._insert_evidence(connection, payload["evidence"], event_id)
            try:
                record = validate_fact(payload["fact"])
            except ModelValidationError as exc:
                raise ProjectionApplyError(f"invalid fact: {exc}") from exc
            if record["recorded_event"] != event_id:
                raise ProjectionApplyError("fact.recorded_event must equal the carrying event_id")
            if not self._exists(connection, "objects", "object_id", record["subject_id"]):
                raise ProjectionApplyError(f"fact references unknown subject: {record['subject_id']}")
            self._check_evidence_refs(connection, record["evidence_refs"])
            try:
                connection.execute(
                    "INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'derived')",
                    (
                        record["fact_id"], record["subject_id"], record["predicate"],
                        _json_text(record["value"]), record["valid_from"], record["valid_to"],
                        record["recorded_event"], record["confidence"], record["status"],
                        _json_text(record["evidence_refs"]), event_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ProjectionApplyError(f"cannot assert fact {record['fact_id']}: {exc}") from exc

        elif event_type == "fact.disputed":
            payload = _strict_payload(payload, {"fact_id", "evidence"})
            evidence_ids = self._insert_evidence(connection, payload["evidence"], event_id)
            fact_id = _nonempty_string(payload["fact_id"], "fact_id")
            if FACT_ID_RE.fullmatch(fact_id) is None:
                raise ProjectionApplyError("fact_id has invalid format")
            row = connection.execute(
                "SELECT evidence_refs_json FROM facts WHERE fact_id=?", (fact_id,)
            ).fetchone()
            if row is None:
                raise ProjectionApplyError(f"cannot dispute unknown fact: {fact_id}")
            refs = json.loads(row[0])
            refs.extend(identifier for identifier in evidence_ids if identifier not in refs)
            connection.execute(
                "UPDATE facts SET status='disputed', evidence_refs_json=?, last_event_id=? WHERE fact_id=?",
                (_json_text(refs), event_id, fact_id),
            )

        elif event_type == "relation.asserted":
            payload = _strict_payload(payload, {"relation", "evidence"})
            self._insert_evidence(connection, payload["evidence"], event_id)
            try:
                record = validate_relation(payload["relation"])
            except ModelValidationError as exc:
                raise ProjectionApplyError(f"invalid relation: {exc}") from exc
            if record["recorded_event"] != event_id:
                raise ProjectionApplyError("relation.recorded_event must equal the carrying event_id")
            for label in ("subject_id", "object_id"):
                identifier = record[label]
                exists = self._exists(connection, "objects", "object_id", identifier) or self._exists(
                    connection, "facts", "fact_id", identifier
                )
                if not exists:
                    raise ProjectionApplyError(f"relation references unknown {label}: {identifier}")
            self._check_evidence_refs(connection, record["evidence_refs"])
            try:
                connection.execute(
                    "INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'derived')",
                    (
                        record["relation_id"], record["subject_id"], record["predicate"],
                        record["object_id"], record["valid_from"], record["valid_to"],
                        record["recorded_event"], record["confidence"],
                        _json_text(record["evidence_refs"]), event_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ProjectionApplyError(f"cannot assert relation {record['relation_id']}: {exc}") from exc

        elif event_type == "relation.invalidated":
            payload = _strict_payload(payload, {"relation_id", "valid_to"})
            relation_id = _nonempty_string(payload["relation_id"], "relation_id")
            if RELATION_ID_RE.fullmatch(relation_id) is None:
                raise ProjectionApplyError("relation_id has invalid format")
            valid_to = _nonempty_string(payload["valid_to"], "valid_to")
            if valid_to != "unknown" and STORY_TIME_RE.fullmatch(valid_to) is None:
                raise ProjectionApplyError("valid_to must be 'unknown' or story:<ordered-key>")
            cursor = connection.execute(
                "UPDATE relations SET valid_to=?, last_event_id=? WHERE relation_id=?",
                (valid_to, event_id, relation_id),
            )
            if cursor.rowcount != 1:
                raise ProjectionApplyError(f"cannot invalidate unknown relation: {relation_id}")

    def _apply_event(self, connection: sqlite3.Connection, event: dict[str, Any], line_index: int) -> None:
        try:
            connection.execute(
                "INSERT INTO projected_events VALUES (?, ?, ?, ?, ?, ?, ?, 'derived')",
                (
                    line_index, event["event_id"], event["event_type"], event["branch_id"],
                    event["parent_event_id"], event["payload_hash"], _json_text(event),
                ),
            )
            if event["event_type"] in PROJECTABLE_EVENTS:
                self._apply_business_event(connection, event)
            connection.execute(
                "UPDATE projection_meta SET last_applied_event_id=?, applied_event_count=? WHERE singleton=1",
                (event["event_id"], line_index),
            )
        except ProjectionApplyError:
            raise
        except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
            raise ProjectionApplyError(
                f"cannot apply event {event.get('event_id', '<unknown>')}: {exc}"
            ) from exc

    def _lineage(self, event_log: EventLog | None = None) -> tuple[dict[str, Any], ...]:
        log = event_log or EventLog(self.book_root)
        log.verify()
        return log.read_lineage(self.branch_id)

    def rebuild(self, event_log: EventLog | None = None) -> ProjectionReport:
        lineage = self._lineage(event_log)
        self.state_directory.mkdir(parents=True, exist_ok=True)
        temporary = self.state_directory / f".state-{uuid.uuid4().hex}.tmp.db"
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect(temporary)
            self._create_schema(connection)
            with connection:
                for index, event in enumerate(lineage, start=1):
                    self._apply_event(connection, event, index)
                self._assert_database_health(connection)
            connection.close()
            connection = None
            os.chmod(temporary, 0o600)
            descriptor = os.open(temporary, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, self.database_path)
            self._fsync_state_directory()
        except ProjectionError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ProjectionError(f"projection rebuild failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()
            temporary.unlink(missing_ok=True)
        return self.verify(event_log)

    def update(self, event_log: EventLog | None = None) -> ProjectionReport:
        if not self.database_path.is_file():
            return self.rebuild(event_log)
        lineage = self._lineage(event_log)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            metadata = self._metadata(connection)
            projected_ids = [row[0] for row in connection.execute(
                "SELECT event_id FROM projected_events ORDER BY line_index"
            )]
            lineage_ids = [event["event_id"] for event in lineage]
            if projected_ids != lineage_ids[: len(projected_ids)]:
                raise ProjectionStaleError("projected event sequence is not a prefix of branch lineage")
            if metadata["applied_event_count"] != len(projected_ids):
                raise ProjectionStaleError("metadata applied_event_count does not match projected_events")
            expected_last = projected_ids[-1] if projected_ids else None
            if metadata["last_applied_event_id"] != expected_last:
                raise ProjectionStaleError("metadata last_applied_event_id is stale")
            for index, event in enumerate(lineage[len(projected_ids) :], start=len(projected_ids) + 1):
                self._apply_event(connection, event, index)
            self._assert_database_health(connection)
            connection.commit()
        except ProjectionError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise ProjectionError(f"projection update failed: {exc}") from exc
        finally:
            connection.close()
        return self.verify(event_log)

    def _assert_database_health(self, connection: sqlite3.Connection) -> None:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ProjectionError(f"SQLite integrity_check failed: {integrity}")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise ProjectionError(f"SQLite foreign_key_check failed: {len(foreign_keys)} violation(s)")
        for table in ("projected_events", "objects", "facets", "relations", "facts", "evidence"):
            invalid = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE authority != 'derived'"
            ).fetchone()[0]
            if invalid:
                raise ProjectionError(f"invalid authority marker in {table}: {invalid} row(s)")

    def _fsync_state_directory(self) -> None:
        if os.name != "posix":
            return
        descriptor = os.open(self.state_directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def verify(self, event_log: EventLog | None = None) -> ProjectionReport:
        if not self.database_path.is_file():
            raise ProjectionStaleError(f"projection database does not exist: {self.database_path}")
        lineage = self._lineage(event_log)
        connection = self._connect()
        try:
            metadata = self._metadata(connection)
            self._assert_database_health(connection)
            projected_ids = [row[0] for row in connection.execute(
                "SELECT event_id FROM projected_events ORDER BY line_index"
            )]
            lineage_ids = [event["event_id"] for event in lineage]
            if projected_ids != lineage_ids:
                raise ProjectionStaleError("projection does not match complete selected branch lineage")
            if metadata["applied_event_count"] != len(projected_ids):
                raise ProjectionStaleError("metadata event count is stale")
            expected_last = projected_ids[-1] if projected_ids else None
            if metadata["last_applied_event_id"] != expected_last:
                raise ProjectionStaleError("metadata event head is stale")
            state_hash = sha256_json(self._export_state(connection))
            return ProjectionReport(
                ok=True,
                branch_id=self.branch_id,
                applied_event_count=len(projected_ids),
                last_applied_event_id=expected_last,
                state_hash=state_hash,
            )
        finally:
            connection.close()

    def _export_state(self, connection: sqlite3.Connection) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for table, order_by in (
            ("objects", "object_id"), ("facets", "object_id, facet_type"),
            ("relations", "relation_id"), ("facts", "fact_id"), ("evidence", "evidence_id"),
        ):
            rows = []
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}"):
                value = dict(row)
                for field in list(value):
                    if field.endswith("_json"):
                        value[field[:-5]] = json.loads(value.pop(field))
                rows.append(value)
            result[table] = rows
        return result

    def export_state(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            self._metadata(connection)
            return self._export_state(connection)
        finally:
            connection.close()

    def get_object(self, object_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            self._metadata(connection)
            row = connection.execute("SELECT * FROM objects WHERE object_id=?", (object_id,)).fetchone()
            if row is None:
                return None
            value = dict(row)
            value["aliases"] = json.loads(value.pop("aliases_json"))
            return value
        finally:
            connection.close()
