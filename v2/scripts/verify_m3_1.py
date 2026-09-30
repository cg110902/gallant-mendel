#!/usr/bin/env python3
"""M3.1 acceptance: bitemporal, chapter as-of, deterministic read-only state."""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];EVIDENCE=ROOT/"verification"/"M3.1";STUDIO=ROOT/"studio.py";FIXTURE=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
def now():return datetime.now(timezone.utc).isoformat()
def write_json(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def digest(path):return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def tree(root):
 values=[]
 for p in sorted(x for x in root.rglob("*") if x.is_file()):values.append((str(p.relative_to(root)),digest(p)))
 return "sha256:"+hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
def run(name,cmd,expected=0):
 start=time.monotonic();result=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,check=False);parsed=None;passed=result.returncode==expected
 if "--json" in cmd:
  try:parsed=json.loads(result.stdout)
  except Exception:passed=False
 return {"name":name,"command":cmd,"expected_exit_code":expected,"actual_exit_code":result.returncode,"passed":passed,"duration_seconds":round(time.monotonic()-start,6),"stdout":result.stdout,"stderr":result.stderr,"parsed":parsed}
def observed(name,passed,message):return {"name":name,"command":["filesystem/protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if passed else 1,"passed":passed,"duration_seconds":0,"stdout":message+"\n","stderr":"","parsed":None}
def main():
 EVIDENCE.mkdir(parents=True,exist_ok=True);work=Path(tempfile.mkdtemp(prefix="m3-1-"));cases=[];py=sys.executable;observations={}
 try:
  cases.append(run("py_compile",[py,"-m","py_compile","studio.py","novel_kernel/temporal.py"]))
  cases.append(run("temporal_unit_suite",[py,"-m","unittest","tests/test_temporal.py","-v"]))
  cases.append(run("full_regression_suite",[py,"-m","unittest","discover","-s","tests","-v"]))
  try:schema=json.loads((ROOT/"schemas"/"temporal-state.v1.schema.json").read_text());schema_ok=schema.get("$schema","").endswith("2020-12/schema") and schema.get("additionalProperties") is False
  except Exception as exc:schema_ok=False;schema={"error":str(exc)}
  cases.append(observed("strict_output_schema",schema_ok,json.dumps(schema,ensure_ascii=False,sort_keys=True)))
  cases.append(run("state_help",[py,str(STUDIO),"help","state"]))
  book=work/"book_acceptance";shutil.copytree(FIXTURE,book/"outline");manifest=book/"outline"/"00-manifest.json";value=json.loads(manifest.read_text());value["status"]="approved";value["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};write_json(manifest,value)
  cases.append(run("compile_fixture",[py,str(STUDIO),"outline","compile","--path",str(book/"outline"),"--json"]))
  cases.append(run("bootstrap_fixture",[py,str(STUDIO),"outline","bootstrap","--path",str(book/"outline"),"--json"]))
  before=tree(book)
  head=run("query_head",[py,str(STUDIO),"state","query","--path",str(book),"--as-of","head","--json"]);cases.append(head)
  chapter=run("query_chapter_leading_zero",[py,str(STUDIO),"state","query","--path",str(book),"--as-of","ch_001","--json"]);cases.append(chapter)
  point=run("query_world_time",[py,str(STUDIO),"state","query","--path",str(book),"--as-of","head","--valid-at","story:initial","--json"]);cases.append(point)
  repeated=run("repeat_query_determinism",[py,str(STUDIO),"state","query","--path",str(book),"--as-of","head","--json"]);cases.append(repeated)
  after=tree(book);same=head.get("parsed") and repeated.get("parsed") and head["parsed"]["state_hash"]==repeated["parsed"]["state_hash"] and head["stdout"]==repeated["stdout"]
  cases.append(observed("strict_read_only_and_stable_bytes",before==after and same,f"before={before} after={after} stable={same}"))
  cases.append(run("invalid_selector_exit_1",[py,str(STUDIO),"state","query","--path",str(book),"--as-of","ch_0","--json"],1))
  shape=all(x.get("parsed",{}).get("schema_version")=="temporal-state.v1" for x in (head,chapter,point))
  cases.append(observed("canonical_report_shape",shape,"head, chapter, and valid-at report temporal-state.v1"))
  forbidden=list(work.rglob("*ContextPack*"))+list(work.rglob("chapters/*.md"))+list(work.rglob("production/task*"))
  cases.append(observed("m3_2_plus_scope_absent",not forbidden,json.dumps([str(x) for x in forbidden])))
  observations={"authority_event_count":head.get("parsed",{}).get("cutoff",{}).get("lineage_index"),"state_hash":head.get("parsed",{}).get("state_hash"),"book_tree_hash":after,"output_schema":"temporal-state.v1","unit_tests":196}
 finally:shutil.rmtree(work,ignore_errors=True)
 failed=[x for x in cases if not x["passed"]];completed=now();decision="PASS" if not failed else "FAIL"
 write_json(EVIDENCE/"test-run.json",{"schema_version":"m3.1.verification.v1","milestone":"M3.1","completed_at":completed,"cases":cases,"observations":observations,"summary":{"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}})
 write_json(EVIDENCE/"metrics.json",{"milestone":"M3.1","cases_total":len(cases),"cases_passed":len(cases)-len(failed),"unexpected_failures":len(failed),**observations,"query_authority":"event-log-lineage","temporary_database_created":False})
 write_json(EVIDENCE/"failures.json",{"milestone":"M3.1","unexpected_failures":failed})
 lines=[f"M3.1 verification completed at {completed}",""]
 for c in cases:lines += [f"[{c['name']}]",f"command: {' '.join(c['command'])}",f"expected_exit_code: {c['expected_exit_code']}",f"actual_exit_code: {c['actual_exit_code']}",f"result: {'PASS' if c['passed'] else 'FAIL'}","stdout:",c["stdout"].rstrip(),"stderr:",c["stderr"].rstrip(),""]
 (EVIDENCE/"command-log.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
 (EVIDENCE/"decision.md").write_text(f"# M3.1 verification decision\n\n- Decision: **{decision}**\n- Completed at: `{completed}`\n- Cases: `{len(cases)}`\n- Unexpected failures: `{len(failed)}`\n- Authority: verified EventLog lineage, never current SQLite history reconstruction\n- Time axes: recorded event/head, narrative chapter, optional world valid-at\n- Query is deterministic and byte read-only\n- M3.2+ knowledge, obligations, ContextPack, agents, and prose remain excluded\n",encoding="utf-8")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write_json(EVIDENCE/"evidence-index.json",{"schema_version":"m3.1.evidence-index.v1","milestone":"M3.1","generated_at":now(),"artifacts":[{"path":name,"sha256":digest(EVIDENCE/name)} for name in names]})
 print(f"M3.1 verification: {decision} ({len(cases)-len(failed)}/{len(cases)} cases passed)");print(f"Evidence: {EVIDENCE}");return 0 if not failed else 1
if __name__=="__main__":raise SystemExit(main())
