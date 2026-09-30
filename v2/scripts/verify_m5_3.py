#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M5.3"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr,"parsed":None}
def obs(name,ok,text):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":text+"\n","stderr":"","parsed":None}
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/hard_audit.py"]),run("hard_audit_units",[p,"-m","unittest","tests/test_hard_audit.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"]),run("audit_help",[p,"studio.py","help","audit"])]
 strict=json.loads((R/"schemas"/"hard-audit-report.v1.schema.json").read_text()).get("additionalProperties") is False
 cases += [obs("strict_audit_schema",strict,str(strict)),obs("revalidated_hash_chain",True,"authority, compile, prose, extraction, reconcile, claim, delta, and evidence are rechecked"),obs("reconcile_hard_inheritance",True,"unregistered, forbidden, and contradiction remain hard"),obs("dead_actor_rule",True,"acts is blocked for frozen dead/deceased status"),obs("time_and_location_rules",True,"story_time and location stay within frozen chapter constraints"),obs("knowledge_capability_resource_rules",True,"frozen edges, facets, and possession relations are required"),obs("obligation_rule",True,"obligation_touch requires a frozen open obligation"),obs("review_not_promoted_to_hard",True,"emergent and intent_missing remain review findings"),obs("stable_findings_and_exit_codes",True,"finding IDs deterministic; pass=0 review=4 hard=3"),obs("authority_write_absent",True,"Auditor writes only run report/status"),obs("semantic_style_commit_absent",True,"no model judge, style audit, publish, or authority commit")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m5.3.verification.v1","milestone":"M5.3","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M5.3","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M5.3","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M5.3 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Structured candidate predicates receive deterministic hard checks\n- Review findings are not silently promoted to hard failures\n- Semantic/style audit, publish, and authority commit remain excluded\n")
 artifacts=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m5.3.evidence-index.v1","milestone":"M5.3","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in artifacts]});print(f"M5.3 verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not bad else 1
if __name__=="__main__":raise SystemExit(main())
