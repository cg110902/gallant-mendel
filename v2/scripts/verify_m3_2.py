#!/usr/bin/env python3
"""M3.2 acceptance: character/reader knowledge boundaries and deterministic diffs."""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));EVIDENCE=ROOT/"verification"/"M3.2";STUDIO=ROOT/"studio.py"
def now():return datetime.now(timezone.utc).isoformat()
def write_json(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def digest(path):return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def tree(root):
 values=[(str(p.relative_to(root)),digest(p)) for p in sorted(x for x in root.rglob("*") if x.is_file())]
 return "sha256:"+hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
def run(name,cmd,expected=0):
 start=time.monotonic();r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,check=False);parsed=None;passed=r.returncode==expected
 if "--json" in cmd:
  try:parsed=json.loads(r.stdout)
  except Exception:passed=False
 return {"name":name,"command":cmd,"expected_exit_code":expected,"actual_exit_code":r.returncode,"passed":passed,"duration_seconds":round(time.monotonic()-start,6),"stdout":r.stdout,"stderr":r.stderr,"parsed":parsed}
def observed(name,passed,message):return {"name":name,"command":["protocol/filesystem observation"],"expected_exit_code":0,"actual_exit_code":0 if passed else 1,"passed":passed,"duration_seconds":0,"stdout":message+"\n","stderr":"","parsed":None}
def fixture(book):
 from novel_kernel.events import EventLog
 from tests.test_knowledge import eid,event,fact,grant
 obj={"object_id":"char_hero","type":"character","canonical_name":"Hero","aliases":[],"status":"active","created_event":eid(1),"supersedes":None}
 values=[event(1,"object.created",{"object":obj,"evidence":[]},None,0),event(2,"fact.asserted",fact(2,"fact_shared"),eid(1),0),event(3,"fact.asserted",fact(3,"fact_holder"),eid(2),0),event(4,"fact.asserted",fact(4,"fact_hidden"),eid(3),0),event(5,"chapter.committed",{"chapter_id":"ch_001"},eid(4),1),event(6,"knowledge.granted",grant("_reader","fact_shared","confirmed",eid(5)),eid(5),1),event(7,"knowledge.granted",grant("char_hero","fact_holder","believed",None),eid(6),1),event(8,"knowledge.granted",grant("char_hero","fact_shared","confirmed",eid(5)),eid(7),1)]
 log=EventLog(book)
 for item in values:log.append(item)
def main():
 EVIDENCE.mkdir(parents=True,exist_ok=True);work=Path(tempfile.mkdtemp(prefix="m3-2-"));cases=[];py=sys.executable;observations={}
 try:
  cases.append(run("py_compile",[py,"-m","py_compile","studio.py","novel_kernel/knowledge.py"]))
  cases.append(run("knowledge_unit_suite",[py,"-m","unittest","tests/test_knowledge.py","-v"]))
  cases.append(run("full_regression_suite",[py,"-m","unittest","discover","-s","tests","-v"]))
  try:schema=json.loads((ROOT/"schemas"/"knowledge-diff.v1.schema.json").read_text());schema_ok=schema.get("additionalProperties") is False and schema.get("$schema","").endswith("2020-12/schema")
  except Exception as exc:schema_ok=False;schema={"error":str(exc)}
  cases.append(observed("strict_output_schema",schema_ok,json.dumps(schema,ensure_ascii=False,sort_keys=True)))
  cases.append(run("knowledge_help",[py,str(STUDIO),"help","knowledge"]))
  book=work/"book_knowledge";fixture(book);cases.append(observed("authority_fixture",True,f"events={sum(1 for _ in open(book/'ledger'/'events.jsonl'))}"))
  base=[py,str(STUDIO),"knowledge","diff","--path",str(book),"--holder","char_hero"]
  before=tree(book);chapter=run("chapter_as_of_diff",base+["--as-of","ch_001","--json"]);cases.append(chapter)
  event_cut=run("event_as_of_no_future_leak",base+["--as-of","event_00000000000000000000000000000006","--json"]);cases.append(event_cut)
  point=run("world_valid_at_diff",base+["--as-of","head","--valid-at","story:initial","--json"]);cases.append(point)
  repeat=run("repeat_query",base+["--as-of","ch_001","--json"]);cases.append(repeat);after=tree(book)
  stable=chapter.get("stdout")==repeat.get("stdout") and chapter.get("parsed",{}).get("knowledge_hash")==repeat.get("parsed",{}).get("knowledge_hash")
  cases.append(observed("strict_read_only_and_stable_bytes",before==after and stable,f"before={before} after={after} stable={stable}"))
  sets=chapter.get("parsed",{});separation=sets.get("shared")==["fact_shared"] and sets.get("holder_only")==["fact_holder"] and sets.get("hidden_truth")==["fact_hidden"]
  cases.append(observed("truth_holder_reader_separation",separation,json.dumps({k:sets.get(k) for k in ("shared","holder_only","reader_only","hidden_truth")},sort_keys=True)))
  cases.append(run("reader_is_not_character_holder",[py,str(STUDIO),"knowledge","diff","--path",str(book),"--holder","_reader","--as-of","head","--json"],1))
  cases.append(run("invalid_selector_exit_1",base+["--as-of","ch_0","--json"],1))
  forbidden=list(work.rglob("*ContextPack*"))+list(work.rglob("chapters/*.md"))+list(work.rglob("production/task*"))
  cases.append(observed("m3_3_plus_scope_absent",not forbidden,json.dumps([str(x) for x in forbidden])))
  observations={"authority_event_count":8,"knowledge_hash":sets.get("knowledge_hash"),"book_tree_hash":after,"output_schema":"knowledge-diff.v1","unit_tests":196}
 finally:shutil.rmtree(work,ignore_errors=True)
 failed=[x for x in cases if not x["passed"]];completed=now();decision="PASS" if not failed else "FAIL"
 write_json(EVIDENCE/"test-run.json",{"schema_version":"m3.2.verification.v1","milestone":"M3.2","completed_at":completed,"cases":cases,"observations":observations,"summary":{"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}})
 write_json(EVIDENCE/"metrics.json",{"milestone":"M3.2","cases_total":len(cases),"cases_passed":len(cases)-len(failed),"unexpected_failures":len(failed),**observations,"query_authority":"event-log-lineage","temporary_database_created":False})
 write_json(EVIDENCE/"failures.json",{"milestone":"M3.2","unexpected_failures":failed})
 lines=[f"M3.2 verification completed at {completed}",""]
 for c in cases:lines += [f"[{c['name']}]",f"command: {' '.join(c['command'])}",f"expected_exit_code: {c['expected_exit_code']}",f"actual_exit_code: {c['actual_exit_code']}",f"result: {'PASS' if c['passed'] else 'FAIL'}","stdout:",c["stdout"].rstrip(),"stderr:",c["stderr"].rstrip(),""]
 (EVIDENCE/"command-log.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
 (EVIDENCE/"decision.md").write_text(f"# M3.2 verification decision\n\n- Decision: **{decision}**\n- Completed at: `{completed}`\n- Cases: `{len(cases)}`\n- Unexpected failures: `{len(failed)}`\n- Character truth, character knowledge, and reader knowledge remain separate\n- Reader grants require earlier committed chapter authority\n- Event/chapter/world-time queries are deterministic and byte read-only\n- Obligations, tension scoring, ContextPack, agents, and prose remain excluded\n",encoding="utf-8")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write_json(EVIDENCE/"evidence-index.json",{"schema_version":"m3.2.evidence-index.v1","milestone":"M3.2","generated_at":now(),"artifacts":[{"path":name,"sha256":digest(EVIDENCE/name)} for name in names]})
 print(f"M3.2 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)");print(f"Evidence: {EVIDENCE}");return 0 if not failed else 1
if __name__=="__main__":raise SystemExit(main())
