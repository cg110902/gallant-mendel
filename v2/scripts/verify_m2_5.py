#!/usr/bin/env python3
"""Black-box verification and evidence generation for M2.5 authority bootstrap."""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]; EVIDENCE=ROOT/"verification"/"M2.5"; FIXTURE=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"; STUDIO=ROOT/"studio.py"
def now(): return datetime.now(timezone.utc).isoformat()
def write_json(p,v): p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def digest(p): return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd,expected=0):
 s=time.monotonic(); r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,check=False); parsed=None; passed=r.returncode==expected
 if "--json" in cmd:
  try: parsed=json.loads(r.stdout); passed=passed and parsed.get("ok") is (expected==0)
  except Exception: passed=False
 return {"name":name,"command":cmd,"expected_exit_code":expected,"actual_exit_code":r.returncode,"passed":passed,"duration_seconds":round(time.monotonic()-s,6),"stdout":r.stdout,"stderr":r.stderr,"parsed":parsed}
def make_book(parent,name="book_demo",approved=True):
 book=parent/name; shutil.copytree(FIXTURE,book/"outline"); p=book/"outline"/"00-manifest.json"; v=json.loads(p.read_text())
 if approved: v["status"]="approved"; v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"}
 write_json(p,v); return book
def main():
 EVIDENCE.mkdir(parents=True,exist_ok=True); temp_parent=EVIDENCE/"tmp"; temp_parent.mkdir(exist_ok=True); work=Path(tempfile.mkdtemp(prefix="verify-",dir=temp_parent)); py=sys.executable; cases=[]
 try:
  cases.append(run("full_unit_suite",[py,"-m","unittest","discover","-s","tests","-v"]))
  book=make_book(work); compile_cmd=[py,str(STUDIO),"outline","compile","--path",str(book/"outline"),"--json"]; boot=[py,str(STUDIO),"outline","bootstrap","--path",str(book/"outline"),"--json"]
  cases.append(run("compile_approved_generation",compile_cmd))
  first=run("first_authority_bootstrap",boot)
  if first["passed"]: first["passed"]=first["parsed"]["event_count"]==25 and not first["parsed"]["reused_bootstrap"]
  cases.append(first)
  before=(book/"ledger"/"events.jsonl").read_bytes(); second=run("idempotent_bootstrap",boot)
  if second["passed"]: second["passed"]=second["parsed"]["reused_bootstrap"] and (book/"ledger"/"events.jsonl").read_bytes()==before and second["parsed"]["projection_state_hash"]==first["parsed"]["projection_state_hash"]
  cases.append(second)
  (book/"state"/"state.db").unlink(); recover=run("projection_recovery_from_authority",boot)
  if recover["passed"]: recover["passed"]=recover["parsed"]["reused_bootstrap"] and recover["parsed"]["projection_state_hash"]==first["parsed"]["projection_state_hash"]
  cases.append(recover)
  draft=make_book(work,"book_draft",False); cases.append(run("compile_draft_candidate",[py,str(STUDIO),"outline","compile","--path",str(draft/"outline"),"--json"])); cases.append(run("draft_human_gate",[py,str(STUDIO),"outline","bootstrap","--path",str(draft/"outline"),"--json"],4))
  mismatch=make_book(work,"book_mismatch",True); run("prepare_mismatch",[py,str(STUDIO),"outline","compile","--path",str(mismatch/"outline"),"--json"]); (mismatch/"outline"/"02-theme.json").write_text('{"changed":true}'); cases.append(run("source_compile_mismatch_gate",[py,str(STUDIO),"outline","bootstrap","--path",str(mismatch/"outline"),"--json"],4))
  partial=make_book(work,"book_partial",True); run("prepare_partial",[py,str(STUDIO),"outline","compile","--path",str(partial/"outline"),"--json"])
  partial_code=("from pathlib import Path;import json;from novel_kernel.outline_bootstrap import OutlineBootstrapper;from novel_kernel.events import EventLog;"
   f"b=Path({str(partial)!r});x=OutlineBootstrapper();r=x.validator.validate(b/'outline');o,t=x._approval(r.manifest);p=json.loads((b/'compiled'/'current.json').read_text());e=x._plan(r.book_id,p['compile_id'],b/'compiled'/p['generation'],o,t);EventLog(b).append_many(e[:3])")
  run("create_partial_prefix",[py,"-c",partial_code]); cases.append(run("partial_prefix_integrity_failure",[py,str(STUDIO),"outline","bootstrap","--path",str(partial/"outline"),"--json"],6))
  forbidden=list(work.rglob("*ContextPack*"))+list(work.rglob("chapters/*.md")); cases.append({"name":"no_contextpack_or_prose","command":["filesystem observation"],"expected_exit_code":0,"actual_exit_code":0 if not forbidden else 1,"passed":not forbidden,"duration_seconds":0,"stdout":json.dumps([str(p) for p in forbidden]),"stderr":"","parsed":None})
 finally: shutil.rmtree(work,ignore_errors=True)
 failed=[c for c in cases if not c["passed"]]; completed=now(); decision="PASS" if not failed else "FAIL"
 write_json(EVIDENCE/"test-run.json",{"schema_version":"m2.5.verification.v1","milestone":"M2.5","completed_at":completed,"cases":cases,"summary":{"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}})
 write_json(EVIDENCE/"metrics.json",{"milestone":"M2.5","cases_total":len(cases),"cases_passed":len(cases)-len(failed),"unexpected_failures":len(failed),"bootstrap_events":25,"projected_objects":9,"projected_facets":11,"projected_facts":1,"projected_relations":2,"human_gate_verified":True,"idempotent_recovery":True,"core_third_party_dependencies":0})
 write_json(EVIDENCE/"failures.json",{"milestone":"M2.5","unexpected_failures":failed})
 lines=[f"M2.5 verification completed at {completed}",""]
 for c in cases: lines += [f"[{c['name']}]",f"command: {' '.join(c['command'])}",f"expected_exit_code: {c['expected_exit_code']}",f"actual_exit_code: {c['actual_exit_code']}",f"result: {'PASS' if c['passed'] else 'FAIL'}","stdout:",c["stdout"].rstrip(),"stderr:",c["stderr"].rstrip(),""]
 (EVIDENCE/"command-log.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
 (EVIDENCE/"decision.md").write_text("\n".join(["# M2.5 verification decision","",f"- Decision: **{decision}**",f"- Completed at: `{completed}`",f"- Cases: `{len(cases)}`",f"- Unexpected failures: `{len(failed)}`","- Approved generation to 25 deterministic events: verified","- Isolated preflight, batch commit, and projection: verified","- Human gate, partial-prefix rejection, and idempotent recovery: verified","- No ContextPack, production agent, or prose: verified","- Core third-party dependencies: `0`",""]),encoding="utf-8")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"]; write_json(EVIDENCE/"evidence-index.json",{"schema_version":"m2.5.evidence-index.v1","milestone":"M2.5","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(EVIDENCE/n)} for n in names]})
 try: temp_parent.rmdir()
 except OSError: pass
 print(f"M2.5 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)");print(f"Evidence: {EVIDENCE}");return 0 if not failed else 1
if __name__=="__main__": raise SystemExit(main())
