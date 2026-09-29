from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "studio.py"
FIXTURES = ROOT / "workspace" / "_fixture"
EXPECTED_EXIT_CODES = {
    0: "SUCCESS",
    1: "INPUT_OR_CONFIG_ERROR",
    2: "SCHEMA_FORMAT_ERROR",
    3: "HARD_VIOLATION",
    4: "HUMAN_GATE",
    5: "ENVIRONMENT_ERROR",
    6: "REPLAY_PROJECTION_ERROR",
    7: "RESOURCE_GUARD",
}


def run_cli(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STUDIO), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


class M0CliTests(unittest.TestCase):
    def test_version_returns_zero(self) -> None:
        result = run_cli("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0.1.0-dev", result.stdout)
        self.assertIn("phase M5.4", result.stdout)

    def test_version_json_is_parseable(self) -> None:
        result = run_cli("version", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["project"], "novel-production-os")
        self.assertEqual(value["python_min"], "3.11")
        self.assertEqual(value["phase"], "M5.4")
        self.assertFalse(value["api_required"])

    def test_help_and_topic_return_zero(self) -> None:
        for args in (("help",), ("--help",), ("help", "doctor")):
            with self.subTest(args=args):
                result = run_cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Usage", result.stdout)

    def test_unknown_command_returns_one_on_stderr(self) -> None:
        result = run_cli("not-a-command")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("unknown command", result.stderr)

    def test_doctor_no_api_key_returns_zero(self) -> None:
        result = run_cli("doctor", "--no-api-key")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no-api-key-ready", result.stdout)

    def test_doctor_json_contains_checks(self) -> None:
        result = run_cli("doctor", "--no-api-key", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["ok"])
        self.assertFalse(value["api_key_required"])
        self.assertGreaterEqual(len(value["checks"]), 8)

    def test_doctor_rejects_wrong_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_cli("doctor", cwd=Path(temp_dir))
        self.assertEqual(result.returncode, 1)
        self.assertIn("engineering_root", result.stderr)

    def test_init_creates_only_m0_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "book"
            result = run_cli("init", "--path", str(target))
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "m0.workspace.v1")
            self.assertFalse((target / "events.jsonl").exists())
            self.assertFalse((target / "state.db").exists())
            for name in ("outline", "state", "ledger", "production", "chapters", "runs", "audits", "snapshots", "branches", "exports"):
                self.assertTrue((target / name).is_dir(), name)

    def test_init_does_not_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "existing"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            result = run_cli("init", "--path", str(target))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse((target / "manifest.json").exists())

    def test_init_force_preserves_unknown_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "existing"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            result = run_cli("init", "--path", str(target), "--force")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertTrue((target / "manifest.json").is_file())

    def test_valid_fixture_passes(self) -> None:
        result = run_cli("doctor", "--fixture", str(FIXTURES / "valid"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_manifest_returns_one(self) -> None:
        result = run_cli("doctor", "--fixture", str(FIXTURES / "broken_missing_manifest"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("manifest is missing", result.stderr)

    def test_invalid_json_fixture_returns_two(self) -> None:
        result = run_cli("doctor", "--fixture", str(FIXTURES / "broken_invalid_json"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid JSON", result.stderr)

    def test_missing_required_field_returns_two(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            (fixture / "manifest.json").write_text(
                json.dumps({"schema_version": "m0.fixture.v1"}), encoding="utf-8"
            )
            result = run_cli("doctor", "--fixture", str(fixture))
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing field", result.stderr)

    @unittest.skipIf(os.name == "nt", "chmod write semantics are not deterministic on Windows")
    def test_readonly_write_probe_returns_five_or_explicit_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            probe_dir = Path(temp_dir) / "readonly"
            probe_dir.mkdir()
            probe_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
            try:
                can_write = os.access(probe_dir, os.W_OK)
                result = run_cli("doctor", "--write-probe", str(probe_dir))
                if can_write:
                    self.skipTest("platform reports chmod directory as writable")
                self.assertEqual(result.returncode, 5)
                self.assertIn("write probe failed", result.stderr)
            finally:
                probe_dir.chmod(stat.S_IRWXU)

    def test_exit_code_document_matches_enum(self) -> None:
        text = (ROOT / "exit-codes.md").read_text(encoding="utf-8")
        found = {
            int(code): symbol
            for code, symbol in re.findall(r"\| ([0-7]) \| `([A-Z_]+)` \|", text)
        }
        self.assertEqual(found, EXPECTED_EXIT_CODES)


if __name__ == "__main__":
    unittest.main()
