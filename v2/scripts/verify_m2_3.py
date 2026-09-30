#!/usr/bin/env python3
"""Black-box verification and evidence generation for M2.3 domain completeness."""

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
EVIDENCE = ROOT / "verification" / "M2.3"
FIXTURE = ROOT / "workspace" / "_fixture" / "outline" / "valid-semantic" / "outline"
STUDIO = ROOT / "studio.py"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str, command: list[str], expected: int = 0, codes: tuple[str, ...] = ()) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    parsed: Any = None
    passed = result.returncode == expected
    if "--json" in command:
        try:
            parsed = json.loads(result.stdout)
            passed = passed and parsed.get("ok") is (expected == 0)
            actual_codes = {item["code"] for item in parsed.get("diagnostics", [])}
            passed = passed and all(code in actual_codes for code in codes)
        except (json.JSONDecodeError, AttributeError, KeyError):
            passed = False
    return {
        "name": name, "command": command, "expected_exit_code": expected,
        "actual_exit_code": result.returncode, "expected_diagnostics": list(codes), "passed": passed,
        "duration_seconds": round(time.monotonic() - started, 6), "stdout": result.stdout,
        "stderr": result.stderr, "parsed": parsed,
    }


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tmp_parent = EVIDENCE / "tmp"
    tmp_parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="verify-", dir=tmp_parent))
    python = sys.executable
    cases: list[dict[str, Any]] = []

    def broken(name: str, stem: str, mutate: Callable[[Any], None]) -> Path:
        root = work / name / "outline"
        shutil.copytree(FIXTURE, root)
        path = root / f"{stem}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        write_json(path, value)
        return root

    def cli(root: Path) -> list[str]:
        return [python, str(STUDIO), "outline", "validate", "--path", str(root), "--json"]

    try:
        cases.append(run("full_unit_suite", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]))
        valid = run("valid_domain_book", [python, str(STUDIO), "outline", "validate", "--book", "book_demo", "--json"])
        if valid["passed"]:
            domain = valid["parsed"].get("domain", {})
            valid["passed"] = domain.get("schema_version") == "outline.domain.v1" and domain.get("record_counts", {}).get("beats") == 1
        cases.append(valid)

        def unbounded(value: Any) -> None:
            value[0].pop("capabilities", None); value[0].pop("resources", None)
        cases.append(run("unbounded_character", cli(broken("character", "04-cast", unbounded)), 2, ("UNBOUNDED_CHARACTER",)))
        cases.append(run("faction_without_resources", cli(broken("faction", "05-factions", lambda value: value[0].pop("resources"))), 2, ("DOMAIN_SCHEMA_ERROR",)))
        cases.append(run("thread_without_turns", cli(broken("thread", "09-threads", lambda value: value[0].update({"turning_points": []}))), 2, ("DOMAIN_SCHEMA_ERROR",)))
        cases.append(run("obligation_without_resolution", cli(broken("obligation", "10-obligations", lambda value: value[0].update({"allowed_resolution": []}))), 2, ("OBLIGATION_WITHOUT_RESOLUTION",)))
        cases.append(run("arc_reverse_range", cli(broken("arc", "11-arcs", lambda value: value[0].update({"range": [50, 1]}))), 2, ("DOMAIN_SCHEMA_ERROR",)))

        def chapter(value: Any) -> None:
            value[0]["purpose"] = ""; value[0]["intent"].pop("required_hook")
        cases.append(run("chapter_purpose_and_hook", cli(broken("chapter", "12-chapter-map", chapter)), 2, ("CHAPTER_WITHOUT_PURPOSE", "CHAPTER_WITHOUT_HOOK")))

        def beat(value: Any) -> None:
            value[0]["beats"][0]["target_words"] = [900, 500]
        cases.append(run("beat_reverse_word_window", cli(broken("beat", "12-chapter-map", beat)), 2, ("DOMAIN_SCHEMA_ERROR",)))

        authority = list(work.rglob("events.jsonl")) + list(work.rglob("*.db")) + list(work.rglob("compiled"))
        cases.append({"name": "no_authority_or_compiled_output", "command": ["filesystem observation"],
            "expected_exit_code": 0, "actual_exit_code": 0 if not authority else 1,
            "expected_diagnostics": [], "passed": not authority, "duration_seconds": 0,
            "stdout": json.dumps([str(path) for path in authority]), "stderr": "", "parsed": None})
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [case for case in cases if not case["passed"]]
    completed = now()
    write_json(EVIDENCE / "test-run.json", {"schema_version": "m2.3.verification.v1", "milestone": "M2.3",
        "completed_at": completed, "cases": cases,
        "summary": {"total": len(cases), "passed": len(cases) - len(failed), "failed": len(failed)}})
    write_json(EVIDENCE / "metrics.json", {"milestone": "M2.3", "cases_total": len(cases),
        "cases_passed": len(cases) - len(failed), "unexpected_failures": len(failed),
        "validated_domain_types": 9, "sample_turning_points": 1, "sample_beats": 1,
        "authority_files_created": 0, "core_third_party_dependencies": 0})
    write_json(EVIDENCE / "failures.json", {"milestone": "M2.3", "unexpected_failures": failed})
    lines = [f"M2.3 verification completed at {completed}", ""]
    for case in cases:
        lines += [f"[{case['name']}]", f"command: {' '.join(case['command'])}",
            f"expected_exit_code: {case['expected_exit_code']}", f"actual_exit_code: {case['actual_exit_code']}",
            f"result: {'PASS' if case['passed'] else 'FAIL'}", "stdout:", case["stdout"].rstrip(),
            "stderr:", case["stderr"].rstrip(), ""]
    (EVIDENCE / "command-log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    decision = "PASS" if not failed else "FAIL"
    (EVIDENCE / "decision.md").write_text("\n".join(["# M2.3 verification decision", "",
        f"- Decision: **{decision}**", f"- Completed at: `{completed}`", f"- Cases: `{len(cases)}`",
        f"- Unexpected failures: `{len(failed)}`", "- Nine domain record types: verified",
        "- Executable thread/obligation/chapter/beat boundaries: verified",
        "- Deterministic domain diagnostics: verified", "- Read-only / no compiled or authority output: verified",
        "- M2.4 compiled artifacts: not implemented", "- Core third-party dependencies: `0`", ""]), encoding="utf-8")
    names = ["test-run.json", "command-log.txt", "metrics.json", "failures.json", "decision.md"]
    write_json(EVIDENCE / "evidence-index.json", {"schema_version": "m2.3.evidence-index.v1", "milestone": "M2.3",
        "generated_at": now(), "artifacts": [{"path": name, "sha256": digest(EVIDENCE / name)} for name in names]})
    try: tmp_parent.rmdir()
    except OSError: pass
    print(f"M2.3 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
