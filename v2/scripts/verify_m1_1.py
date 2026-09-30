#!/usr/bin/env python3
"""Produce external evidence for M1.1 durable atomic-file primitives."""

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
EVIDENCE = ROOT / "verification" / "M1.1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str, command: list[str], expected: int = 0) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "name": name,
        "command": command,
        "expected_exit_code": expected,
        "actual_exit_code": result.returncode,
        "passed": result.returncode == expected,
        "duration_seconds": round(time.monotonic() - started, 6),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tmp_root = EVIDENCE / "tmp"
    tmp_root.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="verify-", dir=tmp_root))
    cases: list[dict[str, Any]] = []
    observations: dict[str, Any] = {}
    python = sys.executable
    try:
        cases.append(run("full_unit_suite", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]))

        success_target = work / "success.bin"
        success_code = (
            "from pathlib import Path; "
            "from novel_kernel.storage import atomic_write_bytes; "
            f"r=atomic_write_bytes(Path({str(success_target)!r}), b'new-complete-state'); "
            "print(r.content_hash)"
        )
        cases.append(run("atomic_success_subprocess", [python, "-c", success_code]))
        observations["success_bytes"] = success_target.read_text(encoding="utf-8") if success_target.exists() else None
        observations["success_hash"] = digest(success_target) if success_target.exists() else None

        crash_target = work / "crash.bin"
        old_bytes = b"old-authoritative-state"
        crash_target.write_bytes(old_bytes)
        crash_code = (
            "import os; from pathlib import Path; "
            "from novel_kernel.storage import atomic_write_bytes; "
            f"atomic_write_bytes(Path({str(crash_target)!r}), b'partial-replacement', "
            "_before_replace=lambda: os._exit(91))"
        )
        crash_case = run("hard_exit_before_replace", [python, "-c", crash_code], expected=91)
        old_survived = crash_target.read_bytes() == old_bytes
        crash_case["passed"] = crash_case["passed"] and old_survived
        crash_case["old_destination_survived"] = old_survived
        cases.append(crash_case)
        orphan_temps = list(work.glob(".crash.bin.atomic-*.tmp"))
        observations["hard_exit_old_hash"] = digest(crash_target)
        observations["hard_exit_temp_files_detected"] = len(orphan_temps)
        for temp in orphan_temps:
            temp.unlink()

        suspect = work / "suspect.bin"
        suspect.write_bytes(b"forensic-evidence")
        quarantine_dir = work / "quarantine"
        quarantine_code = (
            "import json; from dataclasses import asdict; from pathlib import Path; "
            "from novel_kernel.storage import quarantine_file; "
            f"r=quarantine_file(Path({str(suspect)!r}), Path({str(quarantine_dir)!r}), "
            "reason='verification mismatch', expected_hash='sha256:'+'0'*64); "
            "print(json.dumps(asdict(r), sort_keys=True))"
        )
        quarantine_case = run("quarantine_subprocess", [python, "-c", quarantine_code])
        isolated = list(quarantine_dir.glob("*.bin"))
        metadata = list(quarantine_dir.glob("*.json"))
        quarantine_valid = (
            not suspect.exists()
            and len(isolated) == 1
            and isolated[0].read_bytes() == b"forensic-evidence"
            and len(metadata) == 1
            and json.loads(metadata[0].read_text(encoding="utf-8"))["hash_mismatch"] is True
        )
        quarantine_case["passed"] = quarantine_case["passed"] and quarantine_valid
        quarantine_case["forensic_bytes_preserved"] = quarantine_valid
        cases.append(quarantine_case)
        observations["quarantine_hash"] = digest(isolated[0]) if isolated else None

        hash_code = (
            "from novel_kernel.storage import canonical_json_bytes, sha256_json; "
            "v={'z':1,'a':'中文'}; print(canonical_json_bytes(v).decode()); print(sha256_json(v))"
        )
        cases.append(run("canonical_json_hash_subprocess", [python, "-c", hash_code]))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [case for case in cases if not case["passed"]]
    completed = now()
    write_json(EVIDENCE / "test-run.json", {
        "schema_version": "m1.1.verification.v1",
        "milestone": "M1.1",
        "completed_at": completed,
        "cases": cases,
        "summary": {"total": len(cases), "passed": len(cases) - len(failed), "failed": len(failed)},
        "observations": observations,
    })
    write_json(EVIDENCE / "metrics.json", {
        "milestone": "M1.1",
        "cases_total": len(cases),
        "cases_passed": len(cases) - len(failed),
        "unexpected_failures": len(failed),
        "hard_exit_injected": True,
        "old_state_survived_hard_exit": next(
            (case.get("old_destination_survived") for case in cases if case["name"] == "hard_exit_before_replace"), False
        ),
        "third_party_dependencies": 0,
    })
    write_json(EVIDENCE / "failures.json", {"milestone": "M1.1", "unexpected_failures": failed})

    lines = [f"M1.1 verification completed at {completed}", ""]
    for case in cases:
        lines.extend([
            f"[{case['name']}]",
            f"command: {' '.join(case['command'])}",
            f"expected_exit_code: {case['expected_exit_code']}",
            f"actual_exit_code: {case['actual_exit_code']}",
            f"result: {'PASS' if case['passed'] else 'FAIL'}",
            "stdout:", case["stdout"].rstrip(), "stderr:", case["stderr"].rstrip(), "",
        ])
    (EVIDENCE / "command-log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    decision = "PASS" if not failed else "FAIL"
    (EVIDENCE / "decision.md").write_text(
        "\n".join([
            "# M1.1 verification decision", "", f"- Decision: **{decision}**",
            f"- Completed at: `{completed}`", f"- Cases: `{len(cases)}`",
            f"- Unexpected failures: `{len(failed)}`",
            "- Hard process exit before replace: executed",
            "- Old destination survived hard exit: yes" if not failed else "- Old destination survived hard exit: inspect failures",
            "- Third-party dependencies: `0`", "",
            "Scope is limited to atomic files, hashes, and quarantine. Event logs, locks,",
            "objects, SQLite projections, and snapshots remain unimplemented.", "",
        ]), encoding="utf-8"
    )
    indexed = ["test-run.json", "command-log.txt", "metrics.json", "failures.json", "decision.md"]
    write_json(EVIDENCE / "evidence-index.json", {
        "schema_version": "m1.1.evidence-index.v1", "milestone": "M1.1", "generated_at": now(),
        "artifacts": [{"path": name, "sha256": digest(EVIDENCE / name)} for name in indexed],
    })
    try:
        tmp_root.rmdir()
    except OSError:
        pass
    print(f"M1.1 verification: {decision} ({len(cases) - len(failed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
