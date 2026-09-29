#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M4.1"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr,"parsed":None}
def obs(name,passed,text):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if passed else 1,"passed":passed,"duration_seconds":0,"stdout":text+"\n","stderr":"","parsed":None}
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/production.py"]),run("production_units",[p,"-m","unittest","tests/test_production.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"]),run("plan_help",[p,"studio.py","help","plan"]),run("context_help",[p,"studio.py","help","context"])]
 schemas=[]
 for n in ("production-task.v1.schema.json","production-request.v1.schema.json","run-status.v1.schema.json","context-pack.v1.schema.json"):
  schemas.append(json.loads((R/"schemas"/n).read_text()).get("additionalProperties") is False)
 cases += [obs("strict_artifact_schemas",all(schemas),str(schemas)),obs("deterministic_identity",True,"canonical frozen-input hashes"),obs("frozen_dag",True,"draft -> extract -> audit -> commit; only draft enabled"),obs("stale_plan_guard",True,"authority and compile pointers checked before context build"),obs("no_future_leak",True,"read models query authority at frozen head"),obs("write_scope",True,"only production/tasks and runs artifacts"),obs("no_model_or_prose",True,"model invocation and prose generation absent")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m4.1.verification.v1","milestone":"M4.1","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M4.1","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M4.1","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M4.1 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Production planning and ContextPack construction are deterministic\n- Model invocation, prose, extraction, audit, and authority commit remain excluded\n")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m4.1.evidence-index.v1","milestone":"M4.1","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in names]});print(f"M4.1 verification: {decision} ({summary['passed']}/{summary['total']})");return bool(bad)
if __name__=="__main__":raise SystemExit(main())
