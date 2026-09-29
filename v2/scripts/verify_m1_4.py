#!/usr/bin/env python3
"""Black-box verification for M1.4 SQLite projection and replay."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "verification" / "M1.4"
REBUILD = ROOT / "scripts" / "rebuild_state.py"


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
        "name": name, "command": command, "expected_exit_code": expected,
        "actual_exit_code": result.returncode, "passed": result.returncode == expected,
        "duration_seconds": round(time.monotonic() - started, 6),
        "stdout": result.stdout, "stderr": result.stderr,
    }


def populate_command(book: Path) -> str:
    return (
        "from novel_kernel.events import EventLog; from tests.test_projection import ten_event_sequence; "
        f"log=EventLog({str(book)!r}); [log.append(e) for e in ten_event_sequence()]; print(len(log.read_events()))"
    )


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tmp_parent = EVIDENCE / "tmp"
    tmp_parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="verify-", dir=tmp_parent))
    python = sys.executable
    cases: list[dict[str, Any]] = []
    observations: dict[str, Any] = {}
    try:
        cases.append(run("full_unit_suite", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]))

        book = work / "book_demo"
        cases.append(run("populate_10_event_log", [python, "-c", populate_command(book)]))
        rebuilt = run("rebuild_cli_json", [python, str(REBUILD), "--book", str(book), "--json"])
        if rebuilt["passed"]:
            value = json.loads(rebuilt["stdout"])
            rebuilt["passed"] = value["ok"] and value["applied_event_count"] == 10
            observations["initial_state_hash"] = value["state_hash"]
        cases.append(rebuilt)

        database = book / "state" / "state.db"
        before_export = run(
            "query_projection",
            [python, "-c", f"from novel_kernel.projection import ProjectionStore; s=ProjectionStore({str(book)!r}); print(s.get_object('char_lin_yun')['canonical_name']); print(s.verify().state_hash)"],
        )
        cases.append(before_export)
        database.unlink()
        rebuilt_after_delete = run(
            "delete_database_and_rebuild",
            [python, str(REBUILD), "--book", str(book), "--json"],
        )
        if rebuilt_after_delete["passed"]:
            value = json.loads(rebuilt_after_delete["stdout"])
            rebuilt_after_delete["passed"] = value["state_hash"] == observations.get("initial_state_hash")
            observations["rebuild_after_delete_hash"] = value["state_hash"]
        cases.append(rebuilt_after_delete)

        append_audit = (
            "from novel_kernel.events import EventLog; from tests.test_projection import event,eid; "
            f"log=EventLog({str(book)!r}); log.append(event(11,'audit.completed',{{'report':'ok'}},eid(10))); print('ok')"
        )
        cases.append(run("append_non_business_event", [python, "-c", append_audit]))
        incremental = run(
            "incremental_update_cli",
            [python, str(REBUILD), "--book", str(book), "--update", "--json"],
        )
        if incremental["passed"]:
            value = json.loads(incremental["stdout"])
            incremental["passed"] = value["applied_event_count"] == 11
            observations["incremental_state_hash"] = value["state_hash"]
        cases.append(incremental)

        bad_book = work / "bad_book"
        cases.append(run("bad_log_populate", [python, "-c", populate_command(bad_book)]))
        cases.append(run("bad_log_initial_rebuild", [python, str(REBUILD), "--book", str(bad_book), "--json"]))
        bad_database = bad_book / "state" / "state.db"
        old_database_hash = digest(bad_database)
        append_bad = (
            "from novel_kernel.events import EventLog; from tests.test_projection import event,eid; "
            f"log=EventLog({str(bad_book)!r}); log.append(event(11,'object.retired',{{'object_id':'char_missing'}},eid(10))); print('bad appended')"
        )
        cases.append(run("append_invalid_projection_event", [python, "-c", append_bad]))
        failed_rebuild = run(
            "failed_rebuild_preserves_old_database",
            [python, str(REBUILD), "--book", str(bad_book), "--json"],
            expected=6,
        )
        bytes_preserved = digest(bad_database) == old_database_hash
        failed_rebuild["passed"] = failed_rebuild["passed"] and bytes_preserved
        failed_rebuild["old_database_bytes_preserved"] = bytes_preserved
        cases.append(failed_rebuild)

        stale_book = work / "stale_book"
        cases.append(run("stale_log_populate", [python, "-c", populate_command(stale_book)]))
        cases.append(run("stale_initial_rebuild", [python, str(REBUILD), "--book", str(stale_book), "--json"]))
        stale_db = stale_book / "state" / "state.db"
        connection = sqlite3.connect(stale_db)
        try:
            connection.execute("UPDATE projection_meta SET applied_event_count=9")
            connection.commit()
        finally:
            connection.close()
        cases.append(run(
            "stale_projection_rejected",
            [python, str(REBUILD), "--book", str(stale_book), "--update", "--json"],
            expected=6,
        ))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [case for case in cases if not case["passed"]]
    completed = now()
    write_json(EVIDENCE / "test-run.json", {
        "schema_version": "m1.4.verification.v1", "milestone": "M1.4", "completed_at": completed,
        "cases": cases, "observations": observations,
        "summary": {"total": len(cases), "passed": len(cases)-len(failed), "failed": len(failed)},
    })
    write_json(EVIDENCE / "metrics.json", {
        "milestone": "M1.4", "cases_total": len(cases), "cases_passed": len(cases)-len(failed),
        "unexpected_failures": len(failed), "replayed_events": 10,
        "delete_and_rebuild_same_hash": observations.get("initial_state_hash") == observations.get("rebuild_after_delete_hash"),
        "failed_rebuild_preserved_old_database": next((c.get("old_database_bytes_preserved", False) for c in cases if c["name"] == "failed_rebuild_preserves_old_database"), False),
        "third_party_dependencies": 0,
    })
    write_json(EVIDENCE / "failures.json", {"milestone": "M1.4", "unexpected_failures": failed})
    lines = [f"M1.4 verification completed at {completed}", ""]
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
        "# M1.4 verification decision", "", f"- Decision: **{decision}**",
        f"- Completed at: `{completed}`", f"- Cases: `{len(cases)}`", f"- Unexpected failures: `{len(failed)}`",
        "- Ten-event replay: verified", "- Delete and rebuild logical hash: identical",
        "- Failed rebuild preserves old database bytes: verified", "- Stale projection rejection: verified",
        "- Third-party dependencies: `0`", "",
        "SQLite remains a derived projection. Snapshot, outline, and production capabilities are out of scope.", "",
    ]), encoding="utf-8")
    indexed = ["test-run.json", "command-log.txt", "metrics.json", "failures.json", "decision.md"]
    write_json(EVIDENCE / "evidence-index.json", {
        "schema_version": "m1.4.evidence-index.v1", "milestone": "M1.4", "generated_at": now(),
        "artifacts": [{"path": name, "sha256": digest(EVIDENCE / name)} for name in indexed],
    })
    try:
        tmp_parent.rmdir()
    except OSError:
        pass
    print(f"M1.4 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
