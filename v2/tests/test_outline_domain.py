from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from novel_kernel.outline_domain import OutlineDomainError, OutlineDomainValidator

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "workspace" / "_fixture" / "outline" / "valid-semantic" / "outline"
STUDIO = ROOT / "studio.py"


class OutlineDomainTests(unittest.TestCase):
    def test_domain_schema_artifact_defines_nine_record_types(self) -> None:
        value = json.loads((ROOT / "schemas" / "outline-domain.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
        expected = {"character", "faction", "place", "item", "thread", "obligation", "arc", "chapter", "beat"}
        self.assertTrue(expected.issubset(value["$defs"]))
        self.assertEqual(len(value["oneOf"]), 9)

    def copy(self, parent: Path) -> Path:
        root = parent / "outline"
        shutil.copytree(FIXTURE, root)
        return root

    @staticmethod
    def mutate(root: Path, stem: str, function) -> None:
        path = root / f"{stem}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        function(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def diagnostics(self, root: Path):
        with self.assertRaises(OutlineDomainError) as caught:
            OutlineDomainValidator().validate(root)
        self.assertEqual(caught.exception.diagnostics, tuple(sorted(caught.exception.diagnostics)))
        return caught.exception.diagnostics

    def test_complete_domain_fixture_has_deterministic_counts(self) -> None:
        first = OutlineDomainValidator().validate(FIXTURE, expected_book_id="book_demo")
        second = OutlineDomainValidator().validate(FIXTURE, expected_book_id="book_demo")
        self.assertEqual(first.domain, second.domain)
        counts = first.domain["record_counts"]
        self.assertEqual(counts["characters"], 2)
        self.assertEqual(counts["turning_points"], 1)
        self.assertEqual(counts["beats"], 1)
        self.assertEqual(first.semantic["declaration_count"], 12)

    def test_unbounded_character_has_specific_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def mutate(value):
                value[0].pop("capabilities")
                value[0].pop("resources", None)
            self.mutate(root, "04-cast", mutate)
            self.assertIn("UNBOUNDED_CHARACTER", [item.code for item in self.diagnostics(root)])

    def test_character_requires_motive_constraint_state_role_and_arc(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def mutate(value):
                for field in ("role", "initial_state", "motives", "constraints", "arc_refs"):
                    value[0].pop(field)
            self.mutate(root, "04-cast", mutate)
            messages = self.diagnostics(root)
            self.assertGreaterEqual(sum(item.code == "DOMAIN_SCHEMA_ERROR" for item in messages), 5)

    def test_faction_place_and_item_required_boundaries(self) -> None:
        cases = [
            ("05-factions", lambda value: value[0].pop("resources"), ".resources"),
            ("06-places", lambda value: value[0].pop("allowed_actions"), ".allowed_actions"),
            ("07-items", lambda value: value[0].update({"foreshadowing_carrier": "yes"}), ".foreshadowing_carrier"),
        ]
        for stem, mutate, path_suffix in cases:
            with self.subTest(stem=stem), tempfile.TemporaryDirectory() as temp:
                root = self.copy(Path(temp))
                self.mutate(root, stem, mutate)
                self.assertTrue(any(item.path.endswith(path_suffix) for item in self.diagnostics(root)))

    def test_thread_turning_point_is_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def mutate(value):
                value[0]["turning_points"][0].pop("irreversible_change")
                value[0]["turning_points"][0]["target_chapter"] = 0
            self.mutate(root, "09-threads", mutate)
            diagnostics = self.diagnostics(root)
            self.assertEqual(len(diagnostics), 2)

    def test_obligation_resolution_window_weight_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def mutate(value):
                value[0]["allowed_resolution"] = []
                value[0]["expected_window"] = [140, 80]
                value[0]["weight"] = True
                value[0]["evidence_requirement"]["min_clues"] = 0
            self.mutate(root, "10-obligations", mutate)
            diagnostics = self.diagnostics(root)
            codes = [item.code for item in diagnostics]
            self.assertIn("OBLIGATION_WITHOUT_RESOLUTION", codes)
            self.assertGreaterEqual(codes.count("DOMAIN_SCHEMA_ERROR"), 3)

    def test_arc_requires_states_turns_range_and_obligation_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def mutate(value):
                value[0]["range"] = [50, 1]
                value[0]["required_turns"] = []
                value[0].pop("exit_state")
            self.mutate(root, "11-arcs", mutate)
            self.assertEqual(len(self.diagnostics(root)), 3)

    def test_chapter_missing_purpose_and_hook_have_specific_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def mutate(value):
                value[0]["purpose"] = " "
                value[0]["intent"].pop("required_hook")
            self.mutate(root, "12-chapter-map", mutate)
            codes = [item.code for item in self.diagnostics(root)]
            self.assertIn("CHAPTER_WITHOUT_PURPOSE", codes)
            self.assertIn("CHAPTER_WITHOUT_HOOK", codes)

    def test_beat_requires_valid_word_window_kind_and_complexity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def mutate(value):
                beat = value[0]["beats"][0]
                beat["target_words"] = [900, 500]
                beat.pop("kind")
                beat["complexity"] = ""
            self.mutate(root, "12-chapter-map", mutate)
            self.assertEqual(len(self.diagnostics(root)), 3)

    def test_unknown_explanatory_fields_are_forward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            self.mutate(root, "04-cast", lambda value: value[0].update({"author_note": "candidate detail"}))
            OutlineDomainValidator().validate(root)

    def test_domain_validation_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            OutlineDomainValidator().validate(root)
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((root.parent / "compiled").exists())


class OutlineDomainCliTests(unittest.TestCase):
    def test_cli_success_includes_domain_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, str(STUDIO), "outline", "validate", "--book", "book_demo", "--json"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["domain"]["schema_version"], "outline.domain.v1")
        self.assertEqual(value["domain"]["record_counts"]["chapters"], 1)

    def test_cli_domain_failure_returns_two_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outline"
            shutil.copytree(FIXTURE, root)
            path = root / "12-chapter-map.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            del value[0]["intent"]["required_hook"]
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(STUDIO), "outline", "validate", "--path", str(root), "--json"],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            output = json.loads(result.stdout)
            self.assertEqual(output["diagnostics"][0]["code"], "CHAPTER_WITHOUT_HOOK")


if __name__ == "__main__":
    unittest.main()
