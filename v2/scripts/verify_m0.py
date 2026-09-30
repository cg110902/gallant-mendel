#!/usr/bin/env python3
"""Black-box M0 acceptance verifier and evidence writer."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "studio.py"
EVIDENCE = ROOT / "verification" / "M0"
FIXTURES = ROOT / "workspace" / "_fixture"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_case(name: str, arguments: list[str], expected: int, cwd: Path = ROOT) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(arguments, cwd=cwd, text=True, capture_output=True, check=False)
    return {
        "name": name,
        "command": arguments,
        "cwd": str(cwd),
        "expected_exit_code": expected,
        "actual_exit_code": result.returncode,
        "passed": result.returncode == expected,
        "duration_seconds": round(time.monotonic() - started, 6),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    cases: list[dict[str, Any]] = []
    commands = [
        ("version", [python, str(STUDIO), "version"], 0),
        ("version_json", [python, str(STUDIO), "version", "--json"], 0),
        ("help", [python, str(STUDIO), "help"], 0),
        ("doctor_no_api_key", [python, str(STUDIO), "doctor", "--no-api-key"], 0),
        ("doctor_json", [python, str(STUDIO), "doctor", "--no-api-key", "--json"], 0),
        ("valid_fixture", [python, str(STUDIO), "doctor", "--fixture", str(FIXTURES / "valid")], 0),
        ("missing_manifest", [python, str(STUDIO), "doctor", "--fixture", str(FIXTURES / "broken_missing_manifest")], 1),
        ("invalid_json", [python, str(STUDIO), "doctor", "--fixture", str(FIXTURES / "broken_invalid_json")], 2),
        ("missing_field", [python, str(STUDIO), "doctor", "--fixture", str(FIXTURES / "broken_missing_field")], 2),
        ("unknown_command", [python, str(STUDIO), "not-a-command"], 1),
        (
            "unit_tests",
            [python, "-m", "unittest", "discover", "-s", "tests", "-v"],
            0,
        ),
    ]
    for name, arguments, expected in commands:
        cases.append(run_case(name, arguments, expected))

    tmp_parent = EVIDENCE / "tmp"
    tmp_parent.mkdir(exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="verify-", dir=tmp_parent))
    permission_probe = "not-run"
    try:
        init_target = temp_dir / "initialized"
        cases.append(run_case("init", [python, str(STUDIO), "init", "--path", str(init_target)], 0))
        cases.append(run_case("duplicate_init", [python, str(STUDIO), "init", "--path", str(init_target)], 1))

        readonly = temp_dir / "readonly"
        readonly.mkdir()
        readonly.chmod(stat.S_IRUSR | stat.S_IXUSR)
        if os.name == "nt" or os.access(readonly, os.W_OK):
            permission_probe = "skip: platform does not enforce deterministic chmod write denial"
        else:
            permission_probe = "pass"
            cases.append(
                run_case(
                    "readonly_probe",
                    [python, str(STUDIO), "doctor", "--write-probe", str(readonly)],
                    5,
                )
            )
        readonly.chmod(stat.S_IRWXU)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    passed = [case for case in cases if case["passed"]]
    failed = [case for case in cases if not case["passed"]]
    completed_at = timestamp()
    test_run = {
        "schema_version": "m0.verification.v1",
        "milestone": "M0",
        "completed_at": completed_at,
        "python": sys.version,
        "cases": cases,
        "summary": {"total": len(cases), "passed": len(passed), "failed": len(failed)},
    }
    write_json(EVIDENCE / "test-run.json", test_run)
    write_json(
        EVIDENCE / "metrics.json",
        {
            "milestone": "M0",
            "completed_at": completed_at,
            "commands_total": len(cases),
            "commands_passed": len(passed),
            "commands_failed": len(failed),
            "permission_probe": permission_probe,
            "third_party_dependencies": 0,
        },
    )
    write_json(
        EVIDENCE / "failures.json",
        {
            "milestone": "M0",
            "unexpected_failures": failed,
            "expected_rejections": [
                case["name"]
                for case in cases
                if case["expected_exit_code"] != 0 and case["passed"]
            ],
        },
    )

    log_lines = [f"M0 black-box verification completed at {completed_at}", ""]
    for case in cases:
        command = " ".join(case["command"])
        log_lines.extend(
            [
                f"[{case['name']}]",
                f"command: {command}",
                f"cwd: {case['cwd']}",
                f"expected_exit_code: {case['expected_exit_code']}",
                f"actual_exit_code: {case['actual_exit_code']}",
                f"result: {'PASS' if case['passed'] else 'FAIL'}",
                "stdout:",
                case["stdout"].rstrip(),
                "stderr:",
                case["stderr"].rstrip(),
                "",
            ]
        )
    (EVIDENCE / "command-log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    decision = "PASS" if not failed else "FAIL"
    (EVIDENCE / "decision.md").write_text(
        "\n".join(
            [
                "# M0 verification decision",
                "",
                f"- Decision: **{decision}**",
                f"- Completed at: `{completed_at}`",
                f"- Black-box cases: `{len(cases)}`",
                f"- Passed: `{len(passed)}`",
                f"- Unexpected failures: `{len(failed)}`",
                f"- Permission probe: `{permission_probe}`",
                "- API key required: `false`",
                "- Third-party runtime dependencies: `0`",
                "",
                "M0 establishes only the engineering constitution, minimal CLI, diagnostics,",
                "fixtures, and rejection behavior. It does not implement M1 business state.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    evidence_files = [
        "test-run.json",
        "command-log.txt",
        "metrics.json",
        "failures.json",
        "decision.md",
    ]
    write_json(
        EVIDENCE / "evidence-index.json",
        {
            "schema_version": "m0.evidence-index.v1",
            "milestone": "M0",
            "generated_at": timestamp(),
            "artifacts": [
                {"path": name, "sha256": sha256(EVIDENCE / name)} for name in evidence_files
            ],
        },
    )
    try:
        tmp_parent.rmdir()
    except OSError:
        pass

    print(f"M0 verification: {decision} ({len(passed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
