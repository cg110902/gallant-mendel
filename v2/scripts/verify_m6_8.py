#!/usr/bin/env python3
"""Acceptance evidence for M6.8 authority concurrency guards."""
from __future__ import annotations
import json,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from novel_kernel.chapter_commit import ChapterCommitter
from novel_kernel.concurrency_guard import ConcurrencyGuardProbe
from novel_kernel.events import EventLog,ParentConflictError,ResourceGuardError
from novel_kernel.production import ProductionResourceGuardError
from novel_kernel.storage import atomic_write_json,sha256_file,sha256_json
from tests import test_chapter_commit as fixture_module
E=ROOT/"verification"/"M6.8";E.mkdir(parents=True,exist_ok=True);cases=[]
def check(name,value,detail=""):cases.append({"name":name,"passed":bool(value),"detail":detail})
with tempfile.TemporaryDirectory() as temp:
 path=E/"concurrency-guard-report.json";report=ConcurrencyGuardProbe().run(Path(temp)/"book_concurrency",report_path=path);doc=json.loads(path.read_text());base={k:v for k,v in doc.items() if k!="report_hash"}
check("probe_passed",report.ok)
check("lock_timeout_is_exit_seven",doc["lock_contention"]["exit_code"]==7)
check("lock_timeout_preserves_authority",doc["lock_contention"]["authority_bytes_unchanged"])
check("exactly_one_race_winner",doc["same_parent_race"]["winner_count"]==1)
check("exactly_one_parent_conflict",doc["same_parent_race"]["conflict_count"]==1)
check("loser_exit_is_seven",[x["exit_code"] for x in doc["same_parent_race"]["outcomes"] if x["outcome"]=="parent_conflict"]==[7])
check("no_silent_overwrite",doc["silent_overwrite"] is False)
check("authority_contains_root_and_winner_only",doc["authority"]["event_count"]==2)
check("projection_matches_winner",doc["projection"]["head_matches_authority"])
check("report_hash_valid",doc["report_hash"]==sha256_json(base))
fixture=fixture_module.ChapterCommitTests(methodName="test_commit_is_idempotent");fixture.setUp()
try:
 try:
  with mock.patch.object(EventLog,"append_many",side_effect=ParentConflictError("injected same-parent race")):ChapterCommitter().commit(fixture.book,run_id=fixture.run_id,actor="human.editor")
  mapped=None
 except ProductionResourceGuardError as exc:mapped=exc
 status=json.loads((fixture.run/"status.json").read_text())
 check("chapter_commit_maps_race",mapped is not None)
 check("chapter_commit_exit_seven",mapped is not None and mapped.exit_code==7)
 check("chapter_not_published_on_race",not (fixture.book/"chapters"/"ch_001.md").exists())
 check("journal_stays_prepared",status["state"]=="commit_prepared")
finally:fixture.tearDown()
check("resource_error_contract",ResourceGuardError.exit_code==7 and ParentConflictError.exit_code==7 and ProductionResourceGuardError.exit_code==7)
check("single_process_scope_honest",doc["scope"]["single_process_threads"] and not doc["scope"]["multi_process_tested"])
check("distributed_lock_not_claimed",not doc["scope"]["distributed_lock_tested"])
check("throughput_not_claimed",not doc["scope"]["throughput_claim"])
challenge=json.loads((ROOT/"calibration"/"challenge-v1"/"soft-challenge-report.v1.json").read_text());check("challenge_nine_fn_unchanged",challenge["totals"]=={"fn":9,"fp":0,"tn":18,"tp":9})
check("schema_parseable",json.loads((ROOT/"schemas"/"concurrency-guard-report.v1.schema.json").read_text())["title"].startswith("M6.8"))
failed=[x for x in cases if not x["passed"]];summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)};now=datetime.now(timezone.utc).isoformat()
atomic_write_json(E/"test-run.json",{"schema_version":"m6.8.verification.v1","milestone":"M6.8","completed_at":now,"cases":cases,"summary":summary})
atomic_write_json(E/"metrics.json",{"milestone":"M6.8","winner_count":doc["same_parent_race"]["winner_count"],"conflict_count":doc["same_parent_race"]["conflict_count"],"lock_timeout_exit_code":doc["lock_contention"]["exit_code"],"parent_conflict_exit_code":7,"authority_event_count":doc["authority"]["event_count"],"silent_overwrite":doc["silent_overwrite"],"cases":summary})
atomic_write_json(E/"failures.json",{"milestone":"M6.8","unexpected_failures":failed})
(E/"command-log.txt").write_text("\n".join(f"[{x['name']}] {'PASS' if x['passed'] else 'FAIL'} {x['detail']}" for x in cases)+"\n")
(E/"decision.md").write_text(f"# M6.8 decision\n\n- Decision: **{'PASS' if not failed else 'FAIL'}**\n- Cases: **{summary['passed']}/{summary['total']} PASS**\n- Held-lock contender failed exit 7 without changing authority bytes\n- Same-parent race produced exactly one winner and one explicit exit-7 conflict\n- Chapter commit maps append-window contention to RESOURCE_GUARD and publishes no chapter\n- EventLog and projection end at the winning event; silent overwrite is false\n- Scope excludes multi-process, distributed locks, fairness, and throughput claims\n")
files=["concurrency-guard-report.json","test-run.json","metrics.json","failures.json","command-log.txt","decision.md"]
atomic_write_json(E/"evidence-index.json",{"schema_version":"evidence-index.v1","milestone":"M6.8","files":[{"path":n,"sha256":sha256_file(E/n)} for n in files]})
print(f"M6.8 {'PASS' if not failed else 'FAIL'}: {summary['passed']}/{summary['total']}");raise SystemExit(0 if not failed else 1)
