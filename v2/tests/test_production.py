from __future__ import annotations
import json,shutil,tempfile,unittest
from pathlib import Path
import subprocess,sys
from novel_kernel.events import EventLog,build_event
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionPlanner,ProductionStaleError
ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
class ProductionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_demo";shutil.copytree(FIX,self.book/"outline");p=self.book/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v));OutlineCompiler().compile(self.book/"outline");OutlineBootstrapper().bootstrap(self.book/"outline")
 def tearDown(self):self.temp.cleanup()
 def test_plan_and_context_are_deterministic_and_scoped(self):
  before=(self.book/"ledger"/"events.jsonl").read_bytes();a=ProductionPlanner().plan(self.book,chapter_id="ch_001");b=ProductionPlanner().plan(self.book,chapter_id="ch_001");self.assertEqual(a.task_id,b.task_id);self.assertTrue(b.reused)
  c=ContextPackBuilder().build(self.book,run_id=a.run_id);d=ContextPackBuilder().build(self.book,run_id=a.run_id);self.assertEqual(c.context_hash,d.context_hash);self.assertEqual(before,(self.book/"ledger"/"events.jsonl").read_bytes());self.assertFalse((self.book/"chapters").exists());self.assertFalse((Path(a.run_path)/"prose.md").exists())
  pack=json.loads(Path(c.context_path).read_text());self.assertEqual(pack["constraints"]["pov"],"char_lin_yun");self.assertIn("append_events",pack["forbidden_actions"])
 def test_dag_has_future_gates(self):
  r=ProductionPlanner().plan(self.book,chapter_id="ch_001");task=json.loads(Path(r.task_path).read_text());self.assertEqual([x["node_id"] for x in task["dag"]],["draft","extract","audit","commit"]);self.assertEqual([x["enabled"] for x in task["dag"]],[True,False,False,False])
 def test_stale_head_blocks_context(self):
  r=ProductionPlanner().plan(self.book,chapter_id="ch_001");log=EventLog(self.book);head=log.read_lineage("main")[-1]["event_id"];log.append(build_event(event_type="audit.completed",book_id="book_demo",branch_id="main",parent_event_id=head,story_seq=0,recorded_at="2026-09-29T19:00:00+08:00",actor_type="human",actor_id="manual",payload={"later":True}))
  with self.assertRaises(ProductionStaleError):ContextPackBuilder().build(self.book,run_id=r.run_id)
 def test_stale_compile_pointer_blocks_context(self):
  r=ProductionPlanner().plan(self.book,chapter_id="ch_001");pointer=self.book/"compiled"/"current.json";value=json.loads(pointer.read_text());value["compile_id"]="sha256:"+"0"*64;pointer.write_text(json.dumps(value))
  with self.assertRaises(ProductionStaleError):ContextPackBuilder().build(self.book,run_id=r.run_id)
 def test_only_next_ready_chapter_can_plan(self):
  with self.assertRaises(Exception):ProductionPlanner().plan(self.book,chapter_id="ch_002")
 def test_cli_plan_and_build(self):
  plan=subprocess.run([sys.executable,str(ROOT/"studio.py"),"plan","chapter","--path",str(self.book),"--chapter","ch_001","--json"],text=True,capture_output=True);self.assertEqual(plan.returncode,0,plan.stderr);run=json.loads(plan.stdout)["run_id"]
  build=subprocess.run([sys.executable,str(ROOT/"studio.py"),"context","build","--path",str(self.book),"--run",run,"--json"],text=True,capture_output=True);self.assertEqual(build.returncode,0,build.stderr);self.assertEqual(json.loads(build.stdout)["state"],"context_ready")
if __name__=="__main__":unittest.main()
