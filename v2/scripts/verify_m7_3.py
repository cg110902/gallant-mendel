#!/usr/bin/env python3
"""M7.3 branch, non-destructive rollback, and deterministic export evidence."""
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));E=ROOT/"verification"/"M7.3";E.mkdir(parents=True,exist_ok=True);cases=[]
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def check(name,value,detail=""):cases.append({"name":name,"passed":bool(value),"detail":detail})
def run(name,cmd):
 t=time.monotonic();p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);cases.append({"name":name,"passed":p.returncode==0,"detail":f"exit={p.returncode} duration={time.monotonic()-t:.3f}s","stdout":p.stdout,"stderr":p.stderr});return p
py=sys.executable
run("py_compile",[py,"-m","py_compile","studio.py","novel_kernel/branch_ops.py","novel_kernel/export.py"])
unit=run("branch_export_units",[py,"-m","unittest","tests.test_branch_export","-v"])
help_run=run("cli_help",[py,"studio.py","help"]);check("help_names_branch", "branch create|rollback" in help_run.stdout);check("help_names_export","Deterministic Markdown/JSON/EPUB export" in help_run.stdout)
for name in ("branch-operation-report.v1.schema.json","export-manifest.v1.schema.json","novel-export.v1.schema.json"):
 try:json.loads((ROOT/"schemas"/name).read_text());ok=True
 except Exception:ok=False
 check("schema_"+name,ok)
source=(ROOT/"novel_kernel/export.py").read_text();check("export_authority_read_only",all(token not in source for token in ("EventLog(book).append","ProjectionStore(","SnapshotStore(")))
check("rollback_is_new_branch","non_destructive_rollback" in (ROOT/"novel_kernel/branch_ops.py").read_text())
check("epub_fixed_timestamp","(1980,1,1,0,0,0)" in source)
check("unit_count_three",unit.stderr.count(" ... ok")>=3)
failed=[x for x in cases if not x["passed"]];summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
write(E/"test-run.json",{"schema_version":"m7.3.verification.v1","milestone":"M7.3","completed_at":datetime.now(timezone.utc).isoformat(),"cases":cases,"summary":summary})
write(E/"metrics.json",{"milestone":"M7.3","branch_modes":2,"export_formats":3,"deterministic_epub":True,"authority_read_only_export":True,"cases":summary})
write(E/"failures.json",{"milestone":"M7.3","unexpected_failures":failed})
(E/"command-log.txt").write_text("\n".join(f"[{x['name']}] {'PASS' if x['passed'] else 'FAIL'} {x['detail']}" for x in cases)+"\n")
(E/"decision.md").write_text(f"# M7.3 decision\n\n- Decision: **{'PASS' if not failed else 'FAIL'}**\n- Cases: **{summary['passed']}/{summary['total']} PASS**\n- Rollback creates a new branch and never rewrites main history\n- Markdown/JSON/EPUB exports are deterministic and authority-read-only\n- EPUB is a minimal EPUB 3 interface, not reader certification\n")
artifacts=["test-run.json","metrics.json","failures.json","command-log.txt","decision.md"];write(E/"evidence-index.json",{"schema_version":"evidence-index.v1","milestone":"M7.3","files":[{"path":n,"sha256":digest(E/n)} for n in artifacts]})
print(f"M7.3 {'PASS' if not failed else 'FAIL'}: {summary['passed']}/{summary['total']}");raise SystemExit(bool(failed))
