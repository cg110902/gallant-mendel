#!/usr/bin/env python3
"""M7.4 live-attestation tooling acceptance; does not execute a vendor IDE."""
from __future__ import annotations
import hashlib,json,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));E=ROOT/"verification"/"M7.4";E.mkdir(parents=True,exist_ok=True);cases=[]
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def check(name,value,detail=""):cases.append({"name":name,"passed":bool(value),"detail":detail})
def run(name,cmd):
 t=time.monotonic();p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);cases.append({"name":name,"passed":p.returncode==0,"detail":f"exit={p.returncode} duration={time.monotonic()-t:.3f}s","stdout":p.stdout,"stderr":p.stderr});return p
py=sys.executable
run("py_compile",[py,"-m","py_compile","studio.py","novel_kernel/live_attestation.py"])
run("attestation_units",[py,"-m","unittest","tests.test_live_attestation","-v"])
template_path=E/"antigravity-live-input.template.json";doc=json.loads(template_path.read_text());check("template_pending",all(x["status"]=="pending" for x in doc["checks"]));check("template_has_eleven_checks",len(doc["checks"])==11);check("template_does_not_claim_runtime","vendor_runtime_executed" not in doc)
for name in ("ide-live-attestation-input.v1.schema.json","ide-live-attestation.v1.schema.json"):
 try:json.loads((ROOT/"schemas"/name).read_text());ok=True
 except Exception:ok=False
 check("schema_"+name,ok)
with tempfile.TemporaryDirectory() as temp:
 rejected=run("pending_template_rejected",[py,"studio.py","ide","attest","--input",str(template_path),"--output",str(Path(temp)/"accepted.json"),"--json"]);cases[-1]["passed"]=rejected.returncode==1
 check("rejection_claims_no_runtime",json.loads(rejected.stdout).get("vendor_runtime_executed") is False)
check("guide_marks_live_pending","PENDING" in (E/"README.md").read_text())
check("surrogate_stays_false",json.loads((ROOT/"verification/M7.2/compatibility-matrix.json").read_text()).get("vendor_runtime_executed") is False)
failed=[x for x in cases if not x["passed"]];summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
write(E/"test-run.json",{"schema_version":"m7.4.verification.v1","milestone":"M7.4-tooling","completed_at":datetime.now(timezone.utc).isoformat(),"vendor_runtime_executed":False,"live_status":"pending","cases":cases,"summary":summary})
write(E/"metrics.json",{"milestone":"M7.4-tooling","frozen_checks":11,"vendor_runtime_executed":False,"live_status":"pending","cases":summary})
write(E/"failures.json",{"milestone":"M7.4-tooling","unexpected_failures":failed})
(E/"command-log.txt").write_text("\n".join(f"[{x['name']}] {'PASS' if x['passed'] else 'FAIL'} {x['detail']}" for x in cases)+"\n")
(E/"decision.md").write_text(f"# M7.4 tooling decision\n\n- Tooling: **{'PASS' if not failed else 'FAIL'}** ({summary['passed']}/{summary['total']})\n- Antigravity live status: **PENDING**\n- `vendor_runtime_executed=false` until an operator supplies and signs all eleven evidence-bound checks\n")
artifacts=["README.md","antigravity-live-input.template.json","test-run.json","metrics.json","failures.json","command-log.txt","decision.md"];write(E/"evidence-index.json",{"schema_version":"evidence-index.v1","milestone":"M7.4-tooling","files":[{"path":n,"sha256":digest(E/n)} for n in artifacts]})
print(f"M7.4 tooling {'PASS' if not failed else 'FAIL'}: {summary['passed']}/{summary['total']}; live=PENDING");raise SystemExit(bool(failed))
