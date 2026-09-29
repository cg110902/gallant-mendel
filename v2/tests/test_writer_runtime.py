from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionIntegrityError,ProductionPlanner
from novel_kernel.writer_runtime import OfflineWriterRuntime,RuntimeResult,WriterRunController
ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
class FailingRuntime:
 name="fail"
 def invoke(self,request):return RuntimeResult(False,"","","partial out\n","provider unavailable\n","provider unavailable")
class MutatingRuntime:
 name="mutate"
 def __init__(self,book):self.book=book
 def invoke(self,request):
  with (self.book/"ledger"/"events.jsonl").open("ab") as f:f.write(b"tamper\n")
  return RuntimeResult(True,"bad","","","")
class WriterRuntimeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_demo";shutil.copytree(FIX,self.book/"outline");p=self.book/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v));OutlineCompiler().compile(self.book/"outline");OutlineBootstrapper().bootstrap(self.book/"outline");self.plan=ProductionPlanner().plan(self.book,chapter_id="ch_001");ContextPackBuilder().build(self.book,run_id=self.plan.run_id)
 def tearDown(self):self.temp.cleanup()
 def test_offline_start_writes_only_candidate_run_artifacts(self):
  authority=(self.book/"ledger"/"events.jsonl").read_bytes();r=WriterRunController().start_task(self.book,task_id=self.plan.task_id);self.assertEqual(r.state,"draft_ready");self.assertTrue((Path(self.plan.run_path)/"prose.md").is_file());self.assertEqual(authority,(self.book/"ledger"/"events.jsonl").read_bytes());self.assertFalse((self.book/"chapters").exists())
  attempt=Path(self.plan.run_path)/"attempts"/"attempt_001";self.assertTrue(all((attempt/n).is_file() for n in ("request.json","result.json","stdout.log","stderr.log","prose.md","writer-notes.md")))
 def test_failed_attempt_is_evidenced_and_resume_uses_new_attempt(self):
  c=WriterRunController({"fail":FailingRuntime(),"offline":OfflineWriterRuntime()});failed=c.start_task(self.book,task_id=self.plan.task_id,runtime_name="fail");self.assertFalse(failed.ok);self.assertEqual(failed.state,"writer_failed");ready=c.resume(self.book,run_id=self.plan.run_id);self.assertEqual(ready.state,"draft_ready");self.assertTrue((Path(self.plan.run_path)/"attempts"/"attempt_002"/"result.json").is_file())
 def test_abort_is_idempotent_and_blocks_start(self):
  c=WriterRunController();a=c.abort(self.book,run_id=self.plan.run_id);b=c.abort(self.book,run_id=self.plan.run_id);self.assertEqual(a,b)
  with self.assertRaises(Exception):c.start_task(self.book,task_id=self.plan.task_id)
 def test_context_tamper_and_unknown_runtime_are_rejected(self):
  with self.assertRaises(Exception):WriterRunController().start_task(self.book,task_id=self.plan.task_id,runtime_name="missing")
  p=Path(self.plan.run_path)/"context-pack.json";value=json.loads(p.read_text());value["objective"]="tampered";p.write_text(json.dumps(value))
  with self.assertRaises(Exception):WriterRunController().start_task(self.book,task_id=self.plan.task_id)
 def test_authority_mutation_is_detected_and_blocks_run(self):
  c=WriterRunController({"mutate":MutatingRuntime(self.book)})
  with self.assertRaises(ProductionIntegrityError):c.start_task(self.book,task_id=self.plan.task_id,runtime_name="mutate")
  self.assertEqual(json.loads((Path(self.plan.run_path)/"status.json").read_text())["state"],"violated")
 def test_human_review_approve_binds_prose_hash(self):
  c=WriterRunController();c.start_task(self.book,task_id=self.plan.task_id);pending=c.request_review(self.book,run_id=self.plan.run_id);self.assertEqual(pending.state,"human_review");approved=c.decide_review(self.book,run_id=self.plan.run_id,decision="approve",actor="editor");self.assertEqual(approved.state,"extraction_ready");self.assertTrue((Path(self.plan.run_path)/"reviews"/"review_001"/"decision.json").is_file())
 def test_human_review_detects_edit_and_rework_can_resume(self):
  c=WriterRunController();c.start_task(self.book,task_id=self.plan.task_id);c.request_review(self.book,run_id=self.plan.run_id);p=Path(self.plan.run_path)/"prose.md";p.write_text(p.read_text()+"human edit")
  with self.assertRaises(Exception):c.decide_review(self.book,run_id=self.plan.run_id,decision="approve",actor="editor")
  # Restore the frozen candidate, request rework, then create a new writer attempt.
  p.write_bytes((Path(self.plan.run_path)/"attempts"/"attempt_001"/"prose.md").read_bytes());rework=c.decide_review(self.book,run_id=self.plan.run_id,decision="rework",actor="editor",note="revise");self.assertEqual(rework.state,"needs_rework");self.assertEqual(c.resume(self.book,run_id=self.plan.run_id).attempt_id,"attempt_002")
 def test_cli_review_and_decide(self):
  c=WriterRunController();c.start_task(self.book,task_id=self.plan.task_id);base=[sys.executable,str(ROOT/"studio.py")];review=subprocess.run(base+["run","review","--path",str(self.book),"--run",self.plan.run_id,"--json"],text=True,capture_output=True);self.assertEqual(review.returncode,0,review.stderr)
  decide=subprocess.run(base+["run","decide","--path",str(self.book),"--run",self.plan.run_id,"--decision","approve","--actor","editor","--json"],text=True,capture_output=True);self.assertEqual(decide.returncode,0,decide.stderr);self.assertEqual(json.loads(decide.stdout)["state"],"extraction_ready")
 def test_cli_start_status_and_invalid_transition(self):
  base=[sys.executable,str(ROOT/"studio.py")];start=subprocess.run(base+["run","start","--path",str(self.book),"--task",self.plan.task_id,"--json"],text=True,capture_output=True);self.assertEqual(start.returncode,0,start.stderr);self.assertEqual(json.loads(start.stdout)["state"],"draft_ready")
  status=subprocess.run(base+["run","status","--path",str(self.book),"--run",self.plan.run_id,"--json"],text=True,capture_output=True);self.assertEqual(status.returncode,0,status.stderr);self.assertEqual(json.loads(status.stdout)["prose_path"],"prose.md")
  again=subprocess.run(base+["run","start","--path",str(self.book),"--task",self.plan.task_id,"--json"],text=True,capture_output=True);self.assertEqual(again.returncode,1)
if __name__=="__main__":unittest.main()
