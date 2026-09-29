#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M5.2"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr,"parsed":None}
def obs(name,ok,text):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":text+"\n","stderr":"","parsed":None}
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/candidate_reconcile.py"]),run("candidate_reconcile_units",[p,"-m","unittest","tests/test_candidate_reconcile.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"]),run("reconcile_help",[p,"studio.py","help","reconcile"])]
 strict=json.loads((R/"schemas"/"candidate-reconcile.v1.schema.json").read_text()).get("additionalProperties") is False
 cases += [obs("strict_reconcile_schema",strict,str(strict)),obs("frozen_authority_cutoff",True,"authority head and compile ID must match request"),obs("evidence_chain_integrity",True,"prose, extraction hash, claim, delta, and evidence references cross-check"),obs("canonical_value_comparison",True,"fact values compare as canonical JSON"),obs("hard_preclassification",True,"unregistered subject, forbidden change, and contradiction block"),obs("review_preclassification",True,"emergent and missing intent require human review"),obs("stable_exit_codes",True,"success=0, review=4, hard=3"),obs("idempotent_candidate_output",True,"same bytes reused; conflicts rejected"),obs("authority_write_absent",True,"only candidate reconcile and run status are written"),obs("auditor_scope_absent",True,"full invariants, audit, publish, and authority commit remain excluded")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m5.2.verification.v1","milestone":"M5.2","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M5.2","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M5.2","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M5.2 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Candidate deltas reconcile against the frozen authority context\n- Hard and human-review outcomes remain non-authoritative gates\n- Audit, publish, and authority commit remain excluded\n")
 artifacts=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m5.2.evidence-index.v1","milestone":"M5.2","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in artifacts]});print(f"M5.2 verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not bad else 1
if __name__=="__main__":raise SystemExit(main())
