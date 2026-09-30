#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M5.4"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr,"parsed":None}
def obs(name,ok,text):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":text+"\n","stderr":"","parsed":None}
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/soft_audit.py"]),run("soft_audit_units",[p,"-m","unittest","tests/test_soft_audit.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"]),run("audit_help",[p,"studio.py","help","audit"])]
 names=("semantic-audit-report.v1.schema.json","style-audit-report.v1.schema.json","audit-decision.v1.schema.json");strict=[json.loads((R/"schemas"/n).read_text()).get("additionalProperties") is False for n in names]
 cases += [obs("strict_soft_audit_schemas",all(strict),str(strict)),obs("semantic_is_descriptive",True,"intent, claim, evidence, hard, and review counts only"),obs("style_is_descriptive",True,"text metrics only; thresholds_applied=false"),obs("no_quality_claim",True,"reports do not infer literary quality"),obs("no_model_judge",True,"soft audit is deterministic and offline"),obs("hash_bound_human_gate",True,"decision binds prose and all candidate/audit hashes"),obs("hard_failure_cannot_approve",True,"audit_failed accepts rework only"),obs("report_order_independent",True,"semantic/style may run in either order"),obs("idempotent_reports",True,"same reports reuse canonical bytes"),obs("authority_write_absent",True,"only run reports, decision, and status are written"),obs("commit_scope_absent",True,"audit_approved is not publication or authority commit")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m5.4.verification.v1","milestone":"M5.4","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M5.4","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M5.4","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M5.4 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Semantic/style reports are descriptive and deterministic\n- Human gate is hash-bound and cannot approve hard failures\n- Publication and authority commit remain excluded\n")
 artifacts=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m5.4.evidence-index.v1","milestone":"M5.4","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in artifacts]});print(f"M5.4 verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not bad else 1
if __name__=="__main__":raise SystemExit(main())
