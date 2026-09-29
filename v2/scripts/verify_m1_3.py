#!/usr/bin/env python3
"""Black-box verification for M1.3 versioned object models."""

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
EVIDENCE = ROOT / "verification" / "M1.3"
EVENT = "event_00000000000000000000000000000001"


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


def valid_bundle() -> dict[str, Any]:
    character = {
        "object_id": "char_lin_yun", "type": "character", "canonical_name": "凌云",
        "aliases": ["云舟"], "status": "active", "created_event": EVENT, "supersedes": None,
    }
    place = {
        "object_id": "place_sword_sect", "type": "place", "canonical_name": "剑宗",
        "aliases": [], "status": "active", "created_event": EVENT, "supersedes": None,
    }
    evidence = {
        "evidence_id": "evidence_ch001_p1", "source_type": "chapter",
        "source_ref": "chapters/ch_001.md", "locator": {"start": 0, "end": 12, "section": "p1"},
        "content_hash": "sha256:" + hashlib.sha256("凌云走进山门".encode()).hexdigest(),
        "excerpt": "凌云走进山门", "recorded_event": EVENT,
    }
    fact = {
        "fact_id": "fact_lin_identity", "subject_id": "char_lin_yun", "predicate": "true_identity",
        "value": "剑宗遗孤", "valid_from": "story:0001-01-01T00:00", "valid_to": None,
        "recorded_event": EVENT, "confidence": "confirmed", "status": "asserted",
        "evidence_refs": ["evidence_ch001_p1"],
    }
    relation = {
        "relation_id": "rel_lin_knows_identity", "subject_id": "char_lin_yun", "predicate": "knows",
        "object_id": "fact_lin_identity", "valid_from": "story:0007-06-03T10:00", "valid_to": None,
        "recorded_event": EVENT, "confidence": "confirmed", "evidence_refs": ["evidence_ch001_p1"],
    }
    facets = [
        {"object_id": "char_lin_yun", "facet_type": "knowledge", "facet_version": 1,
         "payload": {"fact_ids": ["fact_lin_identity"]}, "valid_from": "story:0001", "valid_to": None,
         "source_refs": ["outline/cast.json#char_lin_yun"], "recorded_event": EVENT},
        {"object_id": "char_lin_yun", "facet_type": "location", "facet_version": 1,
         "payload": {"place_id": "place_sword_sect"}, "valid_from": "story:0001", "valid_to": None,
         "source_refs": ["outline/cast.json#char_lin_yun"], "recorded_event": EVENT},
        {"object_id": "char_lin_yun", "facet_type": "relationship", "facet_version": 1,
         "payload": {"relation_ids": ["rel_lin_knows_identity"]}, "valid_from": "story:0001", "valid_to": None,
         "source_refs": ["outline/cast.json#char_lin_yun"], "recorded_event": EVENT},
    ]
    return {"objects": [character, place], "facets": facets, "relations": [relation], "facts": [fact], "evidence": [evidence]}


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
        bundle_path = work / "bundle.json"
        write_json(bundle_path, valid_bundle())
        bundle_worker = (
            "import json; from pathlib import Path; from novel_kernel.objects import validate_model_bundle; "
            f"v=json.loads(Path({str(bundle_path)!r}).read_text()); r=validate_model_bundle(**v); "
            "print(len(r.objects),len(r.facets),len(r.relations),len(r.facts),len(r.evidence))"
        )
        valid_case = run("valid_unicode_bundle", [python, "-c", bundle_worker])
        cases.append(valid_case)
        observations["valid_bundle_hash"] = digest(bundle_path)

        facet_worker = (
            "from novel_kernel.objects import validate_facet; E='" + EVENT + "'; "
            "p={'identity':{'identity_kind':'human'},'appearance':{'description':'黑衣'},"
            "'psychology':{'current_motive':'真相','want':'真相','fear':'背叛'},"
            "'capability':{'capabilities':['剑术']},'voice':{'style_markers':['寡言']},"
            "'knowledge':{'fact_ids':[]},'resource':{'resources':{'coin':1}},"
            "'location':{'place_id':'place_sword_sect'},'relationship':{'relation_ids':[]},"
            "'status':{'state':'active'},'arc':{'stage':'setup'},'style':{'directives':['短句']},"
            "'constraint':{'rules':['不泄密']}}; "
            "[validate_facet({'object_id':'char_lin_yun','facet_type':k,'facet_version':1,'payload':v,"
            "'valid_from':'story:0001','valid_to':None,'source_refs':['fixture#1'],'recorded_event':E}) "
            "for k,v in p.items()]; print(len(p))"
        )
        cases.append(run("all_13_facet_schemas", [python, "-c", facet_worker]))

        malformed_worker = (
            "import sys; from novel_kernel.objects import ModelValidationError, validate_object; "
            "v={'object_id':'char_x','type':'character','canonical_name':'X','aliases':[],'status':'active',"
            "'created_event':'" + EVENT + "','supersedes':None,'invented':1}; "
            "\ntry: validate_object(v)\nexcept ModelValidationError as e: print(e,file=sys.stderr);sys.exit(2)"
        )
        cases.append(run("unknown_field_rejected", [python, "-c", malformed_worker], expected=2))

        dangling = valid_bundle()
        dangling["relations"][0]["evidence_refs"] = ["evidence_missing"]
        dangling_path = work / "dangling.json"
        write_json(dangling_path, dangling)
        dangling_worker = (
            "import json,sys; from pathlib import Path; from novel_kernel.objects import ReferenceIntegrityError,validate_model_bundle; "
            f"v=json.loads(Path({str(dangling_path)!r}).read_text()); "
            "\ntry: validate_model_bundle(**v)\nexcept ReferenceIntegrityError as e: print(e,file=sys.stderr);sys.exit(3)"
        )
        cases.append(run("dangling_evidence_rejected", [python, "-c", dangling_worker], expected=3))

        schema_worker = (
            "import json; from pathlib import Path; p=Path('schemas'); "
            "names=['object','facet','relation','fact','evidence']; "
            "values=[json.loads((p/f'{n}.schema.json').read_text()) for n in names]; "
            "assert all(v['additionalProperties'] is False for v in values); print(len(values))"
        )
        cases.append(run("schema_artifacts_parse", [python, "-c", schema_worker]))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [case for case in cases if not case["passed"]]
    completed = now()
    write_json(EVIDENCE / "test-run.json", {
        "schema_version": "m1.3.verification.v1", "milestone": "M1.3", "completed_at": completed,
        "cases": cases, "observations": observations,
        "summary": {"total": len(cases), "passed": len(cases) - len(failed), "failed": len(failed)},
    })
    write_json(EVIDENCE / "metrics.json", {
        "milestone": "M1.3", "cases_total": len(cases), "cases_passed": len(cases)-len(failed),
        "unexpected_failures": len(failed), "facet_schemas": 13, "model_schemas": 5,
        "dangling_reference_rejected": next((c["passed"] for c in cases if c["name"] == "dangling_evidence_rejected"), False),
        "third_party_dependencies": 0,
    })
    write_json(EVIDENCE / "failures.json", {"milestone": "M1.3", "unexpected_failures": failed})
    lines = [f"M1.3 verification completed at {completed}", ""]
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
        "# M1.3 verification decision", "", f"- Decision: **{decision}**",
        f"- Completed at: `{completed}`", f"- Cases: `{len(cases)}`", f"- Unexpected failures: `{len(failed)}`",
        "- Versioned model schemas: `5`", "- Frozen Facet v1 payload schemas: `13`",
        "- Dangling evidence reference rejection: verified", "- Third-party dependencies: `0`", "",
        "Scope is validation and in-memory reference integrity only. SQLite projection, event",
        "application, snapshots, outlines, and production agents remain unimplemented.", "",
    ]), encoding="utf-8")
    indexed = ["test-run.json", "command-log.txt", "metrics.json", "failures.json", "decision.md"]
    write_json(EVIDENCE / "evidence-index.json", {
        "schema_version": "m1.3.evidence-index.v1", "milestone": "M1.3", "generated_at": now(),
        "artifacts": [{"path": name, "sha256": digest(EVIDENCE / name)} for name in indexed],
    })
    try:
        tmp_parent.rmdir()
    except OSError:
        pass
    print(f"M1.3 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)")
    print(f"Evidence: {EVIDENCE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
