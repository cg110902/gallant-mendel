from __future__ import annotations

import builtins
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from novel_kernel.outline import (
    JsonDocumentLoader,
    OptionalYamlDocumentLoader,
    OutlineDependencyError,
    OutlineFormatError,
    OutlineLayoutError,
    OutlinePackageValidator,
    STRUCTURED_STEMS,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "studio.py"
FIXTURES = ROOT / "workspace" / "_fixture" / "outline"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STUDIO), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class ManifestValidationTests(unittest.TestCase):
    def valid(self) -> dict:
        return {
            "schema_version": "outline.v1",
            "book_id": "book_demo",
            "title": "示例书",
            "language": "zh-CN",
            "planned_chapters": 500,
            "canon_policy": "strict",
        }

    def test_minimal_manifest_is_valid_and_detached(self) -> None:
        source = self.valid()
        result = validate_manifest(source, expected_book_id="book_demo")
        source["title"] = "changed"
        self.assertEqual(result["title"], "示例书")

    def test_missing_unknown_version_and_book_mismatch_are_rejected(self) -> None:
        values = []
        missing = self.valid()
        del missing["canon_policy"]
        values.append((missing, "missing fields"))
        values.append((dict(self.valid(), invented=True), "unknown fields"))
        values.append((dict(self.valid(), schema_version="outline.v2"), "unsupported"))
        for value, message in values:
            with self.subTest(message=message):
                with self.assertRaisesRegex(OutlineFormatError, message):
                    validate_manifest(value)
        with self.assertRaisesRegex(OutlineFormatError, "does not match"):
            validate_manifest(self.valid(), expected_book_id="book_other")

    def test_numeric_range_status_and_approval_rules(self) -> None:
        invalid = [
            dict(self.valid(), planned_chapters=True),
            dict(self.valid(), planned_words=0),
            dict(self.valid(), chapter_word_range=[4500, 2500]),
            dict(self.valid(), status="compiled"),
            dict(self.valid(), status="approved"),
            dict(self.valid(), approval={"owner": "author"}),
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(OutlineFormatError):
                    validate_manifest(value)
        approved = dict(
            self.valid(),
            status="approved",
            approval={"owner": "author", "approved_at": "2026-09-29T10:00:00+08:00"},
        )
        self.assertEqual(validate_manifest(approved)["status"], "approved")


class LoaderTests(unittest.TestCase):
    def test_json_loader_rejects_duplicate_keys_nan_and_bad_json(self) -> None:
        loader = JsonDocumentLoader()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "value.json"
            for text, message in (
                ('{"a":1,"a":2}', "duplicate"),
                ('{"a":NaN}', "constant"),
                ('{"a":}', "invalid JSON"),
            ):
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(OutlineFormatError, message):
                        loader.load(path)

    def test_yaml_loader_has_explicit_missing_dependency_error(self) -> None:
        loader = OptionalYamlDocumentLoader()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "value.yaml"
            path.write_text("value: 1\n", encoding="utf-8")
            original_import = builtins.__import__

            def blocked(name, *args, **kwargs):
                if name == "yaml":
                    raise ImportError("injected missing adapter")
                return original_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=blocked):
                with self.assertRaisesRegex(OutlineDependencyError, "optional YAML adapter"):
                    loader.load(path)


class OutlinePackageTests(unittest.TestCase):
    def validator(self) -> OutlinePackageValidator:
        return OutlinePackageValidator()

    def copy_valid(self, destination: Path) -> Path:
        target = destination / "outline"
        shutil.copytree(FIXTURES / "valid-json" / "outline", target)
        return target

    def test_valid_json_package_reports_all_files_and_stable_hash(self) -> None:
        root = FIXTURES / "valid-json" / "outline"
        report = self.validator().validate(root, expected_book_id="book_demo")
        second = self.validator().validate(root, expected_book_id="book_demo")
        self.assertTrue(report.ok)
        self.assertEqual(report.schema_version, "outline.v1")
        self.assertEqual(report.structured_document_count, len(STRUCTURED_STEMS))
        self.assertEqual(report.source_file_count, 1)
        self.assertEqual(report.package_hash, second.package_hash)
        self.assertEqual(report.manifest_file, "00-manifest.json")
        self.assertEqual(len(report.files), len(STRUCTURED_STEMS) + 2)

    def test_package_hash_changes_with_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.copy_valid(Path(temp_dir))
            first = self.validator().validate(root).package_hash
            (root / "sources" / "README.md").write_text("changed\n", encoding="utf-8")
            second = self.validator().validate(root).package_hash
            self.assertNotEqual(first, second)

    def test_static_broken_fixtures_fail_at_expected_layer(self) -> None:
        cases = [
            ("broken-missing-manifest", OutlineLayoutError, "missing"),
            ("broken-invalid-manifest", OutlineFormatError, "missing fields"),
            ("broken-invalid-json", OutlineFormatError, "invalid JSON"),
            ("broken-unknown-entry", OutlineLayoutError, "unknown entries"),
            ("broken-duplicate-format", OutlineLayoutError, "ambiguous"),
        ]
        for name, exception, message in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(exception, message):
                    self.validator().validate(FIXTURES / name / "outline")

    def test_non_object_or_array_structured_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.copy_valid(Path(temp_dir))
            (root / "02-theme.json").write_text('"free text"\n', encoding="utf-8")
            with self.assertRaisesRegex(OutlineFormatError, "object or array"):
                self.validator().validate(root)

    @unittest.skipIf(os.name == "nt", "symlink creation is not deterministic on Windows")
    def test_root_and_nested_source_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.copy_valid(Path(temp_dir))
            target = root / "02-theme.json"
            target.unlink()
            target.symlink_to(root / "03-world.json")
            with self.assertRaisesRegex(OutlineLayoutError, "symbolic links"):
                self.validator().validate(root)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.copy_valid(Path(temp_dir))
            (root / "sources" / "link.md").symlink_to(root / "01-premise.md")
            with self.assertRaisesRegex(OutlineLayoutError, "symbolic links"):
                self.validator().validate(root)

    def test_validation_is_read_only_and_creates_no_compiled_or_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.copy_valid(Path(temp_dir))
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.validator().validate(root)
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((root.parent / "compiled").exists())
            self.assertFalse((root.parent / "ledger" / "events.jsonl").exists())
            self.assertFalse((root.parent / "state" / "state.db").exists())


class OutlineCliTests(unittest.TestCase):
    def test_manifest_schema_artifact_is_strict_draft_2020(self) -> None:
        value = json.loads((ROOT / "schemas" / "outline-manifest.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(value["additionalProperties"])
        self.assertEqual(value["properties"]["schema_version"]["const"], "outline.v1")
        self.assertEqual(set(value["required"]), {
            "schema_version", "book_id", "title", "language", "planned_chapters", "canon_policy"
        })

    def test_exact_book_command_validates_demo_package(self) -> None:
        result = run_cli("outline", "validate", "--book", "book_demo", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["book_id"], "book_demo")

    def test_studio_outline_validate_json(self) -> None:
        path = FIXTURES / "valid-json" / "outline"
        result = run_cli("outline", "validate", "--path", str(path), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["ok"])
        self.assertEqual(value["book_id"], "book_demo")

    def test_cli_error_codes_distinguish_layout_and_format(self) -> None:
        layout = run_cli(
            "outline", "validate", "--path", str(FIXTURES / "broken-missing-manifest" / "outline"), "--json"
        )
        self.assertEqual(layout.returncode, 1)
        self.assertEqual(json.loads(layout.stdout)["exit_code"], 1)
        formatted = run_cli(
            "outline", "validate", "--path", str(FIXTURES / "broken-invalid-json" / "outline"), "--json"
        )
        self.assertEqual(formatted.returncode, 2)
        self.assertEqual(json.loads(formatted.stdout)["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
