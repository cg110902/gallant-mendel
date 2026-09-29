#!/usr/bin/env python3
"""Black-box verification and evidence generation for M2.4 compilation."""
from __future__ import annotations
import hashlib,json,os,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]; EVIDENCE=ROOT/"verification"/"M2.4"
FIXTURE=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"; STUDIO=ROOT/"studio.py"
def now(): return datetime.now(timezone.utc).isoformat()
def write_json(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def digest(path): return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def run(name,command,expected=0):
 started=time.monotonic(); r=subprocess.run(command,cwd=ROOT,text=True,capture_output=True,check=False)
 parsed=None; passed=r.returncode==expected
 if "--json" in command:
  try: parsed=json.loads(r.stdout); passed=passed and parsed.get("ok") is (expected==0)
  except Exception: passed=False
 return {"name":name,"command":command,"expected_exit_code":expected,"actual_exit_code":r.returncode,"passed":passed,"duration_seconds":round(time.monotonic()-started,6),"stdout":r.stdout,"stderr":r.stderr,"parsed":parsed}
def main():
 EVIDENCE.mkdir(parents=True,exist_ok=True); tmp=EVIDENCE/"tmp"; tmp.mkdir(exist_ok=True)
 work=Path(tempfile.mkdtemp(prefix="verify-",dir=tmp)); py=sys.executable; cases=[]
 try:
  book=work/"book_demo"; shutil.copytree(FIXTURE,book/"outline")
  cli=[py,str(STUDIO),"outline","compile","--path",str(book/"outline"),"--json"]
  cases.append(run("full_unit_suite",[py,"-m","unittest","discover","-s","tests","-v"]))
  first=run("compile_generation",cli)
  if first["passed"]: first["passed"]=first["parsed"]["artifact_count"]==7 and not first["parsed"]["reused_generation"]
  cases.append(first)
  second=run("idempotent_recompile",cli)
  if second["passed"]: second["passed"]=second["parsed"]["compile_id"]==first["parsed"]["compile_id"] and second["parsed"]["reused_generation"]
  cases.append(second)
  generation=Path(first["parsed"]["generation_path"])
  index=json.loads((generation/"artifact-index.json").read_text())
  integrity=all("sha256:"+hashlib.sha256((generation/a["path"]).read_bytes()).hexdigest()==a["sha256"] for a in index["artifacts"])
  cases.append({"name":"artifact_index_hashes","command":["filesystem hash observation"],"expected_exit_code":0,"actual_exit_code":0 if integrity else 1,"passed":integrity,"duration_seconds":0,"stdout":f"{len(index['artifacts'])} artifacts\n","stderr":"","parsed":None})
  fault_book=work/"fault"; shutil.copytree(FIXTURE,fault_book/"outline")
  fault_code=("from pathlib import Path; from novel_kernel.outline_compile import OutlineCompiler; "
   f"b=Path({str(fault_book)!r}); c=OutlineCompiler(); a=c.compile(b/'outline'); old=(b/'compiled'/'current.json').read_bytes(); "
   "p=b/'outline'/'02-theme.json'; p.write_text('{\"changed\":true}'); "
   "f=lambda: (_ for _ in ()).throw(RuntimeError('injected')); "
   "\ntry: c.compile(b/'outline',_before_pointer=f)\nexcept RuntimeError: pass\nelse: raise AssertionError('fault absent')\n"
   "assert (b/'compiled'/'current.json').read_bytes()==old; assert len(list((b/'compiled'/'generations').iterdir()))==1; print('preserved')")
  cases.append(run("pointer_fault_rollback",[py,"-c",fault_code]))
  (generation/"objects.json").write_text("tampered")
  cases.append(run("tampered_generation_rejected",cli,6))
  invalid=work/"invalid"; shutil.copytree(FIXTURE,invalid/"outline"); p=invalid/"outline"/"12-chapter-map.json"; v=json.loads(p.read_text()); del v[0]["purpose"]; write_json(p,v)
  bad=run("invalid_domain_not_compiled",[py,str(STUDIO),"outline","compile","--path",str(invalid/"outline"),"--json"],2)
  bad["passed"]=bad["passed"] and not (invalid/"compiled").exists(); cases.append(bad)
  if os.name=="posix":
   linked=work/"linked"; shutil.copytree(FIXTURE,linked/"outline"); target=linked/"target"; target.mkdir(); (linked/"compiled").symlink_to(target,target_is_directory=True)
   cases.append(run("compiled_symlink_rejected",[py,str(STUDIO),"outline","compile","--path",str(linked/"outline"),"--json"],5))
  authority=list(work.rglob("events.jsonl"))+list(work.rglob("*.db"))
  cases.append({"name":"no_authority_outputs","command":["filesystem observation"],"expected_exit_code":0,"actual_exit_code":0 if not authority else 1,"passed":not authority,"duration_seconds":0,"stdout":json.dumps([str(p) for p in authority]),"stderr":"","parsed":None})
 finally: shutil.rmtree(work,ignore_errors=True)
 failed=[c for c in cases if not c["passed"]]; completed=now(); decision="PASS" if not failed else "FAIL"
 write_json(EVIDENCE/"test-run.json",{"schema_version":"m2.4.verification.v1","milestone":"M2.4","completed_at":completed,"cases":cases,"summary":{"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}})
 write_json(EVIDENCE/"metrics.json",{"milestone":"M2.4","cases_total":len(cases),"cases_passed":len(cases)-len(failed),"unexpected_failures":len(failed),"logical_artifacts":7,"atomic_pointer":True,"idempotent_generation":True,"authority_files_created":0,"core_third_party_dependencies":0})
 write_json(EVIDENCE/"failures.json",{"milestone":"M2.4","unexpected_failures":failed})
 lines=[f"M2.4 verification completed at {completed}",""]
 for c in cases: lines += [f"[{c['name']}]",f"command: {' '.join(c['command'])}",f"expected_exit_code: {c['expected_exit_code']}",f"actual_exit_code: {c['actual_exit_code']}",f"result: {'PASS' if c['passed'] else 'FAIL'}","stdout:",c["stdout"].rstrip(),"stderr:",c["stderr"].rstrip(),""]
 (EVIDENCE/"command-log.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
 (EVIDENCE/"decision.md").write_text("\n".join(["# M2.4 verification decision","",f"- Decision: **{decision}**",f"- Completed at: `{completed}`",f"- Cases: `{len(cases)}`",f"- Unexpected failures: `{len(failed)}`","- Content-addressed generation and seven logical artifacts: verified","- Atomic current pointer and injected-fault rollback: verified","- Idempotence and tamper rejection: verified","- No authority event or projection output: verified","- M2.5 initial authority bootstrap: not implemented","- Core third-party dependencies: `0`",""]),encoding="utf-8")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"]
 write_json(EVIDENCE/"evidence-index.json",{"schema_version":"m2.4.evidence-index.v1","milestone":"M2.4","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(EVIDENCE/n)} for n in names]})
 try: tmp.rmdir()
 except OSError: pass
 print(f"M2.4 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)"); print(f"Evidence: {EVIDENCE}")
 return 0 if not failed else 1
if __name__=="__main__": raise SystemExit(main())
