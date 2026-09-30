"""Deterministic M2.2 semantic index and reference validation for Outline v1."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from .outline import (
    OutlineFormatError,
    OutlinePackageValidator,
    OutlineValidationReport,
    StructuredLoaderRegistry,
)

DECLARATIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "04-cast": ("char_", ("characters", "cast")),
    "05-factions": ("faction_", ("factions",)),
    "06-places": ("place_", ("places",)),
    "07-items": ("item_", ("items",)),
    "08-timeline": ("event_", ("events", "timeline")),
    "09-threads": ("thread_", ("threads",)),
    "10-obligations": ("ob_", ("obligations",)),
    "11-arcs": ("arc_", ("arcs",)),
    "12-chapter-map": ("ch_", ("chapters", "chapter_map")),
}
KIND_BY_PREFIX = {
    "char_": "character", "faction_": "faction", "place_": "place", "item_": "item",
    "event_": "event", "thread_": "thread", "ob_": "obligation", "arc_": "arc", "ch_": "chapter",
}
STABLE_ID_RE = re.compile(
    r"^(?:char|faction|place|item|event|thread|ob|arc|ch|beat)_[a-z0-9][a-z0-9_-]{0,95}$"
)
STORY_TIME_RE = re.compile(r"^story:[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")


@dataclass(frozen=True, order=True)
class SemanticDiagnostic:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class SemanticDeclaration:
    object_id: str
    kind: str
    path: str


class OutlineSemanticError(OutlineFormatError):
    def __init__(self, diagnostics: Iterable[SemanticDiagnostic]) -> None:
        self.diagnostics = tuple(sorted(diagnostics))
        first = self.diagnostics[0] if self.diagnostics else None
        message = "outline semantic validation failed"
        if first is not None:
            message += f" ({len(self.diagnostics)} diagnostics): {first.code} at {first.path}: {first.message}"
        super().__init__(message)


class OutlineSemanticValidator:
    def __init__(
        self,
        package_validator: OutlinePackageValidator | None = None,
        loaders: StructuredLoaderRegistry | None = None,
    ) -> None:
        self.package_validator = package_validator or OutlinePackageValidator()
        self.loaders = loaders or StructuredLoaderRegistry()

    def validate(
        self,
        package_path: Path | str,
        *,
        expected_book_id: str | None = None,
    ) -> OutlineValidationReport:
        report = self.package_validator.validate(package_path, expected_book_id=expected_book_id)
        root = Path(report.package_path)
        files_by_role = {item.role: root / item.path for item in report.files if item.role in DECLARATIONS}
        documents = {role: self.loaders.load(path) for role, path in files_by_role.items()}
        diagnostics: list[SemanticDiagnostic] = []
        declarations: list[SemanticDeclaration] = []
        records: dict[str, list[tuple[dict[str, Any], str]]] = {}

        for role in DECLARATIONS:
            prefix, wrappers = DECLARATIONS[role]
            role_records = self._records(documents[role], role, wrappers, diagnostics)
            records[role] = []
            for index, record in enumerate(role_records):
                path = f"{files_by_role[role].name}#{index}"
                if not isinstance(record, dict):
                    diagnostics.append(SemanticDiagnostic("SEMANTIC_ROOT_ERROR", path, "record must be an object"))
                    continue
                records[role].append((record, path))
                object_id = record.get("id")
                if object_id is None:
                    diagnostics.append(SemanticDiagnostic("MISSING_ID", path, "record requires id"))
                    continue
                if not isinstance(object_id, str) or STABLE_ID_RE.fullmatch(object_id) is None or not object_id.startswith(prefix):
                    diagnostics.append(SemanticDiagnostic("INVALID_ID", f"{path}.id", f"expected stable {prefix} ID"))
                    continue
                declarations.append(SemanticDeclaration(object_id, KIND_BY_PREFIX[prefix], f"{path}.id"))
                if role == "12-chapter-map":
                    self._collect_beats(record, path, declarations, diagnostics)

        by_id: dict[str, SemanticDeclaration] = {}
        for declaration in declarations:
            previous = by_id.get(declaration.object_id)
            if previous is not None:
                diagnostics.append(SemanticDiagnostic(
                    "DUPLICATE_ID", declaration.path,
                    f"{declaration.object_id} already declared at {previous.path}",
                ))
            else:
                by_id[declaration.object_id] = declaration

        self._check_aliases(records, diagnostics)
        reference_count, edges = self._check_references(records, by_id, diagnostics)
        time_window_count = self._check_times(records, diagnostics)
        self._check_cycles(edges, diagnostics)

        if diagnostics:
            raise OutlineSemanticError(diagnostics)
        kind_counts: dict[str, int] = {}
        for declaration in declarations:
            kind_counts[declaration.kind] = kind_counts.get(declaration.kind, 0) + 1
        semantic = {
            "ok": True,
            "schema_version": "outline.semantic.v1",
            "declaration_count": len(declarations),
            "reference_count": reference_count,
            "time_window_count": time_window_count,
            "timeline_edge_count": sum(len(targets) for targets in edges.values()),
            "kind_counts": dict(sorted(kind_counts.items())),
            "diagnostics": [],
        }
        return replace(report, semantic=semantic)

    @staticmethod
    def _records(
        document: Any,
        role: str,
        wrappers: tuple[str, ...],
        diagnostics: list[SemanticDiagnostic],
    ) -> list[Any]:
        if isinstance(document, list):
            return document
        if isinstance(document, dict):
            if not document:
                return []
            if "id" in document:
                return [document]
            present = [key for key in wrappers if key in document]
            if len(present) == 1 and len(document) == 1 and isinstance(document[present[0]], list):
                return document[present[0]]
        diagnostics.append(SemanticDiagnostic(
            "SEMANTIC_ROOT_ERROR", role,
            f"root must be an array, a single id record, an empty object, or one of: {', '.join(wrappers)}",
        ))
        return []

    @staticmethod
    def _collect_beats(
        chapter: dict[str, Any],
        chapter_path: str,
        declarations: list[SemanticDeclaration],
        diagnostics: list[SemanticDiagnostic],
    ) -> None:
        if "beats" not in chapter:
            return
        beats = chapter["beats"]
        if not isinstance(beats, list):
            diagnostics.append(SemanticDiagnostic("SEMANTIC_ROOT_ERROR", f"{chapter_path}.beats", "beats must be an array"))
            return
        for index, beat in enumerate(beats):
            path = f"{chapter_path}.beats[{index}]"
            if not isinstance(beat, dict):
                diagnostics.append(SemanticDiagnostic("SEMANTIC_ROOT_ERROR", path, "beat must be an object"))
                continue
            beat_id = beat.get("id")
            if beat_id is None:
                diagnostics.append(SemanticDiagnostic("MISSING_ID", path, "beat requires id"))
            elif not isinstance(beat_id, str) or STABLE_ID_RE.fullmatch(beat_id) is None or not beat_id.startswith("beat_"):
                diagnostics.append(SemanticDiagnostic("INVALID_ID", f"{path}.id", "expected stable beat_ ID"))
            else:
                declarations.append(SemanticDeclaration(beat_id, "beat", f"{path}.id"))

    @staticmethod
    def _check_aliases(
        records: dict[str, list[tuple[dict[str, Any], str]]],
        diagnostics: list[SemanticDiagnostic],
    ) -> None:
        for role, role_records in records.items():
            seen: dict[str, tuple[str, str]] = {}
            for record, path in role_records:
                object_id = record.get("id")
                if not isinstance(object_id, str):
                    continue
                names: list[tuple[str, str]] = []
                for field in ("name", "canonical_name"):
                    if field in record and isinstance(record[field], str) and record[field]:
                        names.append((record[field], f"{path}.{field}"))
                aliases = record.get("aliases", [])
                if aliases is not None and not isinstance(aliases, list):
                    diagnostics.append(SemanticDiagnostic("ALIAS_COLLISION", f"{path}.aliases", "aliases must be an array"))
                    aliases = []
                for index, alias in enumerate(aliases):
                    if not isinstance(alias, str) or not alias:
                        diagnostics.append(SemanticDiagnostic("ALIAS_COLLISION", f"{path}.aliases[{index}]", "alias must be a non-empty string"))
                    else:
                        names.append((alias, f"{path}.aliases[{index}]"))
                local: set[str] = set()
                for name, name_path in names:
                    if name in local:
                        diagnostics.append(SemanticDiagnostic("ALIAS_COLLISION", name_path, f"name/alias {name!r} repeats within {object_id}"))
                        continue
                    local.add(name)
                    previous = seen.get(name)
                    if previous is not None and previous[0] != object_id:
                        diagnostics.append(SemanticDiagnostic(
                            "ALIAS_COLLISION", name_path,
                            f"{name!r} identifies both {previous[0]} ({previous[1]}) and {object_id}",
                        ))
                    else:
                        seen[name] = (object_id, name_path)

    def _check_references(
        self,
        records: dict[str, list[tuple[dict[str, Any], str]]],
        by_id: dict[str, SemanticDeclaration],
        diagnostics: list[SemanticDiagnostic],
    ) -> tuple[int, dict[str, set[str]]]:
        references: list[tuple[str, str, str]] = []
        edges: dict[str, set[str]] = {}

        def one(value: Any, path: str, prefix: str) -> None:
            if not isinstance(value, str) or not value.startswith(prefix) or STABLE_ID_RE.fullmatch(value) is None:
                diagnostics.append(SemanticDiagnostic("INVALID_REFERENCE", path, f"expected {prefix} reference"))
            else:
                references.append((value, path, prefix))

        def many(value: Any, path: str, prefix: str) -> None:
            if not isinstance(value, list):
                diagnostics.append(SemanticDiagnostic("INVALID_REFERENCE", path, "reference field must be an array"))
                return
            for index, item in enumerate(value):
                one(item, f"{path}[{index}]", prefix)

        for role, role_records in records.items():
            for record, path in role_records:
                if role == "04-cast":
                    state = record.get("initial_state")
                    if isinstance(state, dict) and "location" in state:
                        one(state["location"], f"{path}.initial_state.location", "place_")
                    if "arc_refs" in record:
                        many(record["arc_refs"], f"{path}.arc_refs", "arc_")
                elif role == "06-places":
                    for field in ("faction", "faction_id", "owner_faction"):
                        if field in record:
                            one(record[field], f"{path}.{field}", "faction_")
                elif role == "07-items":
                    for field in ("current_holder", "holder", "owner"):
                        if field in record:
                            value = record[field]
                            if not isinstance(value, str) or not value.startswith(("char_", "faction_")):
                                diagnostics.append(SemanticDiagnostic("INVALID_REFERENCE", f"{path}.{field}", "expected char_ or faction_ reference"))
                            else:
                                references.append((value, f"{path}.{field}", value.split("_", 1)[0] + "_"))
                elif role == "09-threads":
                    if "owner" in record:
                        one(record["owner"], f"{path}.owner", "char_")
                    if "related_characters" in record:
                        many(record["related_characters"], f"{path}.related_characters", "char_")
                    if "related_obligations" in record:
                        many(record["related_obligations"], f"{path}.related_obligations", "ob_")
                elif role == "10-obligations":
                    if "source_thread" in record:
                        one(record["source_thread"], f"{path}.source_thread", "thread_")
                    visibility = record.get("character_visibility")
                    if visibility is not None:
                        if not isinstance(visibility, dict):
                            diagnostics.append(SemanticDiagnostic("INVALID_REFERENCE", f"{path}.character_visibility", "must be an object keyed by character ID"))
                        else:
                            for character_id in visibility:
                                one(character_id, f"{path}.character_visibility.{character_id}", "char_")
                    evidence = record.get("evidence_requirement")
                    if isinstance(evidence, dict) and "payoff_requires" in evidence:
                        many(evidence["payoff_requires"], f"{path}.evidence_requirement.payoff_requires", "event_")
                elif role == "11-arcs":
                    for field in ("obligations_created", "obligations_resolved"):
                        if field in record:
                            many(record[field], f"{path}.{field}", "ob_")
                elif role == "12-chapter-map":
                    for field, prefix in (("arc", "arc_"), ("pov", "char_"), ("location", "place_")):
                        if field in record:
                            one(record[field], f"{path}.{field}", prefix)
                    intent = record.get("intent")
                    if isinstance(intent, dict) and "required_events" in intent:
                        many(intent["required_events"], f"{path}.intent.required_events", "event_")
                elif role == "08-timeline":
                    event_id = record.get("id")
                    if isinstance(event_id, str):
                        edges.setdefault(event_id, set())
                    for field in ("before", "after"):
                        if field not in record:
                            continue
                        values = record[field] if isinstance(record[field], list) else [record[field]]
                        many(values, f"{path}.{field}", "event_")
                        for target in values:
                            if isinstance(target, str) and isinstance(event_id, str):
                                if field == "before":
                                    edges.setdefault(event_id, set()).add(target)
                                else:
                                    edges.setdefault(target, set()).add(event_id)

        for target, path, prefix in references:
            declaration = by_id.get(target)
            if declaration is None:
                diagnostics.append(SemanticDiagnostic("UNKNOWN_REFERENCE", path, f"target is not declared: {target}"))
            elif not target.startswith(prefix):
                diagnostics.append(SemanticDiagnostic("INVALID_REFERENCE", path, f"target has wrong kind: {target}"))
        return len(references), edges

    @staticmethod
    def _check_times(
        records: dict[str, list[tuple[dict[str, Any], str]]],
        diagnostics: list[SemanticDiagnostic],
    ) -> int:
        count = 0
        for role in ("08-timeline", "12-chapter-map"):
            for record, path in records[role]:
                value = record.get("time")
                if value is None:
                    continue
                count += 1
                if isinstance(value, str):
                    if STORY_TIME_RE.fullmatch(value) is None:
                        diagnostics.append(SemanticDiagnostic("TIME_CONTRADICTION", f"{path}.time", "expected story:<ordered-key>"))
                    continue
                if not isinstance(value, dict):
                    diagnostics.append(SemanticDiagnostic("TIME_CONTRADICTION", f"{path}.time", "time must be a story string or start/end object"))
                    continue
                start, end = value.get("start"), value.get("end")
                for field, point in (("start", start), ("end", end)):
                    if point is not None and (not isinstance(point, str) or STORY_TIME_RE.fullmatch(point) is None):
                        diagnostics.append(SemanticDiagnostic("TIME_CONTRADICTION", f"{path}.time.{field}", "expected story:<ordered-key>"))
                if isinstance(start, str) and isinstance(end, str) and STORY_TIME_RE.fullmatch(start) and STORY_TIME_RE.fullmatch(end) and end < start:
                    diagnostics.append(SemanticDiagnostic("TIME_CONTRADICTION", f"{path}.time", "end sorts before start"))
        return count

    @staticmethod
    def _check_cycles(edges: dict[str, set[str]], diagnostics: list[SemanticDiagnostic]) -> None:
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(node: str) -> None:
            state[node] = 1
            stack.append(node)
            for target in sorted(edges.get(node, ())):
                if state.get(target, 0) == 0:
                    visit(target)
                elif state.get(target) == 1:
                    start = stack.index(target)
                    cycle = stack[start:] + [target]
                    diagnostics.append(SemanticDiagnostic(
                        "CIRCULAR_DEPENDENCY", f"timeline:{node}", " -> ".join(cycle)
                    ))
            stack.pop()
            state[node] = 2

        for node in sorted(edges):
            if state.get(node, 0) == 0:
                visit(node)
