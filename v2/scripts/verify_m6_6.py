#!/usr/bin/env python3
"""Black-box acceptance for M6.6 three-chapter recovery smoke."""
from __future__ import annotations
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from novel_kernel.storage import atomic_write_json,sha256_file,sha256_json
from novel_kernel.three_chapter_smoke import ThreeChapterSmoke
from tests.test_three_chapter_smoke import ThreeChapterSmokeTests,THRESHOLDS

E=ROOT/"verification"/"M6.6"
E.mkdir(parents=True,exist_ok=True)
cases=[]
def check(name,condition,detail=""):
 cases.append({"name":name,"passed":bool(condition),"detail":detail})

test=ThreeChapterSmokeTests(methodName="test_three_chapter_restore_and_interrupted_commit_have_no_silent_loss")
try:
 test.setUp()
 report_path=E/"three-chapter-smoke-report.json"
 restored=test.root/"recovered"/"book_demo"
 report=ThreeChapterSmoke().run(test.book,thresholds_path=THRESHOLDS,evaluated_at="2026-09-30T00:00:00+00:00",prose_by_chapter=test._prose(),interrupt=test._interrupt_after_prefix,restore_target=restored,report_path=report_path)
 doc=json.loads(report_path.read_text())
 base={k:v for k,v in doc.items() if k!="report_hash"}
 check("three_chapters_published",report.ok and doc["chapter_count"]==3)
 check("authority_parent_head_contiguous",doc["loss_checks"]["authority_chain_contiguous"])
 check("authority_event_count_conserved",doc["loss_checks"]["authority_count_conserved"])
 check("chapter_count_and_ids_conserved",doc["loss_checks"]["chapter_count_conserved"] and doc["loss_checks"]["chapter_ids_conserved"])
 check("facts_conserved",doc["loss_checks"]["fact_count_conserved"] and doc["loss_checks"]["projection_facts_conserved"])
 check("projection_head_conserved",doc["loss_checks"]["projection_head_conserved"])
 check("run_receipts_conserved",doc["loss_checks"]["run_receipts_conserved"])
 check("snapshot_restored_before_chapter_three",doc["snapshot"]["restored_before_chapter_three"] and doc["snapshot"]["lineage_event_count"]<doc["authority_event_count"])
 check("journal_prefix_interruption_observed",doc["transaction_recovery"]["interruption_injected"] and doc["transaction_recovery"]["interruption_observed"])
 check("journal_retry_recovered",doc["transaction_recovery"]["recovered"])
 check("no_silent_data_loss",doc["silent_data_loss"] is False and all(doc["loss_checks"].values()))
 check("fixed_three_chapter_ced",doc["ced"]["window_size"]==3 and doc["ced"]["start"]=="ch_001" and doc["ced"]["end"]=="ch_003")
 check("ced_zero_for_control_window",doc["ced"]["error_count"]==0 and doc["ced"]["density"]==0)
 check("advisory_evidence_excluded_from_ced",doc["ced"]["advisory_findings_excluded"]>=1)
 check("report_hash_valid",doc["report_hash"]==sha256_json(base))
 check("challenge_false_negatives_unchanged",doc["scope"]["challenge_false_negatives_changed"] is False)
 check("hard_gate_not_promoted",doc["scope"]["hard_gate_promoted"] is False)
 challenge=json.loads((ROOT/"calibration"/"challenge-v1"/"soft-challenge-report.v1.json").read_text())
 totals=challenge["totals"]
 check("challenge_receipt_still_9_fn",totals=={"fn":9,"fp":0,"tn":18,"tp":9},str(totals))
 check("threshold_bundle_hash_unchanged",json.loads(THRESHOLDS.read_text())["bundle_hash"]=="sha256:c7f35608853f6a784df4ddf59e2c7b01449e4f23e2829e67650b55a1aee0963e")
 check("schema_present_and_parseable",json.loads((ROOT/"schemas"/"three-chapter-smoke-report.v1.schema.json").read_text())["title"]=="M6.6 three-chapter smoke report")
finally:
 test.tearDown()

failed=[case for case in cases if not case["passed"]]
completed=datetime.now(timezone.utc).isoformat()
summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}
atomic_write_json(E/"test-run.json",{"schema_version":"m6.6.verification.v1","milestone":"M6.6","completed_at":completed,"cases":cases,"summary":summary})
atomic_write_json(E/"metrics.json",{"milestone":"M6.6","chapter_count":3,"ced_window_size":3,"ced_error_count":doc["ced"]["error_count"],"ced_density":doc["ced"]["density"],"advisory_findings":doc["ced"]["advisory_findings_excluded"],"authority_event_count":doc["authority_event_count"],"fact_count":doc["fact_count"],"interruption_recovered":doc["transaction_recovery"]["recovered"],"silent_data_loss":doc["silent_data_loss"],"cases":summary})
atomic_write_json(E/"failures.json",{"milestone":"M6.6","unexpected_failures":failed})
(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {'PASS' if c['passed'] else 'FAIL'} {c['detail']}" for c in cases)+"\n")
(E/"decision.md").write_text(f"# M6.6 decision\n\n- Decision: **{'PASS' if not failed else 'FAIL'}**\n- Cases: **{summary['passed']}/{summary['total']} PASS**\n- Three contiguous authority commits completed across a verified chapter-two snapshot restore\n- Deterministic commit-prefix interruption recovered without silent data loss\n- Fixed ch_001..ch_003 CED is {doc['ced']['density']} ({doc['ced']['error_count']} hard errors / 3 chapters)\n- Advisory findings remain excluded from CED and non-blocking\n- Challenge FN=9 and frozen threshold bundle remain unchanged\n- Scope is a controlled three-chapter smoke, not a production-reliability claim\n")
files=["three-chapter-smoke-report.json","test-run.json","metrics.json","failures.json","command-log.txt","decision.md"]
atomic_write_json(E/"evidence-index.json",{"schema_version":"evidence-index.v1","milestone":"M6.6","files":[{"path":name,"sha256":sha256_file(E/name)} for name in files]})
print(f"M6.6 {'PASS' if not failed else 'FAIL'}: {summary['passed']}/{summary['total']}")
raise SystemExit(0 if not failed else 1)
