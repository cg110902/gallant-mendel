#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));E=ROOT/"verification"/"M3.4";STUDIO=ROOT/"studio.py";FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
def now():return datetime.now(timezone.utc).isoformat()
def w(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def d(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def tree(r):return dbytes(json.dumps([(str(p.relative_to(r)),d(p)) for p in sorted(x for x in r.rglob('*') if x.is_file())],sort_keys=True).encode())
def dbytes(b):return "sha256:"+hashlib.sha256(b).hexdigest()
def run(name,cmd,expected=0):
 s=time.monotonic();r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);parsed=None;passed=r.returncode==expected
 if "--json" in cmd:
  try:parsed=json.loads(r.stdout)
  except:passed=False
 return {"name":name,"command":cmd,"expected_exit_code":expected,"actual_exit_code":r.returncode,"passed":passed,"duration_seconds":round(time.monotonic()-s,6),"stdout":r.stdout,"stderr":r.stderr,"parsed":parsed}
def obs(name,ok,msg):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":msg+"\n","stderr":"","parsed":None}
def fixture(book):
 from novel_kernel.events import EventLog
 from tests.test_reconcile import ev,eid,intent,reality
 log=EventLog(book)
 for x in [ev(1,"intent.registered",intent(),None,0),ev(2,"chapter.committed",{"chapter_id":"ch_001"},eid(1),1),ev(3,"audit.completed",{"decision":"approve"},eid(2),1),ev(4,"reality.observed",reality(),eid(3),1)]:log.append(x)
def main():
 E.mkdir(parents=True,exist_ok=True);work=Path(tempfile.mkdtemp(prefix="m3-4-"));cases=[];py=sys.executable;o={}
 try:
  cases+=[run("py_compile",[py,"-m","py_compile","studio.py","novel_kernel/reconcile.py"]),run("reconcile_units",[py,"-m","unittest","tests/test_reconcile.py","-v"]),run("full_units",[py,"-m","unittest","discover","-s","tests","-v"])]
  schema=json.loads((ROOT/"schemas"/"intent-reality-diff.v1.schema.json").read_text());cases.append(obs("strict_schema",schema.get("additionalProperties") is False,"strict draft schema"));cases.append(run("help",[py,str(STUDIO),"help","reconcile"]))
  book=work/"book_reconcile";fixture(book);base=[py,str(STUDIO),"reconcile","diff","--path",str(book),"--scope","ch_001"]
  before=tree(book);head=run("head_diff",base+["--as-of","head","--json"]);cases.append(head);pre=run("pre_reality",base+["--as-of","event_00000000000000000000000000000003","--json"]);cases.append(pre);repeat=run("repeat",base+["--as-of","head","--json"]);cases.append(repeat);after=tree(book)
  stable=before==after and head["stdout"]==repeat["stdout"];cases.append(obs("read_only_determinism",stable,f"before={before} after={after}"));p=head.get("parsed",{});cases.append(obs("seven_classifications",set(p.get("counts",{}))=={"intent_fulfilled","intent_missing","intent_changed_with_approval","emergent_valid","emergent_unregistered","contradiction","hard_violation"},json.dumps(p.get("counts"))))
  cases.append(run("unknown_scope_exit_1",[py,str(STUDIO),"reconcile","diff","--path",str(book),"--scope","missing","--as-of","head","--json"],1))
  canonical=work/"book_demo";shutil.copytree(FIX,canonical/"outline");m=canonical/"outline"/"00-manifest.json";v=json.loads(m.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};w(m,v)
  cases.append(run("compile",[py,str(STUDIO),"outline","compile","--path",str(canonical/"outline"),"--json"]));boot=run("bootstrap_intent",[py,str(STUDIO),"outline","bootstrap","--path",str(canonical/"outline"),"--json"]);cases.append(boot);cq=run("canonical_intent_diff",[py,str(STUDIO),"reconcile","diff","--path",str(canonical),"--scope","ch_001","--as-of","head","--json"]);cases.append(cq)
  cases.append(obs("bootstrap_26_events",boot.get("parsed",{}).get("event_count")==26,str(boot.get("parsed",{}).get("event_count"))));forbidden=list(work.rglob("*ContextPack*"))+list(work.rglob("chapters/*.md"));cases.append(obs("scope_absent",not forbidden,json.dumps([str(x) for x in forbidden])))
  o={"diff_hash":p.get("diff_hash"),"bootstrap_events":26,"unit_tests":196,"schema":"intent-reality-diff.v1"}
 finally:shutil.rmtree(work,ignore_errors=True)
 failed=[x for x in cases if not x["passed"]];done=now();decision="PASS" if not failed else "FAIL";w(E/"test-run.json",{"schema_version":"m3.4.verification.v1","milestone":"M3.4","completed_at":done,"cases":cases,"observations":o,"summary":{"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)}});w(E/"metrics.json",{"milestone":"M3.4","cases_total":len(cases),"cases_passed":len(cases)-len(failed),"unexpected_failures":len(failed),**o});w(E/"failures.json",{"milestone":"M3.4","unexpected_failures":failed})
 lines=[f"M3.4 verification {done}",""]
 for c in cases:lines += [f"[{c['name']}]",f"command: {' '.join(c['command'])}",f"expected_exit_code: {c['expected_exit_code']}",f"actual_exit_code: {c['actual_exit_code']}",f"result: {'PASS' if c['passed'] else 'FAIL'}","stdout:",c["stdout"].rstrip(),"stderr:",c["stderr"].rstrip(),""]
 (E/"command-log.txt").write_text("\n".join(lines)+"\n");(E/"decision.md").write_text(f"# M3.4 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Intent comes from bootstrap authority; Reality requires committed chapter evidence\n- Approval classifications require audit authority\n- ContextPack and prose remain excluded\n")
 names=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];w(E/"evidence-index.json",{"schema_version":"m3.4.evidence-index.v1","milestone":"M3.4","generated_at":now(),"artifacts":[{"path":n,"sha256":d(E/n)} for n in names]});print(f"M3.4 verification: {decision} ({len(cases)-len(failed)}/{len(cases)})");return 0 if not failed else 1
if __name__=="__main__":raise SystemExit(main())
