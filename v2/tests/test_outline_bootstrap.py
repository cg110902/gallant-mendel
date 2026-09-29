from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.events import EventLog,build_event
from novel_kernel.outline_bootstrap import BootstrapHumanGateError,BootstrapIntegrityError,OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.projection import ProjectionStore
ROOT=Path(__file__).resolve().parents[1]; FIXTURE=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"; STUDIO=ROOT/"studio.py"

class BootstrapTests(unittest.TestCase):
 def book(self,parent:Path,approved:bool=True)->Path:
  book=parent/"book_demo"; shutil.copytree(FIXTURE,book/"outline")
  if approved:
   p=book/"outline"/"00-manifest.json"; v=json.loads(p.read_text()); v["status"]="approved"; v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"}; p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n")
  return book
 def prepare(self,parent:Path)->Path:
  book=self.book(parent); OutlineCompiler().compile(book/"outline"); return book
 def test_bootstrap_commits_deterministic_batch_and_projection(self):
  with tempfile.TemporaryDirectory() as t:
   book=self.prepare(Path(t)); result=OutlineBootstrapper().bootstrap(book/"outline",expected_book_id="book_demo")
   self.assertEqual(result.event_count,25); self.assertFalse(result.reused_bootstrap)
   events=EventLog(book).read_events(); self.assertEqual(events[-1]["event_id"],result.head_event_id)
   counts={kind:sum(e["event_type"]==kind for e in events) for kind in {e["event_type"] for e in events}}
   self.assertEqual(counts,{"object.created":9,"facet.asserted":11,"fact.asserted":1,"relation.asserted":2,"obligation.created":1,"audit.completed":1})
   self.assertEqual(events[-1]["payload"]["approval"]["owner"],"author")
   self.assertTrue(all(e["recorded_at"]=="2026-09-29T18:00:00+08:00" and e["story_seq"]==0 for e in events))
   state=ProjectionStore(book).export_state(); self.assertEqual(len(state["objects"]),9); self.assertEqual(len(state["facets"]),11); self.assertEqual(len(state["facts"]),1); self.assertEqual(len(state["relations"]),2)
 def test_same_approved_generation_has_identical_event_bytes_across_books(self):
  with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
   one=self.prepare(Path(a)); two=self.prepare(Path(b)); OutlineBootstrapper().bootstrap(one/"outline"); OutlineBootstrapper().bootstrap(two/"outline")
   self.assertEqual((one/"ledger"/"events.jsonl").read_bytes(),(two/"ledger"/"events.jsonl").read_bytes())
 def test_repeated_bootstrap_is_idempotent_and_recovers_deleted_projection(self):
  with tempfile.TemporaryDirectory() as t:
   book=self.prepare(Path(t)); first=OutlineBootstrapper().bootstrap(book/"outline"); before=(book/"ledger"/"events.jsonl").read_bytes(); (book/"state"/"state.db").unlink()
   second=OutlineBootstrapper().bootstrap(book/"outline"); self.assertTrue(second.reused_bootstrap); self.assertEqual(before,(book/"ledger"/"events.jsonl").read_bytes()); self.assertEqual(first.projection_state_hash,second.projection_state_hash)
 def test_draft_manifest_stops_at_human_gate_without_authority(self):
  with tempfile.TemporaryDirectory() as t:
   book=self.book(Path(t),approved=False); OutlineCompiler().compile(book/"outline")
   with self.assertRaises(BootstrapHumanGateError): OutlineBootstrapper().bootstrap(book/"outline")
   self.assertFalse((book/"ledger").exists()); self.assertFalse((book/"state").exists())
 def test_compiled_source_mismatch_stops_before_authority(self):
  with tempfile.TemporaryDirectory() as t:
   book=self.prepare(Path(t)); p=book/"outline"/"02-theme.json"; p.write_text('{"changed":true}')
   with self.assertRaises(BootstrapHumanGateError): OutlineBootstrapper().bootstrap(book/"outline")
   self.assertFalse((book/"ledger").exists())
 def test_partial_bootstrap_prefix_is_integrity_failure(self):
  with tempfile.TemporaryDirectory() as t:
   book=self.prepare(Path(t)); bootstrap=OutlineBootstrapper(); report=bootstrap.validator.validate(book/"outline"); owner,at=bootstrap._approval(report.manifest); pointer=json.loads((book/"compiled"/"current.json").read_text()); events=bootstrap._plan("book_demo",pointer["compile_id"],book/"compiled"/pointer["generation"],owner,at)
   EventLog(book).append_many(events[:3]); before=(book/"ledger"/"events.jsonl").read_bytes()
   with self.assertRaises(BootstrapIntegrityError): bootstrap.bootstrap(book/"outline")
   self.assertEqual(before,(book/"ledger"/"events.jsonl").read_bytes())
 def test_unrelated_existing_authority_requires_human_resolution(self):
  with tempfile.TemporaryDirectory() as t:
   book=self.prepare(Path(t)); event=build_event(event_type="audit.completed",book_id="book_demo",branch_id="main",parent_event_id=None,story_seq=0,recorded_at="2026-09-29T18:00:00+08:00",actor_type="human",actor_id="manual",payload={"note":"existing"}); EventLog(book).append(event)
   with self.assertRaises(BootstrapHumanGateError): OutlineBootstrapper().bootstrap(book/"outline")
 def test_new_compile_after_bootstrap_cannot_reinitialize_authority(self):
  with tempfile.TemporaryDirectory() as t:
   book=self.prepare(Path(t)); OutlineBootstrapper().bootstrap(book/"outline"); before=(book/"ledger"/"events.jsonl").read_bytes(); (book/"outline"/"02-theme.json").write_text('{"changed":true}'); OutlineCompiler().compile(book/"outline")
   with self.assertRaises(BootstrapHumanGateError): OutlineBootstrapper().bootstrap(book/"outline")
   self.assertEqual(before,(book/"ledger"/"events.jsonl").read_bytes())
 def test_bootstrap_creates_no_contextpack_or_prose(self):
  with tempfile.TemporaryDirectory() as t:
   book=self.prepare(Path(t)); OutlineBootstrapper().bootstrap(book/"outline")
   self.assertFalse((book/"production").exists()); self.assertFalse((book/"chapters").exists()); self.assertEqual(list(book.rglob("*ContextPack*")),[])

class BootstrapCliTests(unittest.TestCase):
 def test_cli_first_and_reused_bootstrap(self):
  with tempfile.TemporaryDirectory() as t:
   helper=BootstrapTests(); book=helper.book(Path(t)); compile_cmd=[sys.executable,str(STUDIO),"outline","compile","--path",str(book/"outline"),"--json"]; boot=[sys.executable,str(STUDIO),"outline","bootstrap","--path",str(book/"outline"),"--json"]
   self.assertEqual(subprocess.run(compile_cmd,cwd=ROOT,capture_output=True).returncode,0)
   first=subprocess.run(boot,cwd=ROOT,text=True,capture_output=True); second=subprocess.run(boot,cwd=ROOT,text=True,capture_output=True)
   self.assertEqual(first.returncode,0,first.stderr); self.assertEqual(second.returncode,0,second.stderr); self.assertFalse(json.loads(first.stdout)["reused_bootstrap"]); self.assertTrue(json.loads(second.stdout)["reused_bootstrap"])
 def test_cli_draft_returns_human_gate_four(self):
  with tempfile.TemporaryDirectory() as t:
   helper=BootstrapTests(); book=helper.book(Path(t),approved=False); OutlineCompiler().compile(book/"outline")
   result=subprocess.run([sys.executable,str(STUDIO),"outline","bootstrap","--path",str(book/"outline"),"--json"],cwd=ROOT,text=True,capture_output=True)
   self.assertEqual(result.returncode,4); self.assertEqual(json.loads(result.stdout)["exit_code"],4)
if __name__=="__main__": unittest.main()
