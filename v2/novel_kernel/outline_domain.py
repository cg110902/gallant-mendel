"""M2.3 deterministic domain-completeness validation for Outline v1."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .outline import OutlineFormatError, OutlineValidationReport, StructuredLoaderRegistry
from .outline_semantics import DECLARATIONS, OutlineSemanticValidator, SemanticDiagnostic


class OutlineDomainError(OutlineFormatError):
    def __init__(self, diagnostics: Iterable[SemanticDiagnostic]) -> None:
        self.diagnostics = tuple(sorted(diagnostics))
        first = self.diagnostics[0] if self.diagnostics else None
        message = "outline domain validation failed"
        if first is not None:
            message += f" ({len(self.diagnostics)} diagnostics): {first.code} at {first.path}: {first.message}"
        super().__init__(message)


class OutlineDomainValidator:
    def __init__(
        self,
        semantic_validator: OutlineSemanticValidator | None = None,
        loaders: StructuredLoaderRegistry | None = None,
    ) -> None:
        self.semantic_validator = semantic_validator or OutlineSemanticValidator()
        self.loaders = loaders or StructuredLoaderRegistry()

    def validate(
        self,
        package_path: Path | str,
        *,
        expected_book_id: str | None = None,
    ) -> OutlineValidationReport:
        report = self.semantic_validator.validate(package_path, expected_book_id=expected_book_id)
        root = Path(report.package_path)
        files = {item.role: root / item.path for item in report.files if item.role in DECLARATIONS}
        documents = {role: self.loaders.load(path) for role, path in files.items()}
        records = {
            role: self._records(documents[role], DECLARATIONS[role][1])
            for role in DECLARATIONS
        }
        diagnostics: list[SemanticDiagnostic] = []
        counters = {
            "characters": len(records["04-cast"]),
            "factions": len(records["05-factions"]),
            "places": len(records["06-places"]),
            "items": len(records["07-items"]),
            "timeline_events": len(records["08-timeline"]),
            "threads": len(records["09-threads"]),
            "obligations": len(records["10-obligations"]),
            "arcs": len(records["11-arcs"]),
            "chapters": len(records["12-chapter-map"]),
            "turning_points": 0,
            "beats": 0,
        }

        for index, record in enumerate(records["04-cast"]):
            self._character(record, f"{files['04-cast'].name}#{index}", diagnostics)
        for index, record in enumerate(records["05-factions"]):
            self._faction(record, f"{files['05-factions'].name}#{index}", diagnostics)
        for index, record in enumerate(records["06-places"]):
            self._place(record, f"{files['06-places'].name}#{index}", diagnostics)
        for index, record in enumerate(records["07-items"]):
            self._item(record, f"{files['07-items'].name}#{index}", diagnostics)
        for index, record in enumerate(records["09-threads"]):
            counters["turning_points"] += self._thread(
                record, f"{files['09-threads'].name}#{index}", diagnostics
            )
        for index, record in enumerate(records["10-obligations"]):
            self._obligation(record, f"{files['10-obligations'].name}#{index}", diagnostics)
        for index, record in enumerate(records["11-arcs"]):
            self._arc(record, f"{files['11-arcs'].name}#{index}", diagnostics)
        for index, record in enumerate(records["12-chapter-map"]):
            counters["beats"] += self._chapter(
                record, f"{files['12-chapter-map'].name}#{index}", diagnostics
            )

        if diagnostics:
            raise OutlineDomainError(diagnostics)
        domain = {
            "ok": True,
            "schema_version": "outline.domain.v1",
            "record_counts": dict(sorted(counters.items())),
            "diagnostics": [],
        }
        return replace(report, domain=domain)

    @staticmethod
    def _records(document: Any, wrappers: tuple[str, ...]) -> list[dict[str, Any]]:
        if isinstance(document, list):
            return document
        if not document:
            return []
        if "id" in document:
            return [document]
        for wrapper in wrappers:
            if wrapper in document:
                return document[wrapper]
        return []  # M2.2 has already rejected every other shape.

    @staticmethod
    def _error(
        diagnostics: list[SemanticDiagnostic], path: str, message: str, code: str = "DOMAIN_SCHEMA_ERROR"
    ) -> None:
        diagnostics.append(SemanticDiagnostic(code, path, message))

    def _text(
        self, record: dict[str, Any], field: str, path: str,
        diagnostics: list[SemanticDiagnostic], *, code: str = "DOMAIN_SCHEMA_ERROR",
    ) -> bool:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            self._error(diagnostics, f"{path}.{field}", "must be a non-empty string", code)
            return False
        return True

    def _positive(
        self, value: Any, path: str, diagnostics: list[SemanticDiagnostic], *, allow_zero: bool = False
    ) -> bool:
        lower = 0 if allow_zero else 1
        if isinstance(value, bool) or not isinstance(value, int) or value < lower:
            self._error(diagnostics, path, f"must be an integer >= {lower}")
            return False
        return True

    def _nonempty(
        self, value: Any, path: str, diagnostics: list[SemanticDiagnostic],
        *, types: tuple[type, ...] = (list, dict), code: str = "DOMAIN_SCHEMA_ERROR",
    ) -> bool:
        if not isinstance(value, types) or not value or (isinstance(value, str) and not value.strip()):
            self._error(diagnostics, path, "must be non-empty", code)
            return False
        return True

    def _window(self, value: Any, path: str, diagnostics: list[SemanticDiagnostic]) -> bool:
        if not isinstance(value, list) or len(value) != 2:
            self._error(diagnostics, path, "must be a two-integer window")
            return False
        valid = self._positive(value[0], f"{path}[0]", diagnostics)
        valid = self._positive(value[1], f"{path}[1]", diagnostics) and valid
        if valid and value[0] > value[1]:
            self._error(diagnostics, path, "window lower bound exceeds upper bound")
            return False
        return valid

    def _character(self, record: dict[str, Any], path: str, diagnostics: list[SemanticDiagnostic]) -> None:
        self._text(record, "name", path, diagnostics)
        self._text(record, "role", path, diagnostics)
        self._nonempty(record.get("initial_state"), f"{path}.initial_state", diagnostics, types=(dict,))
        self._nonempty(record.get("motives"), f"{path}.motives", diagnostics)
        self._nonempty(record.get("constraints"), f"{path}.constraints", diagnostics, types=(list,))
        self._nonempty(record.get("arc_refs"), f"{path}.arc_refs", diagnostics, types=(list,))
        bounded = any(
            isinstance(record.get(field), (list, dict)) and bool(record[field])
            for field in ("capabilities", "resources")
        )
        if not bounded:
            self._error(
                diagnostics, path, "character requires non-empty capabilities or resources", "UNBOUNDED_CHARACTER"
            )

    def _faction(self, record: dict[str, Any], path: str, diagnostics: list[SemanticDiagnostic]) -> None:
        for field in ("name", "goal", "hierarchy", "internal_conflict", "known_information_boundary"):
            self._text(record, field, path, diagnostics)
        self._nonempty(record.get("resources"), f"{path}.resources", diagnostics)
        if "external_relations" not in record or not isinstance(record["external_relations"], (list, dict)):
            self._error(diagnostics, f"{path}.external_relations", "must be an array or object")

    def _place(self, record: dict[str, Any], path: str, diagnostics: list[SemanticDiagnostic]) -> None:
        for field in ("name", "location", "accessibility"):
            self._text(record, field, path, diagnostics)
        self._nonempty(record.get("environment_constraints"), f"{path}.environment_constraints", diagnostics, types=(list,))
        self._nonempty(record.get("allowed_actions"), f"{path}.allowed_actions", diagnostics, types=(list,))
        if not any(field in record for field in ("faction", "faction_id", "owner_faction")):
            self._error(diagnostics, path, "place requires faction ownership")
        self._positive(record.get("first_appearance_chapter"), f"{path}.first_appearance_chapter", diagnostics)

    def _item(self, record: dict[str, Any], path: str, diagnostics: list[SemanticDiagnostic]) -> None:
        self._text(record, "name", path, diagnostics)
        self._text(record, "source", path, diagnostics)
        if not any(field in record for field in ("current_holder", "holder", "owner")):
            self._error(diagnostics, path, "item requires a current holder")
        if not any(isinstance(record.get(field), (list, dict)) and record[field] for field in ("capabilities", "limitations")):
            self._error(diagnostics, path, "item requires capabilities or limitations")
        self._nonempty(record.get("transfer_rules"), f"{path}.transfer_rules", diagnostics, types=(list, dict, str))
        if not isinstance(record.get("foreshadowing_carrier"), bool):
            self._error(diagnostics, f"{path}.foreshadowing_carrier", "must be boolean")

    def _thread(self, record: dict[str, Any], path: str, diagnostics: list[SemanticDiagnostic]) -> int:
        for field in ("kind", "owner", "start_condition", "progress_metric", "resolution_condition", "forbidden_resolution"):
            self._text(record, field, path, diagnostics)
        turning_points = record.get("turning_points")
        if not self._nonempty(turning_points, f"{path}.turning_points", diagnostics, types=(list,)):
            return 0
        for index, point in enumerate(turning_points):
            point_path = f"{path}.turning_points[{index}]"
            if not isinstance(point, dict):
                self._error(diagnostics, point_path, "must be an object")
                continue
            for field in ("id", "action", "irreversible_change"):
                self._text(point, field, point_path, diagnostics)
            self._positive(point.get("target_chapter"), f"{point_path}.target_chapter", diagnostics)
        return len(turning_points)

    def _obligation(self, record: dict[str, Any], path: str, diagnostics: list[SemanticDiagnostic]) -> None:
        for field in ("kind", "source_thread", "reader_visibility"):
            self._text(record, field, path, diagnostics)
        self._positive(record.get("planted_chapter"), f"{path}.planted_chapter", diagnostics)
        self._window(record.get("expected_window"), f"{path}.expected_window", diagnostics)
        weight = record.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
            self._error(diagnostics, f"{path}.weight", "must be a number between 0 and 1")
        resolutions = record.get("allowed_resolution")
        if not self._nonempty(
            resolutions, f"{path}.allowed_resolution", diagnostics, types=(list,),
            code="OBLIGATION_WITHOUT_RESOLUTION",
        ):
            resolutions = []
        allowed = {"fulfilled", "subverted", "deferred", "retired"}
        if any(not isinstance(item, str) or item not in allowed for item in resolutions):
            self._error(
                diagnostics, f"{path}.allowed_resolution", "contains unsupported resolution",
                "OBLIGATION_WITHOUT_RESOLUTION",
            )
        self._nonempty(record.get("character_visibility"), f"{path}.character_visibility", diagnostics, types=(dict,))
        evidence = record.get("evidence_requirement")
        if not isinstance(evidence, dict):
            self._error(diagnostics, f"{path}.evidence_requirement", "must be an object")
            return
        self._positive(evidence.get("min_clues"), f"{path}.evidence_requirement.min_clues", diagnostics)
        self._nonempty(
            evidence.get("payoff_requires"), f"{path}.evidence_requirement.payoff_requires", diagnostics, types=(list,)
        )

    def _arc(self, record: dict[str, Any], path: str, diagnostics: list[SemanticDiagnostic]) -> None:
        for field in ("volume", "entry_state", "exit_state", "core_question"):
            self._text(record, field, path, diagnostics)
        self._window(record.get("range"), f"{path}.range", diagnostics)
        self._nonempty(record.get("required_turns"), f"{path}.required_turns", diagnostics, types=(list,))
        for field in ("obligations_created", "obligations_resolved"):
            if not isinstance(record.get(field), list):
                self._error(diagnostics, f"{path}.{field}", "must be an array")

    def _chapter(self, record: dict[str, Any], path: str, diagnostics: list[SemanticDiagnostic]) -> int:
        for field in ("volume", "arc", "pov", "location"):
            self._text(record, field, path, diagnostics)
        self._text(record, "purpose", path, diagnostics, code="CHAPTER_WITHOUT_PURPOSE")
        time = record.get("time")
        if not isinstance(time, dict) or "start" not in time or "end" not in time:
            self._error(diagnostics, f"{path}.time", "must contain start and end")
        intent = record.get("intent")
        if not isinstance(intent, dict):
            self._error(diagnostics, f"{path}.intent", "must be an object")
        else:
            self._nonempty(intent.get("required_events"), f"{path}.intent.required_events", diagnostics, types=(list,))
            self._nonempty(intent.get("required_changes"), f"{path}.intent.required_changes", diagnostics, types=(list,))
            hook = intent.get("required_hook")
            if not isinstance(hook, str) or not hook.strip():
                self._error(diagnostics, f"{path}.intent.required_hook", "must be a non-empty string", "CHAPTER_WITHOUT_HOOK")
            if not isinstance(intent.get("forbidden"), list):
                self._error(diagnostics, f"{path}.intent.forbidden", "must be an array")
        beats = record.get("beats")
        if not self._nonempty(beats, f"{path}.beats", diagnostics, types=(list,)):
            return 0
        for index, beat in enumerate(beats):
            beat_path = f"{path}.beats[{index}]"
            if not isinstance(beat, dict):
                self._error(diagnostics, beat_path, "must be an object")
                continue
            for field in ("id", "kind", "complexity"):
                self._text(beat, field, beat_path, diagnostics)
            self._window(beat.get("target_words"), f"{beat_path}.target_words", diagnostics)
        return len(beats)
