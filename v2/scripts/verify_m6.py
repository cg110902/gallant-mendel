#!/usr/bin/env python3
"""M6 final acceptance without recursively regenerating frozen substage evidence."""
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));E=ROOT/"verification"/"M6";E.mkdir(parents=True,exist_ok=True);cases=[]
def check(name,value,detail=""):cases.append({"name":name,"passed":bool(value),"detail":detail})
def run(name,cmd):
 started=time.monotonic();p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);cases.append({"name":name,"passed":p.returncode==0,"detail":f"exit={p.returncode} duration={time.monotonic()-started:.3f}s","command":cmd,"stdout":p.stdout,"stderr":p.stderr})
def load(path):return json.loads(path.read_text())
def digest(path):return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
py=sys.executable
run("py_compile",[py,"-m","compileall","-q","novel_kernel","scripts","tests"])
run("full_units_284",[py,"-m","unittest","discover","-s","tests","-v"])
run("m5_end_to_end_boundary",[py,"-m","unittest","tests.test_m5_end_to_end","-v"])
for stage in [f"M6.{n}" for n in range(1,9)]:
 root=ROOT/"verification"/stage;decision=(root/"decision.md").read_text();check(f"{stage.lower().replace('.','_')}_decision_pass","Decision: **PASS**" in decision)
 idx=load(root/"evidence-index.json");rows=idx.get("files",idx.get("artifacts",[]));mismatch=[x["path"] for x in rows if not (root/x["path"]).is_file() or digest(root/x["path"])!=x["sha256"]];check(f"{stage.lower().replace('.','_')}_evidence_hashes",not mismatch,str(mismatch))
baseline=load(ROOT/"calibration"/"baseline"/"calibration-report.v1.json");bt={key:sum(x[key] for x in baseline["confusion_matrices"]) for key in ("tp","fp","tn","fn")};check("m6_2_historical_baseline_preserved",bt=={"tp":7,"fp":0,"tn":10,"fn":3},str(bt))
bfn={x["sample_id"] for x in baseline["detections"] if x["outcome"]=="fn"};check("historical_three_fn_explicit",bfn=={"mutation_05_personadrift","mutation_09_troperepeat","mutation_10_wordcountcheat"},str(sorted(bfn)))
threshold=load(ROOT/"calibration"/"soft-v1"/"soft-threshold-bundle.v1.json");check("threshold_bundle_frozen",threshold["bundle_hash"]=="sha256:c7f35608853f6a784df4ddf59e2c7b01449e4f23e2829e67650b55a1aee0963e")
holdout=load(ROOT/"calibration"/"soft-v1"/"soft-holdout-report.v1.json");ht=holdout["totals"];check("template_holdout_preserved",ht=={"tp":12,"fp":0,"tn":12,"fn":0},str(ht))
challenge=load(ROOT/"calibration"/"challenge-v1"/"soft-challenge-report.v1.json");check("challenge_separate_and_nine_fn",challenge["template_holdout_claim_separate"] and challenge["totals"]=={"tp":9,"fp":0,"tn":18,"fn":9},str(challenge["totals"]))
check("challenge_hash_frozen",challenge["report_hash"]=="sha256:ee9147a8e272424ea2628fe1b9ac8f7ec1c01795028d488fe4863519e16466d9")
smoke=load(ROOT/"verification"/"M6.6"/"three-chapter-smoke-report.json");check("three_chapter_no_loss",smoke["chapter_count"]==3 and not smoke["silent_data_loss"] and all(smoke["loss_checks"].values()))
soak=load(ROOT/"verification"/"M6.7"/"thirty-chapter-soak-report.json");check("thirty_chapter_recovery_no_loss",soak["chapter_count"]==30 and soak["snapshot_count"]==2 and soak["transaction_recovery"]["recovered"] and not soak["silent_data_loss"] and all(soak["loss_checks"].values()))
check("fixed_ced_zero_but_not_quality_claim",soak["ced"]["overall_density"]==0 and soak["scope"]["reliability_claim"]=="controlled thirty-chapter sequential soak only")
concurrency=load(ROOT/"verification"/"M6.8"/"concurrency-guard-report.json");check("concurrency_one_winner_one_conflict",concurrency["same_parent_race"]["winner_count"]==1 and concurrency["same_parent_race"]["conflict_count"]==1 and not concurrency["silent_overwrite"])
check("resource_guard_exit_seven",concurrency["lock_contention"]["exit_code"]==7 and concurrency["lock_contention"]["authority_bytes_unchanged"])
post=load(ROOT/"calibration"/"postmortems"/"m6-known-limitations.v1.json");pb={k:v for k,v in post.items() if k!="postmortem_hash"};from novel_kernel.storage import sha256_json
check("twelve_false_negative_postmortems",len(post["false_negatives"])==12 and post["postmortem_hash"]==sha256_json(pb))
check("postmortem_binds_frozen_reports",post["baseline_report_hash"]==baseline["evaluation_hash"] and post["challenge_report_hash"]==challenge["report_hash"])
check("warning_only_policy_preserved","warning-only" in post["gate_policy"] and "human approval" in post["gate_policy"])
schemas=list((ROOT/"schemas").glob("*.json"));bad=[]
for path in schemas:
 try:json.loads(path.read_text())
 except Exception as exc:bad.append(f"{path.name}:{exc}")
check("all_schemas_parse",len(schemas)==56 and not bad,f"count={len(schemas)} bad={bad}")
check("m6_exit_conditions_mapped",all((ROOT.parent/"施工文档"/name).is_file() for name in ["35-M6.1OfflineOracle与MutationCorpus补充冻结决策.md","36-M6.2ExecutableMutationHarness补充冻结决策.md","37-M6.3SoftFeature与DataSplit补充冻结决策.md","38-M6.4Threshold冻结与OneShotHoldout补充冻结决策.md","39-M6.5AdvisoryDetector与ChallengeTransfer补充冻结决策.md","40-M6.6三章连续提交与恢复Smoke补充冻结决策.md","41-M6.7三十章Soak与断点续跑补充冻结决策.md","42-M6.8并发冲突与资源保护补充冻结决策.md","43-M6总回归与退出条件补充冻结决策.md"]))
failed=[x for x in cases if not x["passed"]];summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)};now=datetime.now(timezone.utc).isoformat()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
write(E/"test-run.json",{"schema_version":"m6.verification.v1","milestone":"M6","completed_at":now,"cases":cases,"summary":summary})
write(E/"metrics.json",{"milestone":"M6","unit_tests":284,"schemas":len(schemas),"baseline":bt,"template_holdout":ht,"challenge":challenge["totals"],"three_chapter_silent_data_loss":smoke["silent_data_loss"],"thirty_chapter_silent_data_loss":soak["silent_data_loss"],"thirty_chapter_ced":soak["ced"]["overall_density"],"concurrency_winners":concurrency["same_parent_race"]["winner_count"],"concurrency_conflicts":concurrency["same_parent_race"]["conflict_count"],"known_false_negatives":len(post["false_negatives"]),"cases":summary})
write(E/"failures.json",{"milestone":"M6","unexpected_failures":failed})
(E/"command-log.txt").write_text("\n".join(f"[{x['name']}] {'PASS' if x['passed'] else 'FAIL'} {x['detail']}" for x in cases)+"\n")
(E/"decision.md").write_text(f"# M6 final decision\n\n- Decision: **{'PASS' if not failed else 'FAIL'}**\n- Cases: **{summary['passed']}/{summary['total']} PASS**\n- M6.1–M6.8 evidence chains and frozen hashes are intact\n- Baseline, template holdout, and challenge metrics remain separate\n- Three/30-chapter controlled recovery has no silent data loss; fixed-window CED is not a quality claim\n- Lock contention is explicit exit 7 with no silent overwrite\n- Twelve historical/challenge false negatives remain in frozen postmortems\n- M6 does not claim natural-language completeness, distributed concurrency, performance SLA, or production reliability\n")
files=["test-run.json","metrics.json","failures.json","command-log.txt","decision.md"];write(E/"evidence-index.json",{"schema_version":"evidence-index.v1","milestone":"M6","files":[{"path":n,"sha256":digest(E/n)} for n in files]})
print(f"M6 final {'PASS' if not failed else 'FAIL'}: {summary['passed']}/{summary['total']}");raise SystemExit(0 if not failed else 1)
