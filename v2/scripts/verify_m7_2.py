#!/usr/bin/env python3
"""Acceptance evidence for M7.2 portable-core IDE compatibility surrogates."""
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));E=ROOT/"verification"/"M7.2";E.mkdir(parents=True,exist_ok=True);cases=[]
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def check(name,value,detail=""):cases.append({"name":name,"passed":bool(value),"detail":detail})
def run(name,cmd):
 t=time.monotonic();p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);cases.append({"name":name,"passed":p.returncode==0,"detail":f"exit={p.returncode} duration={time.monotonic()-t:.3f}s","stdout":p.stdout,"stderr":p.stderr});return p
py=sys.executable
run("py_compile",[py,"-m","py_compile","novel_kernel/compatibility_matrix.py"])
run("matrix_units",[py,"-m","unittest","tests.test_compatibility_matrix","-v"])
run("matrix_cli",[py,"-m","novel_kernel.compatibility_matrix","--output",str(E/"compatibility-matrix.json")])
try: report=json.loads((E/"compatibility-matrix.json").read_text())
except (OSError,json.JSONDecodeError): report={}
check("matrix_report_ok",report.get("ok") is True)
check("four_by_ten",report.get("platform_count")==4 and report.get("capability_count")==10)
check("forty_mapping_rows",sum(len(x.get("cases",[])) for x in report.get("platform_matrices",[]))==40)
check("all_mappings_pass",all(x.get("passed")==10 and x.get("total")==10 for x in report.get("platform_matrices",[])))
check("vendor_runtime_not_claimed",report.get("vendor_runtime_executed") is False and report.get("claims",{}).get("real_vendor_ide_tested") is False)
check("live_attestation_required",report.get("live_attestation_required") is True)
check("antigravity_live_pending",(E/"ANTIGRAVITY-LIVE-ACCEPTANCE.md").is_file() and "PENDING" in (E/"ANTIGRAVITY-LIVE-ACCEPTANCE.md").read_text())
check("schema_present",(ROOT/"schemas/ide-compatibility-matrix.v1.schema.json").is_file())
failed=[x for x in cases if not x["passed"]];summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
write(E/"test-run.json",{"schema_version":"m7.2.verification.v1","milestone":"M7.2","completed_at":datetime.now(timezone.utc).isoformat(),"cases":cases,"summary":summary})
write(E/"metrics.json",{"milestone":"M7.2","platforms":4,"capabilities":10,"mapping_rows":40,"portable_core_passed":report.get("portable_cases_passed",0),"vendor_runtime_executed":False,"cases":summary})
write(E/"failures.json",{"milestone":"M7.2","unexpected_failures":failed})
(E/"command-log.txt").write_text("\n".join(f"[{x['name']}] {'PASS' if x['passed'] else 'FAIL'} {x['detail']}" for x in cases)+"\n")
(E/"decision.md").write_text(f"# M7.2 decision\n\n- Decision: **{'PASS' if not failed else 'FAIL'}**\n- Cases: **{summary['passed']}/{summary['total']} PASS**\n- Portable core: **{report.get('portable_cases_passed',0)}/10 PASS**\n- Adapter mappings: **4 × 10**\n- `vendor_runtime_executed=false`; Antigravity live acceptance remains **PENDING**\n")
artifacts=["compatibility-matrix.json","test-run.json","metrics.json","failures.json","command-log.txt","decision.md","ANTIGRAVITY-LIVE-ACCEPTANCE.md"];write(E/"evidence-index.json",{"schema_version":"evidence-index.v1","milestone":"M7.2","files":[{"path":n,"sha256":digest(E/n)} for n in artifacts]})
print(f"M7.2 {'PASS' if not failed else 'FAIL'}: {summary['passed']}/{summary['total']}");raise SystemExit(0 if not failed else 1)
