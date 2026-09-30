from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from novel_kernel.agent_layout import validate_agent_layout

ROOT = Path(__file__).resolve().parents[1]


class AgentLayoutTests(unittest.TestCase):
    def test_four_layouts_have_at_least_ten_passing_checks(self) -> None:
        report = validate_agent_layout(ROOT)
        self.assertTrue(report.ok)
        self.assertEqual(set(report.platform_totals), {"antigravity", "claude", "cursor", "codex"})
        for totals in report.platform_totals.values():
            self.assertGreaterEqual(totals["total"], 10)
            self.assertEqual(totals["passed"], totals["total"])
            self.assertEqual(totals["failed"], 0)

    def test_doctor_agent_layout_is_no_api_key_and_machine_readable(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "studio.py"), "doctor", "--agent-layout", "--no-api-key", "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["ok"])
        self.assertFalse(value["api_key_required"])
        self.assertTrue(value["agent_layout"]["ok"])
        self.assertGreaterEqual(sum(x["total"] for x in value["agent_layout"]["platform_totals"].values()), 40)
        self.assertFalse([x for x in value["checks"] if x["id"].startswith("agent_layout.") and x["status"] != "pass"])

    def test_stale_reference_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in (".agents", ".claude", ".cursor", ".codex"):
                shutil.copytree(ROOT / name, root / name)
            claude = root / ".claude" / "CLAUDE.md"
            claude.write_text("standalone duplicated rules\n", encoding="utf-8")
            skill = root / ".agents" / "skills" / "novel-doctor" / "SKILL.md"
            skill.unlink()
            skill.symlink_to(ROOT / ".agents" / "skills" / "novel-doctor" / "SKILL.md")
            report = validate_agent_layout(root)
            failed = {row.check_id for row in report.checks if not row.passed}
            self.assertFalse(report.ok)
            self.assertIn("canonical_doctor_skill", failed)
            self.assertIn("canonical_reference", failed)


if __name__ == "__main__":
    unittest.main()
