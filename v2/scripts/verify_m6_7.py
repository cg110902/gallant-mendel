#!/usr/bin/env python3
"""Acceptance evidence for the M6.7 controlled thirty-chapter soak."""
from __future__ import annotations
import json,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from novel_kernel.storage import atomic_write_json,sha256_file,sha256_json
from novel_kernel.thirty_chapter_soak import ThirtyChapterSoak
from tests.test_thirty_chapter_soak import ThirtyChapterSoakTests,THRESHOLDS
E=ROOT/"verification"/"M6.7";E.mkdir(parents=True,exist_ok=True);cases=[]
def check(name,condition,detail=""):cases.append({"name":name,"passed":bool(condition),"detail":detail})
test=ThirtyChapterSoakTests(methodName="test_thirty_chapter_soak_survives_outage_and_commit_interruption")
try:
 test.setUp();path=E/"thirty-chapter-soak-report.json"
 report=ThirtyChapterSoak().run(test.book,thresholds_path=THRESHOLDS,evaluated_at="2026-09-30T00:00:00+00:00",prose_for_chapter=test.prose,restore_target=test.root/"recovered"/"book_demo",interrupt=test.interrupt_after_prefix,report_path=path)
 doc=json.loads(path.read_text());base={k:v for k,v in doc.items() if k!="report_hash"}
 check("thirty_chapters_completed",report.ok and doc["chapter_count"]==30)
 check("authority_count_conserved",doc["loss_checks"]["authority_count_conserved"])
 check("authority_chain_contiguous",doc["loss_checks"]["authority_chain_contiguous"])
 check("chapter_count_and_ids_conserved",doc["loss_checks"]["chapter_count_conserved"] and doc["loss_checks"]["chapter_ids_conserved"])
 check("chapter_hashes_conserved",doc["loss_checks"]["chapter_hashes_conserved"])
 check("facts_conserved",doc["loss_checks"]["fact_count_conserved"] and doc["loss_checks"]["projection_facts_conserved"])
 check("projection_head_conserved",doc["loss_checks"]["projection_head_conserved"])
 check("run_receipts_conserved",doc["loss_checks"]["run_receipts_conserved"])
 check("snapshot_heads_conserved",doc["loss_checks"]["snapshot_heads_conserved"])
 check("chapter_ten_outage_restored",doc["outage_recovery"]["restored_to_empty_target"] and doc["outage_recovery"]["continued"])
 check("chapter_twenty_interruption_recovered",doc["transaction_recovery"]["interruption_observed"] and doc["transaction_recovery"]["recovered"])
 check("two_verified_snapshots",doc["snapshot_count"]==2 and [x["after_chapter"] for x in doc["snapshots"]]==["ch_010","ch_020"])
 check("three_fixed_ced_windows",doc["ced"]["window_size"]==10 and len(doc["ced"]["windows"])==3)
 check("control_ced_is_zero",doc["ced"]["total_error_count"]==0 and doc["ced"]["overall_density"]==0)
 check("advisories_excluded_from_ced",doc["ced"]["advisory_findings_excluded"]>=3)
 check("no_silent_data_loss",doc["silent_data_loss"] is False and all(doc["loss_checks"].values()))
 check("report_hash_valid",doc["report_hash"]==sha256_json(base))
 check("no_performance_threshold",doc["scope"]["performance_threshold_applied"] is False)
 check("concurrency_not_claimed",doc["scope"]["concurrent_writers_tested"] is False)
 challenge=json.loads((ROOT/"calibration"/"challenge-v1"/"soft-challenge-report.v1.json").read_text())
 check("challenge_nine_fn_unchanged",challenge["totals"]=={"fn":9,"fp":0,"tn":18,"tp":9})
 check("hard_gate_not_promoted",doc["scope"]["hard_gate_promoted"] is False)
 check("threshold_bundle_unchanged",json.loads(THRESHOLDS.read_text())["bundle_hash"]=="sha256:c7f35608853f6a784df4ddf59e2c7b01449e4f23e2829e67650b55a1aee0963e")
 check("schema_parseable",json.loads((ROOT/"schemas"/"thirty-chapter-soak-report.v1.schema.json").read_text())["title"].startswith("M6.7"))
finally:test.tearDown()
failed=[x for x in cases if not x["passed"]];summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)};now=datetime.now(timezone.utc).isoformat()
atomic_write_json(E/"test-run.json",{"schema_version":"m6.7.verification.v1","milestone":"M6.7","completed_at":now,"cases":cases,"summary":summary})
atomic_write_json(E/"metrics.json",{"milestone":"M6.7","chapter_count":30,"authority_event_count":doc["authority_event_count"],"fact_count":doc["fact_count"],"snapshot_count":doc["snapshot_count"],"ced_windows":doc["ced"]["windows"],"ced_overall_density":doc["ced"]["overall_density"],"advisory_findings":doc["ced"]["advisory_findings_excluded"],"elapsed_seconds_observed":doc["elapsed_seconds_observed"],"silent_data_loss":doc["silent_data_loss"],"cases":summary})
atomic_write_json(E/"failures.json",{"milestone":"M6.7","unexpected_failures":failed})
(E/"command-log.txt").write_text("\n".join(f"[{x['name']}] {'PASS' if x['passed'] else 'FAIL'} {x['detail']}" for x in cases)+"\n")
(E/"decision.md").write_text(f"# M6.7 decision\n\n- Decision: **{'PASS' if not failed else 'FAIL'}**\n- Cases: **{summary['passed']}/{summary['total']} PASS**\n- Controlled sequential chapters: 30\n- Verified snapshots: 2; chapter-ten restore continued through chapter 30\n- Chapter-twenty commit-prefix interruption recovered\n- Three fixed ten-chapter CED windows: 0 hard errors; advisory findings excluded\n- Silent data loss: false\n- Elapsed {doc['elapsed_seconds_observed']:.3f}s is observational only, not a performance threshold\n- Concurrency and production reliability are not claimed\n")
files=["thirty-chapter-soak-report.json","test-run.json","metrics.json","failures.json","command-log.txt","decision.md"]
atomic_write_json(E/"evidence-index.json",{"schema_version":"evidence-index.v1","milestone":"M6.7","files":[{"path":name,"sha256":sha256_file(E/name)} for name in files]})
print(f"M6.7 {'PASS' if not failed else 'FAIL'}: {summary['passed']}/{summary['total']}");raise SystemExit(0 if not failed else 1)
