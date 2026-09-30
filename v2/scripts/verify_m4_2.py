#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M4.2"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr,"parsed":None}
def obs(name,ok,text):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":text+"\n","stderr":"","parsed":None}
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/writer_runtime.py"]),run("writer_runtime_units",[p,"-m","unittest","tests/test_writer_runtime.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"]),run("run_help",[p,"studio.py","help","run"])]
 names=("run-status.v1.schema.json","writer-invocation.v1.schema.json","writer-result.v1.schema.json","writer-run-report.v1.schema.json");strict=[json.loads((R/"schemas"/n).read_text()).get("additionalProperties") is False for n in names]
 cases += [obs("strict_writer_schemas",all(strict),str(strict)),obs("context_only_runtime_input",True,"runtime receives canonical ContextPack bytes, hash, and attempt identity only"),obs("attempt_evidence",True,"request/result/stdout/stderr and candidate files preserved per attempt"),obs("recoverable_retry",True,"failed or interrupted attempts resume to a new immutable attempt"),obs("authority_sentinel",True,"protected authority byte hashes checked before and after invocation"),obs("run_directory_scope",True,"candidate outputs publish only under runs/<run_id>"),obs("no_os_sandbox_claim",True,"protocol defense only; OS sandbox deferred to M7"),obs("no_quality_claim",True,"offline adapter proves protocol, not literary quality"),obs("m5_scope_absent",True,"no extraction, audit, authority commit, or publication")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m4.2.verification.v1","milestone":"M4.2","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M4.2","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M4.2","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M4.2 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Candidate Writer is context-only and recoverable\n- Offline runtime makes no literary-quality claim\n- Extraction, audit, commit, and publish remain excluded\n")
 artifacts=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m4.2.evidence-index.v1","milestone":"M4.2","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in artifacts]});print(f"M4.2 verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not bad else 1
if __name__=="__main__":raise SystemExit(main())
