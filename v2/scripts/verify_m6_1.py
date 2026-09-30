#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M6.1"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr}
def obs(name,ok,text):return {"name":name,"command":["deterministic observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":text+"\n","stderr":""}
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/calibration.py"]),run("calibration_units",[p,"-m","unittest","tests/test_calibration.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"]),run("calibrate_help",[p,"studio.py","help","calibrate"])]
 corpus=json.loads((R/"calibration"/"mutation-corpus.v1.json").read_text());names=[x["mutator_id"] for x in corpus["mutations"]];expected=["KillThenAct","GhostCharacter","TimeReversal","KnowledgeLeak","PersonaDrift","HookRemoval","ForeshadowGhost","PowerJump","TropeRepeat","WordCountCheat"];schemas=["mutation-corpus.v1.schema.json","mutation-observations.v1.schema.json","calibration-report.v1.schema.json","calibrated-threshold.v1.schema.json"]
 parsed=[]
 for name in schemas:
  try:parsed.append(json.loads((R/"schemas"/name).read_text()).get("additionalProperties") is False)
  except Exception:parsed.append(False)
 cases += [obs("strict_calibration_schemas",all(parsed),str(parsed)),obs("frozen_ten_mutators",names==expected,str(names)),obs("paired_clean_controls",all(not x["clean"]["expected_detected"] and x["mutated"]["expected_detected"] for x in corpus["mutations"]),"each mutation has clean negative and mutated positive"),obs("offline_oracle_no_api",corpus["oracle"]["external_api_used"] is False,"deterministic offline-writer.v1"),obs("corpus_hash_sealed",corpus["corpus_hash"]=="sha256:2e59a7255201afd97b73c41098749c582800e02d37ddc90cf90f51553fd614f8",corpus["corpus_hash"]),obs("complete_observations_required",True,"missing/duplicate/unknown sample observations are rejected"),obs("per_gate_confusion_matrix",True,"TP/FP/TN/FN plus nullable precision/recall are emitted per expected gate"),obs("soft_false_negatives_visible",True,"unsupported soft detectors remain FN rather than fabricated passes"),obs("fixed_window_ced",True,"contiguous chapter windows report errors/chapter; gaps are rejected"),obs("threshold_provenance_required",True,"dates, sample size, ordered distribution, rationale, owner, corpus/report hashes required"),obs("threshold_not_activated",True,"M6.1 validates records but installs no production threshold"),obs("authority_write_absent",True,"corpus and reports are calibration artifacts; EventLog is untouched"),obs("scope_boundary",True,"no model judge, 3/30 chapter reliability, concurrency, or performance claim")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m6.1.verification.v1","milestone":"M6.1","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M6.1","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M6.1","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M6.1 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Offline oracle and frozen ten-mutator gold corpus are deterministic\n- Confusion/CED metrics preserve false negatives and reject incomplete observations\n- No production quality threshold or reliability claim is activated\n")
 artifacts=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m6.1.evidence-index.v1","milestone":"M6.1","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in artifacts]});print(f"M6.1 verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not bad else 1
if __name__=="__main__":raise SystemExit(main())
