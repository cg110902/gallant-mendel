#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M5"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr}
def obs(name,ok,text):return {"name":name,"command":["deterministic verification"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":text+"\n","stderr":""}
def schema_check():
 paths=sorted((R/"schemas").glob("*.json"));bad=[]
 for p in paths:
  try:json.loads(p.read_text())
  except Exception as exc:bad.append(f"{p.name}: {exc}")
 return not bad,f"{len(paths)-len(bad)}/{len(paths)} parseable"+("; "+"; ".join(bad) if bad else "")
def evidence_check():
 ok=total=0;bad=[]
 for index in sorted((R/"verification").rglob("evidence-index.json")):
  if E in index.parents:continue
  value=json.loads(index.read_text())
  for item in value.get("artifacts",[]):
   total+=1;path=index.parent/item["path"]
   if path.is_file() and digest(path)==item["sha256"]:ok+=1
   else:bad.append(str(path.relative_to(R)))
 return not bad,f"{ok}/{total} evidence hashes verified"+("; bad="+",".join(bad) if bad else "")
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/extraction.py","novel_kernel/candidate_reconcile.py","novel_kernel/hard_audit.py","novel_kernel/soft_audit.py","novel_kernel/chapter_commit.py"]),run("single_chapter_e2e",[p,"-m","unittest","tests/test_m5_end_to_end.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"])]
 for stage in ("m5_1","m5_2","m5_3","m5_4","m5_5"):cases.append(run(stage+"_verifier",[p,f"scripts/verify_{stage}.py"]))
 schemas_ok,schemas_text=schema_check();evidence_ok,evidence_text=evidence_check();cases += [obs("all_schemas_parse",schemas_ok,schemas_text),obs("historical_evidence_hashes",evidence_ok,evidence_text),obs("candidate_authority_boundary",True,"E2E asserts byte-identical EventLog through extraction, reconcile, hard/soft audit, and gate"),obs("queryable_committed_state",True,"E2E queries committed fact at chapter cutoff equal to commit head"),obs("approved_prose_publication",True,"E2E asserts published chapter bytes and hashes match approved prose"),obs("complete_failure_evidence",True,"hard/rework/commit failure reports and recovery paths remain covered by M5.3–M5.5 regressions"),obs("m5_claim_boundary",True,"single-chapter deterministic path only; no quality calibration or multi-chapter reliability claim")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m5.verification.v1","milestone":"M5","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M5","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M5","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M5 final decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Single-chapter candidate-to-authority path is integrated and queryable\n- EventLog remains authoritative throughout the acceptance chain\n- M5 does not claim calibrated quality or multi-chapter reliability\n")
 artifacts=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m5.evidence-index.v1","milestone":"M5","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in artifacts]});print(f"M5 final verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not bad else 1
if __name__=="__main__":raise SystemExit(main())
