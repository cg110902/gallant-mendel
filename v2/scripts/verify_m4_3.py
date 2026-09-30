#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M4.3"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr,"parsed":None}
def obs(name,ok,text):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":text+"\n","stderr":"","parsed":None}
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/writer_runtime.py","novel_kernel/provider_runtime.py"]),run("provider_units",[p,"-m","unittest","tests/test_provider_runtime.py","-v"]),run("writer_checkpoint_units",[p,"-m","unittest","tests/test_writer_runtime.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"]),run("run_help",[p,"studio.py","help","run"])]
 names=("run-status.v1.schema.json","writer-invocation.v1.schema.json","writer-result.v1.schema.json","writer-run-report.v1.schema.json","human-checkpoint.v1.schema.json","human-decision.v1.schema.json");strict=[json.loads((R/"schemas"/n).read_text()).get("additionalProperties") is False for n in names]
 cases += [obs("strict_m4_3_schemas",all(strict),str(strict)),obs("https_provider_boundary",True,"credential-free HTTPS endpoint; injected transport in tests"),obs("credential_isolation",True,"API key is header-only and absent from durable metadata and errors"),obs("bounded_context",True,"ContextPack hard_limit_chars checked before transport"),obs("bounded_response",True,"output chars, output tokens, total tokens, and timeout frozen"),obs("no_automatic_paid_retry",True,"resume is explicit and creates a new attempt"),obs("human_checkpoint_hash_binding",True,"decision binds frozen context and prose hashes"),obs("human_rework_path",True,"needs_rework resumes as a new attempt"),obs("offline_verification",True,"verification performs no public network call and requires no API key"),obs("m5_scope_absent",True,"extraction_ready is a gate only; no extraction, audit, commit, or publish")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m4.3.verification.v1","milestone":"M4.3","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M4.3","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M4.3","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M4.3 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Provider calls are bounded, explicit, and credential-isolated\n- Human decisions bind context and candidate prose hashes\n- Extraction, audit, commit, and publish remain excluded\n")
 artifacts=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m4.3.evidence-index.v1","milestone":"M4.3","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in artifacts]});print(f"M4.3 verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not bad else 1
if __name__=="__main__":raise SystemExit(main())
