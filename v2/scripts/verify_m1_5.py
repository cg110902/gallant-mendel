#!/usr/bin/env python3
"""Black-box verification for M1.5 snapshot creation and restore."""

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
EVIDENCE = ROOT / "verification" / "M1.5"
SNAPSHOT_CLI = ROOT / "scripts" / "snapshot.py"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str, command: list[str], expected: int = 0) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {"name": name, "command": command, "expected_exit_code": expected, "actual_exit_code": result.returncode,
            "passed": result.returncode == expected, "duration_seconds": round(time.monotonic()-started, 6),
            "stdout": result.stdout, "stderr": result.stderr}


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
        prepare = (
            "from pathlib import Path; from novel_kernel.events import EventLog; from novel_kernel.projection import ProjectionStore; "
            "from tests.test_projection import ten_event_sequence; "
            f"b=Path({str(book)!r}); log=EventLog(b); log.append_many(ten_event_sequence()); "
            "ProjectionStore(b).rebuild(log); p=b/'chapters'/'ch_001.md'; p.parent.mkdir(parents=True); "
            "p.write_text('# 第一章\\n\\n凌云走入山门。\\n',encoding='utf-8'); print('ready')"
        )
        cases.append(run("prepare_book", [python, "-c", prepare]))
        created = run("snapshot_create_cli", [python, str(SNAPSHOT_CLI), "create", "--book", str(book),
                       "--label", "m1.5-blackbox", "--artifact", "chapters/ch_001.md", "--json"])
        snapshot_path: Path | None = None
        if created["passed"]:
            value = json.loads(created["stdout"])
            created["passed"] = value["ok"] and value["lineage_event_count"] == 10 and value["artifact_count"] == 1
            snapshot_path = Path(value["path"])
            observations["snapshot_id"] = value["snapshot_id"]
            observations["state_hash"] = value["projection_state_hash"]
        cases.append(created)
        if snapshot_path is None:
            raise RuntimeError("snapshot create prerequisite failed")
        cases.append(run("snapshot_validate_cli", [python, str(SNAPSHOT_CLI), "validate", "--snapshot", str(snapshot_path), "--json"]))
        target = work / "restored"
        restored = run("snapshot_restore_cli", [python, str(SNAPSHOT_CLI), "restore", "--snapshot", str(snapshot_path),
                        "--target", str(target), "--json"])
        if restored["passed"]:
            value = json.loads(restored["stdout"])
            restored["passed"] = value["projection_state_hash"] == observations["state_hash"]
        cases.append(restored)
        verify_restore = (
            "from pathlib import Path; from novel_kernel.events import EventLog; from novel_kernel.projection import ProjectionStore; "
            f"b=Path({str(target)!r}); log=EventLog(b); r=ProjectionStore(b).verify(log); "
            "assert len(log.read_events())==10; assert (b/'chapters'/'ch_001.md').is_file(); print(r.state_hash)"
        )
        cases.append(run("restored_book_verify", [python, "-c", verify_restore]))

        tamper_target = snapshot_path / "artifacts" / "files" / "chapters" / "ch_001.md"
        tamper_target.write_text("tampered", encoding="utf-8")
        cases.append(run("tampered_snapshot_rejected", [python, str(SNAPSHOT_CLI), "validate", "--snapshot",
                                                         str(snapshot_path), "--json"], expected=6))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [case for case in cases if not case["passed"]]
    completed = now()
    write_json(EVIDENCE/"test-run.json", {"schema_version":"m1.5.verification.v1","milestone":"M1.5",
        "completed_at":completed,"cases":cases,"observations":observations,
        "summary":{"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}})
    write_json(EVIDENCE/"metrics.json", {"milestone":"M1.5","cases_total":len(cases),
        "cases_passed":len(cases)-len(failed),"unexpected_failures":len(failed),
        "snapshot_restore_same_state_hash":next((c["passed"] for c in cases if c["name"]=="snapshot_restore_cli"),False),
        "tamper_rejected":next((c["passed"] for c in cases if c["name"]=="tampered_snapshot_rejected"),False),
        "third_party_dependencies":0})
    write_json(EVIDENCE/"failures.json", {"milestone":"M1.5","unexpected_failures":failed})
    lines=[f"M1.5 verification completed at {completed}",""]
    for case in cases:
        lines += [f"[{case['name']}]",f"command: {' '.join(case['command'])}",
                  f"expected_exit_code: {case['expected_exit_code']}",f"actual_exit_code: {case['actual_exit_code']}",
                  f"result: {'PASS' if case['passed'] else 'FAIL'}","stdout:",case["stdout"].rstrip(),
                  "stderr:",case["stderr"].rstrip(),""]
    (EVIDENCE/"command-log.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    decision="PASS" if not failed else "FAIL"
    (EVIDENCE/"decision.md").write_text("\n".join(["# M1.5 verification decision","",f"- Decision: **{decision}**",
        f"- Completed at: `{completed}`",f"- Cases: `{len(cases)}`",f"- Unexpected failures: `{len(failed)}`",
        "- Snapshot create/validate/restore: verified","- Artifact tamper rejection: verified",
        "- Non-destructive target policy: covered by unit tests","- Third-party dependencies: `0`","",
        "M1 scale acceptance is recorded separately in verification/M1/.",""]),encoding="utf-8")
    indexed=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"]
    write_json(EVIDENCE/"evidence-index.json", {"schema_version":"m1.5.evidence-index.v1","milestone":"M1.5",
        "generated_at":now(),"artifacts":[{"path":n,"sha256":digest(EVIDENCE/n)} for n in indexed]})
    try: tmp_parent.rmdir()
    except OSError: pass
    print(f"M1.5 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1

if __name__ == "__main__":
    raise SystemExit(main())
