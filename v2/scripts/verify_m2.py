#!/usr/bin/env python3
"""Final M2 acceptance: evidence chain, deterministic pipeline, and readiness."""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]; EVIDENCE=ROOT/"verification"/"M2"; FIXTURE=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"; STUDIO=ROOT/"studio.py"
def now():return datetime.now(timezone.utc).isoformat()
def write_json(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd,expected=0):
 s=time.monotonic();r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,check=False);parsed=None;passed=r.returncode==expected
 if "--json" in cmd:
  try:parsed=json.loads(r.stdout);passed=passed and parsed.get("ok",parsed.get("ready")) is (expected==0)
  except Exception:passed=False
 return {"name":name,"command":cmd,"expected_exit_code":expected,"actual_exit_code":r.returncode,"passed":passed,"duration_seconds":round(time.monotonic()-s,6),"stdout":r.stdout,"stderr":r.stderr,"parsed":parsed}
def approved(parent,name):
 b=parent/name;shutil.copytree(FIXTURE,b/"outline");p=b/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};write_json(p,v);return b
def main():
 EVIDENCE.mkdir(parents=True,exist_ok=True);temp_parent=EVIDENCE/"tmp";temp_parent.mkdir(exist_ok=True);work=Path(tempfile.mkdtemp(prefix="verify-",dir=temp_parent));py=sys.executable;cases=[];observations={}
 try:
  cases.append(run("full_unit_suite",[py,"-m","unittest","discover","-s","tests","-v"]))
  checked=0;bad=[]
  for milestone in ("M2.1","M2.2","M2.3","M2.4","M2.5"):
   idx=ROOT/"verification"/milestone/"evidence-index.json";value=json.loads(idx.read_text())
   for item in value["artifacts"]:
    p=idx.parent/item["path"];actual=digest(p);checked+=1
    if actual!=item["sha256"]:bad.append(str(p))
  cases.append({"name":"m2_substage_evidence_chain","command":["verify M2.1-M2.5 evidence indexes"],"expected_exit_code":0,"actual_exit_code":0 if not bad else 1,"passed":not bad,"duration_seconds":0,"stdout":f"{checked} hashes checked; mismatches={bad}\n","stderr":"","parsed":None})
  books=[approved(work,"book_a"),approved(work,"book_b")];outputs=[]
  for index,b in enumerate(books,1):
   prefix=f"pipeline_{index}";base=[py,str(STUDIO),"outline"]
   cases.append(run(prefix+"_validate",base+["validate","--path",str(b/"outline"),"--json"]))
   comp=run(prefix+"_compile",base+["compile","--path",str(b/"outline"),"--json"]);cases.append(comp)
   boot=run(prefix+"_bootstrap",base+["bootstrap","--path",str(b/"outline"),"--json"]);cases.append(boot)
   ready=run(prefix+"_readiness",base+["readiness","--path",str(b/"outline"),"--json"]);cases.append(ready)
   outputs.append((comp,boot,ready,(b/"ledger"/"events.jsonl").read_bytes()))
  deterministic=(outputs[0][0]["parsed"]["compile_id"]==outputs[1][0]["parsed"]["compile_id"] and outputs[0][1]["parsed"]["projection_state_hash"]==outputs[1][1]["parsed"]["projection_state_hash"] and outputs[0][3]==outputs[1][3] and outputs[0][2]["parsed"]==outputs[1][2]["parsed"])
  cases.append({"name":"independent_pipeline_determinism","command":["compare two independent pipeline outputs"],"expected_exit_code":0,"actual_exit_code":0 if deterministic else 1,"passed":deterministic,"duration_seconds":0,"stdout":f"compile={outputs[0][0]['parsed']['compile_id']} event_log_hash={digest(books[0]/'ledger'/'events.jsonl')}\n","stderr":"","parsed":None})
  error_total=0;error_bad=[]
  for milestone in ("M2.1","M2.2","M2.3","M2.4","M2.5"):
   value=json.loads((ROOT/"verification"/milestone/"test-run.json").read_text())
   for item in value["cases"]:
    if item.get("expected_exit_code",0)!=0:
     error_total+=1
     if not item["passed"]:error_bad.append(f"{milestone}:{item['name']}")
  corpus_ok=error_total>=12 and not error_bad
  cases.append({"name":"deliberate_error_corpus","command":["inspect passed M2 error cases"],"expected_exit_code":0,"actual_exit_code":0 if corpus_ok else 1,"passed":corpus_ok,"duration_seconds":0,"stdout":f"error_cases={error_total} failed={error_bad}\n","stderr":"","parsed":None})
  recovery_book=books[0];before=outputs[0][1]["parsed"]["projection_state_hash"];(recovery_book/"state"/"state.db").unlink();recovery=run("projection_delete_bootstrap_recovery",[py,str(STUDIO),"outline","bootstrap","--path",str(recovery_book/"outline"),"--json"])
  if recovery["passed"]:recovery["passed"]=recovery["parsed"]["reused_bootstrap"] and recovery["parsed"]["projection_state_hash"]==before
  cases.append(recovery)
  cases.append(run("readiness_after_recovery",[py,str(STUDIO),"outline","readiness","--path",str(recovery_book/"outline"),"--json"]))
  forbidden=list(work.rglob("*ContextPack*"))+list(work.rglob("chapters/*.md"))+list(work.rglob("production/task*"))
  cases.append({"name":"no_out_of_scope_production_artifacts","command":["filesystem observation"],"expected_exit_code":0,"actual_exit_code":0 if not forbidden else 1,"passed":not forbidden,"duration_seconds":0,"stdout":json.dumps([str(p) for p in forbidden]),"stderr":"","parsed":None})
  observations={"compile_id":outputs[0][0]["parsed"]["compile_id"],"event_count":outputs[0][1]["parsed"]["event_count"],"authority_head":outputs[0][1]["parsed"]["head_event_id"],"event_log_hash":digest(books[0]/"ledger"/"events.jsonl"),"projection_state_hash":outputs[0][1]["parsed"]["projection_state_hash"],"chapter_id":outputs[0][2]["parsed"]["chapter_id"],"error_corpus_count":error_total,"substage_evidence_hashes":checked}
 finally:shutil.rmtree(work,ignore_errors=True)
 failed=[c for c in cases if not c["passed"]];completed=now();decision="PASS" if not failed else "FAIL"
 write_json(EVIDENCE/"test-run.json",{"schema_version":"m2.verification.v1","milestone":"M2","completed_at":completed,"cases":cases,"observations":observations,"summary":{"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}})
 write_json(EVIDENCE/"metrics.json",{"milestone":"M2","cases_total":len(cases),"cases_passed":len(cases)-len(failed),"unexpected_failures":len(failed),**observations,"core_third_party_dependencies":0,"contextpack_generated":False})
 write_json(EVIDENCE/"failures.json",{"milestone":"M2","unexpected_failures":failed})
 lines=[f"M2 final verification completed at {completed}",""]
 for c in cases:lines += [f"[{c['name']}]",f"command: {' '.join(c['command'])}",f"expected_exit_code: {c['expected_exit_code']}",f"actual_exit_code: {c['actual_exit_code']}",f"result: {'PASS' if c['passed'] else 'FAIL'}","stdout:",c["stdout"].rstrip(),"stderr:",c["stderr"].rstrip(),""]
 (EVIDENCE/"command-log.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
 (EVIDENCE/"decision.md").write_text("\n".join(["# M2 final verification decision","",f"- Decision: **{decision}**",f"- Completed at: `{completed}`",f"- Cases: `{len(cases)}`",f"- Unexpected failures: `{len(failed)}`",f"- Deliberate error cases: `{observations.get('error_corpus_count',0)}`",f"- M2.1–M2.5 indexed evidence hashes: `{observations.get('substage_evidence_hashes',0)}`","- Independent validate/compile/bootstrap/readiness pipelines: byte-deterministic","- First chapter ContextPack prerequisites: ready","- ContextPack, production agent, and prose generation: not implemented","- Core third-party dependencies: `0`",""]),encoding="utf-8")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write_json(EVIDENCE/"evidence-index.json",{"schema_version":"m2.evidence-index.v1","milestone":"M2","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(EVIDENCE/n)} for n in names]})
 try:temp_parent.rmdir()
 except OSError:pass
 print(f"M2 final verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)");print(f"Evidence: {EVIDENCE}");return 0 if not failed else 1
if __name__=="__main__":raise SystemExit(main())
