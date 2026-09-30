from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from novel_kernel.outline_compile import (
    LOGICAL_PATHS,
    OutlineCompileEnvironmentError,
    OutlineCompileIntegrityError,
    OutlineCompiler,
)
from novel_kernel.storage import sha256_bytes

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "workspace" / "_fixture" / "outline" / "valid-semantic" / "outline"
STUDIO = ROOT / "studio.py"


class OutlineCompilerTests(unittest.TestCase):
    def test_compiled_protocol_schemas_are_strict(self) -> None:
        expected = {
            "outline-current.schema.json": "outline.current.v1",
            "outline-artifact-index.schema.json": "outline.artifact-index.v1",
            "production-manifest.schema.json": "production-manifest.v1",
        }
        for name, version in expected.items():
            with self.subTest(name=name):
                value = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
                self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertFalse(value["additionalProperties"])
                self.assertEqual(value["properties"]["schema_version"]["const"], version)

    def book(self, parent: Path) -> Path:
        book = parent / "book_demo"
        shutil.copytree(FIXTURE, book / "outline")
        return book

    def test_compile_publishes_content_addressed_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            result = OutlineCompiler().compile(book / "outline", expected_book_id="book_demo")
            self.assertTrue(result.ok)
            self.assertFalse(result.reused_generation)
            generation = Path(result.generation_path)
            self.assertEqual({path.name for path in generation.iterdir()}, set(LOGICAL_PATHS) | {"artifact-index.json"})
            pointer_bytes = (book / "compiled" / "current.json").read_bytes()
            pointer = json.loads(pointer_bytes)
            self.assertEqual(pointer["compile_id"], result.compile_id)
            self.assertEqual(pointer_bytes, json.dumps(pointer, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
            index = json.loads((generation / "artifact-index.json").read_text())
            self.assertEqual(len(index["artifacts"]), 7)
            for artifact in index["artifacts"]:
                data = (generation / artifact["path"]).read_bytes()
                self.assertEqual(artifact["bytes"], len(data))
                self.assertEqual(artifact["sha256"], sha256_bytes(data))

    def test_same_input_is_idempotent_and_reuses_verified_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            first = OutlineCompiler().compile(book / "outline")
            before = {path.name: path.read_bytes() for path in Path(first.generation_path).iterdir()}
            second = OutlineCompiler().compile(book / "outline")
            after = {path.name: path.read_bytes() for path in Path(second.generation_path).iterdir()}
            self.assertEqual(first.compile_id, second.compile_id)
            self.assertTrue(second.reused_generation)
            self.assertEqual(before, after)
            self.assertEqual(second.previous_compile_id, first.compile_id)

    def test_changed_source_publishes_new_generation_and_preserves_old(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            first = OutlineCompiler().compile(book / "outline")
            cast = book / "outline" / "04-cast.json"
            value = json.loads(cast.read_text())
            value[0]["name"] = "凌云改名"
            cast.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            second = OutlineCompiler().compile(book / "outline")
            self.assertNotEqual(first.compile_id, second.compile_id)
            self.assertEqual(second.previous_compile_id, first.compile_id)
            self.assertTrue(Path(first.generation_path).is_dir())
            self.assertTrue(Path(second.generation_path).is_dir())

    def test_pointer_fault_preserves_old_pointer_and_removes_new_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            compiler = OutlineCompiler()
            first = compiler.compile(book / "outline")
            pointer = book / "compiled" / "current.json"
            before = pointer.read_bytes()
            theme = book / "outline" / "02-theme.json"
            theme.write_text('{"note":"changed"}', encoding="utf-8")
            def fail() -> None:
                raise RuntimeError("injected before pointer")
            with self.assertRaisesRegex(RuntimeError, "injected"):
                compiler.compile(book / "outline", _before_pointer=fail)
            self.assertEqual(pointer.read_bytes(), before)
            generations = [path for path in (book / "compiled" / "generations").iterdir() if path.is_dir()]
            self.assertEqual([path.name for path in generations], [first.compile_id.removeprefix("sha256:")])

    def test_tampered_generation_is_rejected_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            result = OutlineCompiler().compile(book / "outline")
            target = Path(result.generation_path) / "objects.json"
            target.write_text("tampered", encoding="utf-8")
            with self.assertRaises(OutlineCompileIntegrityError):
                OutlineCompiler().compile(book / "outline")
            self.assertEqual(target.read_text(), "tampered")

    def test_manifest_is_json_compatible_yaml_and_report_has_no_clock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            result = OutlineCompiler().compile(book / "outline")
            generation = Path(result.generation_path)
            manifest = json.loads((generation / "production-manifest.yaml").read_text())
            self.assertEqual(manifest["compile_id"], result.compile_id)
            report = (generation / "compile-report.md").read_text()
            self.assertIn("Decision: **PASS**", report)
            self.assertNotIn("Completed at", report)

    def test_invalid_outline_creates_no_compiled_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            path = book / "outline" / "12-chapter-map.json"
            value = json.loads(path.read_text())
            del value[0]["purpose"]
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(Exception):
                OutlineCompiler().compile(book / "outline")
            self.assertFalse((book / "compiled").exists())

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_compiled_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            target = book / "elsewhere"
            target.mkdir()
            (book / "compiled").symlink_to(target, target_is_directory=True)
            with self.assertRaises(OutlineCompileEnvironmentError):
                OutlineCompiler().compile(book / "outline")

    def test_compile_creates_no_authority_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = self.book(Path(temp))
            OutlineCompiler().compile(book / "outline")
            self.assertFalse((book / "ledger" / "events.jsonl").exists())
            self.assertFalse((book / "state" / "state.db").exists())


class OutlineCompileCliTests(unittest.TestCase):
    def test_cli_compile_json_and_idempotent_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = Path(temp) / "book_demo"
            shutil.copytree(FIXTURE, book / "outline")
            command = [sys.executable, str(STUDIO), "outline", "compile", "--path", str(book / "outline"), "--json"]
            first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_value, second_value = json.loads(first.stdout), json.loads(second.stdout)
            self.assertEqual(first_value["compile_id"], second_value["compile_id"])
            self.assertFalse(first_value["reused_generation"])
            self.assertTrue(second_value["reused_generation"])

    def test_cli_integrity_failure_returns_six(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            book = Path(temp) / "book_demo"
            shutil.copytree(FIXTURE, book / "outline")
            result = OutlineCompiler().compile(book / "outline")
            (Path(result.generation_path) / "timeline.json").write_text("tampered")
            command = [sys.executable, str(STUDIO), "outline", "compile", "--path", str(book / "outline"), "--json"]
            failed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(failed.returncode, 6)
            self.assertEqual(json.loads(failed.stdout)["exit_code"], 6)


if __name__ == "__main__":
    unittest.main()
