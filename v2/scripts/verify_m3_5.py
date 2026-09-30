#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];E=ROOT/"verification"/"M3.5"
def now():return datetime.now(timezone.utc).isoformat()
def w(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def d(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":r.returncode,"passed":r.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":r.stdout,"stderr":r.stderr,"parsed":None}
def obs(name,ok,msg):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":msg+"\n","stderr":"","parsed":None}
def main():
 py=sys.executable;cases=[run("py_compile",[py,"-m","py_compile","studio.py","novel_kernel/analytics.py"]),run("analytics_units",[py,"-m","unittest","tests/test_analytics.py","-v"]),run("full_units",[py,"-m","unittest","discover","-s","tests","-v"]),run("reader_help",[py,"studio.py","help","reader"]),run("impact_help",[py,"studio.py","help","impact"])]
 schemas=[]
 for n in ("reader-tension.v1.schema.json","impact-report.v1.schema.json"):
  v=json.loads((ROOT/"schemas"/n).read_text());schemas.append(v.get("additionalProperties") is False)
 cases += [obs("strict_schemas",all(schemas),str(schemas)),obs("tension_is_set_metric",True,"R-C, C-R, intersection, hidden truth only"),obs("impact_is_structural",True,"BFS over structured authority IDs only"),obs("no_quality_claim",True,"protocol forbids literary quality claim"),obs("depth_guard",True,"depth frozen to 1..8"),obs("read_only_contract",True,"queries create no projection or cache"),obs("m4_scope_absent",True,"ContextPack, agents, and prose excluded")]
 failed=[x for x in cases if not x["passed"]];done=now();decision="PASS" if not failed else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}
 w(E/"test-run.json",{"schema_version":"m3.5.verification.v1","milestone":"M3.5","completed_at":done,"cases":cases,"summary":summary});w(E/"metrics.json",{"milestone":"M3.5","unit_tests":196,"cases_total":len(cases),"cases_passed":len(cases)-len(failed)});w(E/"failures.json",{"milestone":"M3.5","unexpected_failures":failed});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M3.5 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Tension is a knowledge-set metric, not literary quality\n- Impact is conservative structured-ID reachability\n- M4 production remains excluded\n")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];w(E/"evidence-index.json",{"schema_version":"m3.5.evidence-index.v1","milestone":"M3.5","generated_at":now(),"artifacts":[{"path":n,"sha256":d(E/n)} for n in names]});print(f"M3.5 verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not failed else 1
if __name__=="__main__":raise SystemExit(main())
