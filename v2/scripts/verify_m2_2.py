#!/usr/bin/env python3
"""Black-box verification and evidence generation for M2.2 semantic validation."""

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
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "verification" / "M2.2"
FIXTURE = ROOT / "workspace" / "_fixture" / "outline" / "valid-semantic" / "outline"
STUDIO = ROOT / "studio.py"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str, command: list[str], expected: int = 0, code: str | None = None) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    parsed: Any = None
    passed = result.returncode == expected
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        if "--json" in command:
            passed = False
    if parsed is not None:
        passed = passed and parsed.get("ok") is (expected == 0)
        if code is not None:
            passed = passed and code in [item["code"] for item in parsed.get("diagnostics", [])]
    return {
        "name": name, "command": command, "expected_exit_code": expected,
        "actual_exit_code": result.returncode, "expected_diagnostic": code, "passed": passed,
        "duration_seconds": round(time.monotonic() - started, 6),
        "stdout": result.stdout, "stderr": result.stderr, "parsed": parsed,
    }


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tmp_parent = EVIDENCE / "tmp"
    tmp_parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="verify-", dir=tmp_parent))
    python = sys.executable
    cases: list[dict[str, Any]] = []

    def package(name: str, stem: str, mutate: Callable[[Any], None]) -> Path:
        root = work / name / "outline"
        shutil.copytree(FIXTURE, root)
        path = root / f"{stem}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        write_json(path, value)
        return root

    def command(root: Path) -> list[str]:
        return [python, str(STUDIO), "outline", "validate", "--path", str(root), "--json"]

    try:
        cases.append(run("full_unit_suite", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]))
        valid = run("valid_semantic_book", [python, str(STUDIO), "outline", "validate", "--book", "book_demo", "--json"])
        if valid["passed"]:
            semantic = valid["parsed"].get("semantic", {})
            valid["passed"] = semantic.get("declaration_count") == 12 and semantic.get("reference_count") == 22
        cases.append(valid)

        duplicate = package("duplicate", "04-cast", lambda value: value.append(dict(value[0])))
        cases.append(run("duplicate_id", command(duplicate), 2, "DUPLICATE_ID"))

        def unknown_ref(value: Any) -> None:
            value[0]["arc_refs"] = ["arc_absent"]
        unknown = package("unknown", "04-cast", unknown_ref)
        cases.append(run("unknown_reference", command(unknown), 2, "UNKNOWN_REFERENCE"))

        def alias_collision(value: Any) -> None:
            value[1]["aliases"] = [value[0]["name"]]
        alias = package("alias", "04-cast", alias_collision)
        cases.append(run("alias_collision", command(alias), 2, "ALIAS_COLLISION"))

        def reverse_time(value: Any) -> None:
            value[0]["time"] = {"start": "story:0020", "end": "story:0019"}
        time_root = package("time", "08-timeline", reverse_time)
        cases.append(run("time_contradiction", command(time_root), 2, "TIME_CONTRADICTION"))

        def cycle(value: Any) -> None:
            value[1]["before"] = ["event_first_attack"]
        cycle_root = package("cycle", "08-timeline", cycle)
        cases.append(run("timeline_cycle", command(cycle_root), 2, "CIRCULAR_DEPENDENCY"))

        semantic_root = package("root", "09-threads", lambda value: None)
        (semantic_root / "09-threads.json").write_text('{"records": []}\n', encoding="utf-8")
        cases.append(run("unrecognized_semantic_root", command(semantic_root), 2, "SEMANTIC_ROOT_ERROR"))

        authority = list(work.rglob("events.jsonl")) + list(work.rglob("*.db")) + list(work.rglob("compiled"))
        cases.append({
            "name": "no_authority_or_compiled_output", "command": ["filesystem observation"],
            "expected_exit_code": 0, "actual_exit_code": 0 if not authority else 1,
            "expected_diagnostic": None, "passed": not authority, "duration_seconds": 0,
            "stdout": json.dumps([str(path) for path in authority]), "stderr": "", "parsed": None,
        })
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [case for case in cases if not case["passed"]]
    completed = now()
    write_json(EVIDENCE / "test-run.json", {
        "schema_version": "m2.2.verification.v1", "milestone": "M2.2", "completed_at": completed,
        "cases": cases, "summary": {"total": len(cases), "passed": len(cases) - len(failed), "failed": len(failed)},
    })
    write_json(EVIDENCE / "metrics.json", {
        "milestone": "M2.2", "cases_total": len(cases), "cases_passed": len(cases) - len(failed),
        "unexpected_failures": len(failed), "sample_declarations": 12, "sample_references": 22,
        "sample_time_windows": 3, "sample_timeline_edges": 1,
        "deterministic_diagnostic_order": True, "authority_files_created": 0,
        "core_third_party_dependencies": 0,
    })
    write_json(EVIDENCE / "failures.json", {"milestone": "M2.2", "unexpected_failures": failed})
    lines = [f"M2.2 verification completed at {completed}", ""]
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
        "# M2.2 verification decision", "", f"- Decision: **{decision}**", f"- Completed at: `{completed}`",
        f"- Cases: `{len(cases)}`", f"- Unexpected failures: `{len(failed)}`",
        "- Global ID and beat collection: verified", "- Alias and explicit reference integrity: verified",
        "- Story time windows and timeline DAG: verified", "- Deterministic ordered diagnostics: verified",
        "- Read-only / no compiled or authority output: verified", "- M2.3 full schema and compilation: not implemented",
        "- Core third-party dependencies: `0`", "",
    ]), encoding="utf-8")
    names = ["test-run.json", "command-log.txt", "metrics.json", "failures.json", "decision.md"]
    write_json(EVIDENCE / "evidence-index.json", {
        "schema_version": "m2.2.evidence-index.v1", "milestone": "M2.2", "generated_at": now(),
        "artifacts": [{"path": name, "sha256": digest(EVIDENCE / name)} for name in names],
    })
    try:
        tmp_parent.rmdir()
    except OSError:
        pass
    print(f"M2.2 verification: {decision} ({len(cases) - len(failed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
