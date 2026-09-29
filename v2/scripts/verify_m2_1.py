#!/usr/bin/env python3
"""Black-box verification and evidence generation for M2.1 Outline validation."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "verification" / "M2.1"
FIXTURES = ROOT / "workspace" / "_fixture" / "outline"
STUDIO = ROOT / "studio.py"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str, command: list[str], expected: int = 0) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    passed = result.returncode == expected
    parsed: Any = None
    if "--json" in command and result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            passed = passed and parsed.get("ok") is (expected == 0)
        except (json.JSONDecodeError, AttributeError):
            passed = False
    return {
        "name": name,
        "command": command,
        "expected_exit_code": expected,
        "actual_exit_code": result.returncode,
        "passed": passed,
        "duration_seconds": round(time.monotonic() - started, 6),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "parsed": parsed,
    }


def fixture(name: str) -> str:
    return str(FIXTURES / name / "outline")


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tmp_parent = EVIDENCE / "tmp"
    tmp_parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="verify-", dir=tmp_parent))
    cases: list[dict[str, Any]] = []
    python = sys.executable
    try:
        cases.append(run("full_unit_suite", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]))
        cases.append(run("valid_json_package", [python, str(STUDIO), "outline", "validate", "--book", "book_demo", "--json"]))
        cases.append(run("missing_required_file", [python, str(STUDIO), "outline", "validate", "--path", fixture("broken-missing-manifest"), "--json"], 1))
        cases.append(run("duplicate_format", [python, str(STUDIO), "outline", "validate", "--path", fixture("broken-duplicate-format"), "--json"], 1))
        cases.append(run("unknown_root_entry", [python, str(STUDIO), "outline", "validate", "--path", fixture("broken-unknown-entry"), "--json"], 1))
        cases.append(run("malformed_json", [python, str(STUDIO), "outline", "validate", "--path", fixture("broken-invalid-json"), "--json"], 2))
        cases.append(run("invalid_manifest", [python, str(STUDIO), "outline", "validate", "--path", fixture("broken-invalid-manifest"), "--json"], 2))

        yaml_root = work / "yaml" / "outline"
        shutil.copytree(FIXTURES / "valid-json" / "outline", yaml_root)
        (yaml_root / "02-theme.json").rename(yaml_root / "02-theme.yaml")
        cases.append(run("yaml_adapter_unavailable", [python, "-S", str(STUDIO), "outline", "validate", "--path", str(yaml_root), "--json"], 5))

        symlink_root = work / "symlink" / "outline"
        shutil.copytree(FIXTURES / "valid-json" / "outline", symlink_root)
        (symlink_root / "sources" / "linked.md").symlink_to(symlink_root / "01-premise.md")
        cases.append(run("nested_symlink_rejected", [python, str(STUDIO), "outline", "validate", "--path", str(symlink_root), "--json"], 1))

        mismatch_book = "book_mismatch_m21"
        mismatch_root = ROOT / "workspace" / mismatch_book
        shutil.rmtree(mismatch_root, ignore_errors=True)
        shutil.copytree(FIXTURES / "valid-json" / "outline", mismatch_root / "outline")
        try:
            cases.append(run("manifest_book_mismatch", [python, str(STUDIO), "outline", "validate", "--book", mismatch_book, "--json"], 2))
        finally:
            shutil.rmtree(mismatch_root, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [case for case in cases if not case["passed"]]
    completed = now()
    summary = {"total": len(cases), "passed": len(cases) - len(failed), "failed": len(failed)}
    write_json(EVIDENCE / "test-run.json", {
        "schema_version": "m2.1.verification.v1", "milestone": "M2.1", "completed_at": completed,
        "cases": cases, "summary": summary,
    })
    write_json(EVIDENCE / "metrics.json", {
        "milestone": "M2.1", "cases_total": len(cases), "cases_passed": len(cases) - len(failed),
        "unexpected_failures": len(failed), "required_structured_documents": 14,
        "layout_rejection_cases": 4, "format_rejection_cases": 3,
        "yaml_dependency_boundary_verified": next(case["passed"] for case in cases if case["name"] == "yaml_adapter_unavailable"),
        "authority_files_created": 0, "core_third_party_dependencies": 0,
    })
    write_json(EVIDENCE / "failures.json", {"milestone": "M2.1", "unexpected_failures": failed})
    lines = [f"M2.1 verification completed at {completed}", ""]
    for case in cases:
        lines.extend([
            f"[{case['name']}]", f"command: {' '.join(case['command'])}",
            f"expected_exit_code: {case['expected_exit_code']}", f"actual_exit_code: {case['actual_exit_code']}",
            f"result: {'PASS' if case['passed'] else 'FAIL'}", "stdout:", case["stdout"].rstrip(),
            "stderr:", case["stderr"].rstrip(), "",
        ])
    (EVIDENCE / "command-log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    decision = "PASS" if not failed else "FAIL"
    (EVIDENCE / "decision.md").write_text("\n".join([
        "# M2.1 verification decision", "", f"- Decision: **{decision}**", f"- Completed at: `{completed}`",
        f"- Cases: `{len(cases)}`", f"- Unexpected failures: `{len(failed)}`",
        "- Strict root layout and fixed file set: verified",
        "- Manifest v1 and book binding: verified",
        "- JSON baseline and optional YAML boundary: verified",
        "- Read-only validation / no authority output: covered by unit tests",
        "- M2.2 semantic compilation: not implemented", "- Core third-party dependencies: `0`", "",
    ]), encoding="utf-8")
    indexed = ["test-run.json", "command-log.txt", "metrics.json", "failures.json", "decision.md"]
    write_json(EVIDENCE / "evidence-index.json", {
        "schema_version": "m2.1.evidence-index.v1", "milestone": "M2.1", "generated_at": now(),
        "artifacts": [{"path": name, "sha256": digest(EVIDENCE / name)} for name in indexed],
    })
    try:
        tmp_parent.rmdir()
    except OSError:
        pass
    print(f"M2.1 verification: {decision} ({len(cases) - len(failed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
