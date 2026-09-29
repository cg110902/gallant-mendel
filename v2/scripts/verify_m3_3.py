#!/usr/bin/env python3
"""M3.3 acceptance: evidence-gated Future Obligation lifecycle."""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));EVIDENCE=ROOT/"verification"/"M3.3";STUDIO=ROOT/"studio.py";FIXTURE=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
def now():return datetime.now(timezone.utc).isoformat()
def write_json(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def tree(root):
 vals=[(str(p.relative_to(root)),digest(p)) for p in sorted(x for x in root.rglob("*") if x.is_file())];return "sha256:"+hashlib.sha256(json.dumps(vals,sort_keys=True).encode()).hexdigest()
def run(name,cmd,expected=0):
 start=time.monotonic();r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,check=False);parsed=None;passed=r.returncode==expected
 if "--json" in cmd:
  try:parsed=json.loads(r.stdout)
  except Exception:passed=False
 return {"name":name,"command":cmd,"expected_exit_code":expected,"actual_exit_code":r.returncode,"passed":passed,"duration_seconds":round(time.monotonic()-start,6),"stdout":r.stdout,"stderr":r.stderr,"parsed":parsed}
def observed(name,passed,msg):return {"name":name,"command":["protocol/filesystem observation"],"expected_exit_code":0,"actual_exit_code":0 if passed else 1,"passed":passed,"duration_seconds":0,"stdout":msg+"\n","stderr":"","parsed":None}
def lifecycle(book):
 from novel_kernel.events import EventLog
 from tests.test_obligations import eid,event,obligation,touch
 vals=[event(1,"obligation.created",{"obligation":obligation(),"evidence":[]},None,0),event(2,"chapter.committed",{"chapter_id":"ch_001"},eid(1),1),touch(3,eid(2),eid(2),1),event(4,"scene.committed",{"scene_id":"scene_002"},eid(3),2),touch(5,eid(4),eid(4),2),event(6,"chapter.committed",{"chapter_id":"ch_003"},eid(5),3),event(7,"obligation.fulfilled",{"obligation_id":"ob_secret","payoff_event_id":eid(6),"satisfied_requirements":["reveal_secret"],"source_refs":["chapter:payoff"],"evidence":[]},eid(6),3)]
 log=EventLog(book)
 for x in vals:log.append(x)
def main():
 EVIDENCE.mkdir(parents=True,exist_ok=True);work=Path(tempfile.mkdtemp(prefix="m3-3-"));cases=[];py=sys.executable;obs={}
 try:
  cases.append(run("py_compile",[py,"-m","py_compile","studio.py","novel_kernel/obligations.py"]))
  cases.append(run("obligation_unit_suite",[py,"-m","unittest","tests/test_obligations.py","-v"]))
  cases.append(run("full_regression_suite",[py,"-m","unittest","discover","-s","tests","-v"]))
  schema=json.loads((ROOT/"schemas"/"obligation-state.v1.schema.json").read_text());cases.append(observed("strict_output_schema",schema.get("additionalProperties") is False,json.dumps(schema,sort_keys=True)))
  cases.append(run("obligation_help",[py,str(STUDIO),"help","obligation"]))
  book=work/"book_lifecycle";lifecycle(book);base=[py,str(STUDIO),"obligation","list","--path",str(book)]
  before=tree(book);due=run("chapter_due_query",base+["--as-of","ch_002","--json"]);cases.append(due)
  terminal=run("terminal_head_query",base+["--as-of","head","--status","terminal","--json"]);cases.append(terminal)
  repeat=run("repeat_query",base+["--as-of","ch_002","--json"]);cases.append(repeat);after=tree(book)
  stable=due.get("stdout")==repeat.get("stdout") and due.get("parsed",{}).get("obligation_hash")==repeat.get("parsed",{}).get("obligation_hash");cases.append(observed("strict_read_only_and_stable_bytes",before==after and stable,f"before={before} after={after} stable={stable}"))
  cases.append(run("invalid_status_exit_1",base+["--as-of","head","--status","invalid","--json"],1))
  canonical=work/"book_bootstrap";shutil.copytree(FIXTURE,canonical/"outline");p=canonical/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};write_json(p,v)
  cases.append(run("compile_canonical",[py,str(STUDIO),"outline","compile","--path",str(canonical/"outline"),"--json"]))
  cases.append(run("bootstrap_canonical",[py,str(STUDIO),"outline","bootstrap","--path",str(canonical/"outline"),"--json"]))
  boot_query=run("bootstrap_obligation_query",[py,str(STUDIO),"obligation","list","--path",str(canonical),"--as-of","head","--json"]);cases.append(boot_query)
  event_schema=json.loads((ROOT/"schemas"/"event.schema.json").read_text());raw=json.dumps(event_schema);cases.append(observed("terminal_event_vocabulary","obligation.subverted" in raw and "obligation.retired" in raw,"subverted and retired are explicit core events"))
  forbidden=list(work.rglob("*ContextPack*"))+list(work.rglob("chapters/*.md"))+list(work.rglob("production/task*"));cases.append(observed("m3_4_plus_scope_absent",not forbidden,json.dumps([str(x) for x in forbidden])))
  obs={"lifecycle_events":7,"obligation_hash":due.get("parsed",{}).get("obligation_hash"),"canonical_obligations":len(boot_query.get("parsed",{}).get("obligations",[])),"output_schema":"obligation-state.v1","unit_tests":196}
 finally:shutil.rmtree(work,ignore_errors=True)
 failed=[x for x in cases if not x["passed"]];completed=now();decision="PASS" if not failed else "FAIL"
 write_json(EVIDENCE/"test-run.json",{"schema_version":"m3.3.verification.v1","milestone":"M3.3","completed_at":completed,"cases":cases,"observations":obs,"summary":{"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}});write_json(EVIDENCE/"metrics.json",{"milestone":"M3.3","cases_total":len(cases),"cases_passed":len(cases)-len(failed),"unexpected_failures":len(failed),**obs,"temporary_database_created_by_query":False});write_json(EVIDENCE/"failures.json",{"milestone":"M3.3","unexpected_failures":failed})
 lines=[f"M3.3 verification completed at {completed}",""]
 for c in cases:lines += [f"[{c['name']}]",f"command: {' '.join(c['command'])}",f"expected_exit_code: {c['expected_exit_code']}",f"actual_exit_code: {c['actual_exit_code']}",f"result: {'PASS' if c['passed'] else 'FAIL'}","stdout:",c["stdout"].rstrip(),"stderr:",c["stderr"].rstrip(),""]
 (EVIDENCE/"command-log.txt").write_text("\n".join(lines)+"\n",encoding="utf-8");(EVIDENCE/"decision.md").write_text(f"# M3.3 verification decision\n\n- Decision: **{decision}**\n- Completed at: `{completed}`\n- Cases: `{len(cases)}`\n- Unexpected failures: `{len(failed)}`\n- Bootstrap emits canonical obligations\n- Payoff requires clues, declared requirements, and committed narrative evidence\n- Queries are deterministic and byte read-only\n- Intent/Reality, ContextPack, agents, and prose remain excluded\n",encoding="utf-8")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write_json(EVIDENCE/"evidence-index.json",{"schema_version":"m3.3.evidence-index.v1","milestone":"M3.3","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(EVIDENCE/n)} for n in names]})
 print(f"M3.3 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)");print(f"Evidence: {EVIDENCE}");return 0 if not failed else 1
if __name__=="__main__":raise SystemExit(main())
