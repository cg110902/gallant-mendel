from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from novel_kernel.outline_semantics import OutlineSemanticError, OutlineSemanticValidator

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "workspace" / "_fixture" / "outline" / "valid-semantic" / "outline"
STUDIO = ROOT / "studio.py"


class OutlineSemanticTests(unittest.TestCase):
    def copy(self, parent: Path) -> Path:
        target = parent / "outline"
        shutil.copytree(FIXTURE, target)
        return target

    @staticmethod
    def mutate(root: Path, stem: str, function) -> None:
        path = root / f"{stem}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        function(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def codes(self, root: Path) -> list[str]:
        with self.assertRaises(OutlineSemanticError) as caught:
            OutlineSemanticValidator().validate(root)
        diagnostics = caught.exception.diagnostics
        self.assertEqual(diagnostics, tuple(sorted(diagnostics)))
        return [item.code for item in diagnostics]

    def test_valid_semantic_package_has_deterministic_summary(self) -> None:
        first = OutlineSemanticValidator().validate(FIXTURE, expected_book_id="book_demo")
        second = OutlineSemanticValidator().validate(FIXTURE, expected_book_id="book_demo")
        self.assertEqual(first.semantic, second.semantic)
        self.assertEqual(first.semantic["declaration_count"], 12)
        self.assertEqual(first.semantic["reference_count"], 22)
        self.assertEqual(first.semantic["time_window_count"], 3)
        self.assertEqual(first.semantic["timeline_edge_count"], 1)
        self.assertEqual(first.semantic["kind_counts"]["character"], 2)

    def test_duplicate_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            self.mutate(root, "04-cast", lambda value: value.append(dict(value[0])))
            self.assertIn("DUPLICATE_ID", self.codes(root))

    def test_missing_and_wrong_prefix_id_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def break_ids(value):
                del value[0]["id"]
                value[1]["id"] = "place_wrong"
            self.mutate(root, "04-cast", break_ids)
            codes = self.codes(root)
            self.assertIn("MISSING_ID", codes)
            self.assertIn("INVALID_ID", codes)

    def test_unknown_and_invalid_references_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def break_refs(value):
                value[0]["initial_state"]["location"] = "place_absent"
                value[0]["arc_refs"] = ["thread_wrong_kind"]
            self.mutate(root, "04-cast", break_refs)
            codes = self.codes(root)
            self.assertIn("UNKNOWN_REFERENCE", codes)
            self.assertIn("INVALID_REFERENCE", codes)

    def test_alias_collision_is_scoped_to_object_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            self.mutate(root, "04-cast", lambda value: value[1].update({"aliases": ["凌云"]}))
            self.assertIn("ALIAS_COLLISION", self.codes(root))
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            self.mutate(root, "05-factions", lambda value: value[0].update({"name": "凌云"}))
            OutlineSemanticValidator().validate(root)

    def test_time_window_and_format_are_checked_without_chapter_monotonicity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            def break_time(value):
                value[0]["time"] = {"start": "story:0020", "end": "story:0019"}
                value[1]["time"] = "tomorrow"
            self.mutate(root, "08-timeline", break_time)
            codes = self.codes(root)
            self.assertEqual(codes.count("TIME_CONTRADICTION"), 2)

    def test_timeline_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            self.mutate(root, "08-timeline", lambda value: value[1].update({"before": ["event_first_attack"]}))
            self.assertIn("CIRCULAR_DEPENDENCY", self.codes(root))

    def test_unrecognized_nonempty_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            (root / "09-threads.json").write_text('{"records": []}\n', encoding="utf-8")
            self.assertIn("SEMANTIC_ROOT_ERROR", self.codes(root))

    def test_diagnostics_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            self.mutate(root, "04-cast", lambda value: value[0].update({"arc_refs": ["arc_missing"]}))
            results = []
            for _ in range(2):
                with self.assertRaises(OutlineSemanticError) as caught:
                    OutlineSemanticValidator().validate(root)
                results.append([item.as_dict() for item in caught.exception.diagnostics])
            self.assertEqual(results[0], results[1])

    def test_validation_remains_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy(Path(temp))
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            OutlineSemanticValidator().validate(root)
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((root.parent / "compiled").exists())


class OutlineSemanticCliTests(unittest.TestCase):
    def run_cli(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(STUDIO), "outline", "validate", "--path", str(path), "--json"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )

    def test_cli_success_contains_semantic_summary(self) -> None:
        result = self.run_cli(FIXTURE)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["semantic"]["schema_version"], "outline.semantic.v1")
        self.assertEqual(value["semantic"]["declaration_count"], 12)

    def test_cli_failure_contains_ordered_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "outline"
            shutil.copytree(FIXTURE, root)
            path = root / "04-cast.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value[0]["arc_refs"] = ["arc_absent"]
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            result = self.run_cli(root)
            self.assertEqual(result.returncode, 2)
            output = json.loads(result.stdout)
            self.assertFalse(output["ok"])
            self.assertEqual(output["diagnostics"][0]["code"], "UNKNOWN_REFERENCE")


if __name__ == "__main__":
    unittest.main()
