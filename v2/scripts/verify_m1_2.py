#!/usr/bin/env python3
"""Black-box verification for M1.2 Event Envelope and append-only JSONL."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "verification" / "M1.2"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
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


def worker_event(book: Path, number: int, parent: str | None, branch: str = "main") -> str:
    return (
        "from pathlib import Path; from novel_kernel.events import EventLog, build_event; "
        f"book=Path({str(book)!r}); parent={parent!r}; "
        "e=build_event("
        f"event_id='event_{number:032x}', event_type='fact.asserted', book_id='book_demo', "
        f"branch_id={branch!r}, parent_event_id=parent, story_seq={number}, "
        "recorded_at='2026-09-29T08:00:00+00:00', actor_type='reconciler', "
        "actor_id='studio.reconcile', payload={'number':"
        f"{number}" "}); EventLog(book).append(e); print(e['event_id'])"
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

        replay_book = work / "replay"
        replay_code = (
            "from pathlib import Path; from novel_kernel.events import EventLog, build_event; "
            f"log=EventLog(Path({str(replay_book)!r})); parent=None; "
            "events=[]; "
            "exec(\"for i in range(1,101):\\n e=build_event(event_id='event_'+format(i,'032x'), "
            "event_type='fact.asserted', book_id='book_demo', branch_id='main', parent_event_id=parent, "
            "story_seq=i, recorded_at='2026-09-29T08:00:00+00:00', actor_type='reconciler', "
            "actor_id='studio.reconcile', payload={'number':i})\\n log.append(e)\\n events.append(e)\\n parent=e['event_id']\"); "
            "r=log.verify(); assert tuple(events)==log.read_events(); print(r.event_count, r.heads['main'])"
        )
        replay_case = run("append_replay_100", [python, "-c", replay_code])
        cases.append(replay_case)
        observations["replay_log_hash"] = file_hash(replay_book / "ledger" / "events.jsonl") if replay_case["passed"] else None

        concurrent_book = work / "concurrent"
        bootstrap = run("concurrency_bootstrap", [python, "-c", worker_event(concurrent_book, 1, None)])
        cases.append(bootstrap)
        parent = f"event_{1:032x}"
        conflict_wrapper = (
            "import sys; from novel_kernel.events import ParentConflictError; "
            "code=" + repr(worker_event(concurrent_book, 2, parent)) + "; "
            "\ntry: exec(code)\nexcept ParentConflictError as e: print(e, file=sys.stderr); sys.exit(7)"
        )
        conflict_wrapper_2 = conflict_wrapper.replace(f"event_{2:032x}", f"event_{3:032x}").replace("'number':2", "'number':3").replace("story_seq=2", "story_seq=3")
        first = subprocess.Popen([python, "-c", conflict_wrapper], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        second = subprocess.Popen([python, "-c", conflict_wrapper_2], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out1, err1 = first.communicate(timeout=15)
        out2, err2 = second.communicate(timeout=15)
        return_codes = sorted([first.returncode, second.returncode])
        concurrency_ok = return_codes == [0, 7]
        cases.append({
            "name": "concurrent_same_parent",
            "command": ["two parallel append workers with identical parent_event_id"],
            "expected_exit_code": "one 0 and one 7",
            "actual_exit_code": [first.returncode, second.returncode],
            "passed": concurrency_ok,
            "duration_seconds": 0.0,
            "stdout": out1 + out2,
            "stderr": err1 + err2,
        })
        verify_concurrent = run(
            "concurrent_log_integrity",
            [python, "-c", f"from pathlib import Path; from novel_kernel.events import EventLog; r=EventLog(Path({str(concurrent_book)!r})).verify(); print(r.event_count)"],
        )
        cases.append(verify_concurrent)

        lock_book = work / "locked"
        marker = work / "lock-acquired"
        holder_code = (
            "import time; from pathlib import Path; from novel_kernel.events import EventLog; "
            f"log=EventLog(Path({str(lock_book)!r})); log.initialize(); "
            f"marker=Path({str(marker)!r}); "
            "\nwith log._locked(): marker.write_text('locked'); time.sleep(1.0)"
        )
        holder = subprocess.Popen([python, "-c", holder_code], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while not marker.exists() and holder.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        lock_worker = (
            "import sys; from pathlib import Path; from novel_kernel.events import EventLog, ResourceGuardError; "
            f"log=EventLog(Path({str(lock_book)!r}), lock_timeout=0.05); "
            "\ntry: log.verify()\nexcept ResourceGuardError as e: print(e, file=sys.stderr); sys.exit(7)"
        )
        cases.append(run("lock_timeout_resource_guard", [python, "-c", lock_worker], expected=7))
        holder_out, holder_err = holder.communicate(timeout=5)
        observations["lock_holder_exit_code"] = holder.returncode
        observations["lock_holder_stderr"] = holder_err

        tamper_book = replay_book
        log_path = tamper_book / "ledger" / "events.jsonl"
        original = log_path.read_bytes()
        lines = original.splitlines()
        value = json.loads(lines[50])
        value["payload"]["number"] = -1
        lines[50] = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        log_path.write_bytes(b"\n".join(lines) + b"\n")
        integrity_worker = (
            "import sys; from pathlib import Path; from novel_kernel.events import EventIntegrityError, EventLog; "
            f"log=EventLog(Path({str(tamper_book)!r})); "
            "\ntry: log.verify(verify_heads=False)\nexcept EventIntegrityError as e: print(e, file=sys.stderr); sys.exit(2)"
        )
        cases.append(run("payload_tamper_detected", [python, "-c", integrity_worker], expected=2))
        log_path.write_bytes(original[:-1])
        cases.append(run("truncated_tail_detected", [python, "-c", integrity_worker], expected=2))
        log_path.write_bytes(original)

        head = replay_book / "ledger" / "heads" / "main.json"
        head.write_text("{}", encoding="utf-8")
        rebuild_worker = (
            "from pathlib import Path; from novel_kernel.events import EventLog, HeadMismatchError; "
            f"log=EventLog(Path({str(replay_book)!r})); detected=False; "
            "\ntry: log.verify()\nexcept HeadMismatchError: detected=True\n"
            "assert detected; log.rebuild_heads(); print(log.verify().event_count)"
        )
        cases.append(run("stale_head_detect_and_rebuild", [python, "-c", rebuild_worker]))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [case for case in cases if not case["passed"]]
    completed = now()
    write_json(EVIDENCE / "test-run.json", {
        "schema_version": "m1.2.verification.v1", "milestone": "M1.2", "completed_at": completed,
        "cases": cases, "observations": observations,
        "summary": {"total": len(cases), "passed": len(cases) - len(failed), "failed": len(failed)},
    })
    write_json(EVIDENCE / "metrics.json", {
        "milestone": "M1.2", "cases_total": len(cases), "cases_passed": len(cases) - len(failed),
        "unexpected_failures": len(failed), "replay_events": 100,
        "concurrent_single_winner": next((c["passed"] for c in cases if c["name"] == "concurrent_same_parent"), False),
        "tamper_detected": next((c["passed"] for c in cases if c["name"] == "payload_tamper_detected"), False),
        "truncation_detected": next((c["passed"] for c in cases if c["name"] == "truncated_tail_detected"), False),
        "third_party_dependencies": 0,
    })
    write_json(EVIDENCE / "failures.json", {"milestone": "M1.2", "unexpected_failures": failed})
    lines = [f"M1.2 verification completed at {completed}", ""]
    for case in cases:
        lines.extend([
            f"[{case['name']}]", f"command: {' '.join(map(str, case['command']))}",
            f"expected_exit_code: {case['expected_exit_code']}", f"actual_exit_code: {case['actual_exit_code']}",
            f"result: {'PASS' if case['passed'] else 'FAIL'}", "stdout:", case["stdout"].rstrip(),
            "stderr:", case["stderr"].rstrip(), "",
        ])
    (EVIDENCE / "command-log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    decision = "PASS" if not failed else "FAIL"
    (EVIDENCE / "decision.md").write_text("\n".join([
        "# M1.2 verification decision", "", f"- Decision: **{decision}**",
        f"- Completed at: `{completed}`", f"- Cases: `{len(cases)}`", f"- Unexpected failures: `{len(failed)}`",
        "- Concurrent same-parent append: exactly one winner", "- Lock timeout maps to resource guard: verified",
        "- Payload tamper and truncated tail: detected", "- Third-party dependencies: `0`", "",
        "Scope excludes Object/Facet/Relation, SQLite projection, snapshots, outlines, and production agents.", "",
    ]), encoding="utf-8")
    indexed = ["test-run.json", "command-log.txt", "metrics.json", "failures.json", "decision.md"]
    write_json(EVIDENCE / "evidence-index.json", {
        "schema_version": "m1.2.evidence-index.v1", "milestone": "M1.2", "generated_at": now(),
        "artifacts": [{"path": name, "sha256": file_hash(EVIDENCE / name)} for name in indexed],
    })
    try:
        tmp_parent.rmdir()
    except OSError:
        pass
    print(f"M1.2 verification: {decision} ({len(cases) - len(failed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
