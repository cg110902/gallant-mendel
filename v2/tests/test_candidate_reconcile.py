from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.candidate_reconcile import CandidateReconciler
from novel_kernel.extraction import CandidateExtractor
from novel_kernel.events import EventLog,build_event
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionIntegrityError,ProductionPlanner,ProductionStaleError
from novel_kernel.writer_runtime import WriterRunController
ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
class CandidateReconcileTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_demo";shutil.copytree(FIX,self.book/"outline");p=self.book/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v));OutlineCompiler().compile(self.book/"outline");OutlineBootstrapper().bootstrap(self.book/"outline");plan=ProductionPlanner().plan(self.book,chapter_id="ch_001");self.run_id=plan.run_id;self.run=Path(plan.run_path);ContextPackBuilder().build(self.book,run_id=self.run_id);c=WriterRunController();c.start_task(self.book,task_id=plan.task_id);self.controller=c
 def tearDown(self):self.temp.cleanup()
 def prepare(self,annotation):
  prose=f'凌云。<!-- novel:claim {json.dumps(annotation,separators=(",",":"))} -->' if annotation else '凌云。';(self.run/"prose.md").write_text(prose);self.controller.request_review(self.book,run_id=self.run_id);self.controller.decide_review(self.book,run_id=self.run_id,decision="approve",actor="editor");CandidateExtractor().extract(self.book,run_id=self.run_id)
 def test_required_change_is_reconciled_without_authority_write(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});before=(self.book/"ledger"/"events.jsonl").read_bytes();r=CandidateReconciler().reconcile(self.book,run_id=self.run_id);self.assertTrue(r.ok);self.assertEqual(r.state,"reconciled");self.assertEqual(r.counts["intent_fulfilled"],1);self.assertEqual(before,(self.book/"ledger"/"events.jsonl").read_bytes())
 def test_conflicting_active_fact_is_hard_block(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"age","value":20});r=CandidateReconciler().reconcile(self.book,run_id=self.run_id);self.assertFalse(r.ok);self.assertTrue(r.has_hard_violation);self.assertEqual(r.counts["contradiction"],1);self.assertEqual(r.state,"reconcile_blocked");x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"reconcile","--path",str(self.book),"--run",self.run_id,"--json"],capture_output=True);self.assertEqual(x.returncode,3)
 def test_no_change_and_missing_intent_require_review(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"age","value":19});r=CandidateReconciler().reconcile(self.book,run_id=self.run_id);self.assertEqual(r.counts["no_change"],1);self.assertEqual(r.counts["intent_missing"],1);self.assertTrue(r.requires_human_review);self.assertEqual(r.state,"reconcile_review");x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"reconcile","--path",str(self.book),"--run",self.run_id,"--json"],capture_output=True);self.assertEqual(x.returncode,4)
 def test_emergent_candidate_requires_review(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"mood","value":"alert"});r=CandidateReconciler().reconcile(self.book,run_id=self.run_id);self.assertEqual(r.counts["emergent_candidate"],1);self.assertEqual(r.state,"reconcile_review")
 def test_broken_evidence_is_rejected(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});p=self.run/"evidence.json";v=json.loads(p.read_text());v["bindings"][0]["quote"]="tamper";p.write_text(json.dumps(v))
  with self.assertRaises(ProductionIntegrityError):CandidateReconciler().reconcile(self.book,run_id=self.run_id)
 def test_stale_authority_is_rejected(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});log=EventLog(self.book);head=log.read_lineage("main")[-1]["event_id"];log.append(build_event(event_type="audit.completed",book_id="book_demo",branch_id="main",parent_event_id=head,story_seq=0,recorded_at="2026-09-29T20:00:00+08:00",actor_type="human",actor_id="test",payload={"later":True}))
  with self.assertRaises(ProductionStaleError):CandidateReconciler().reconcile(self.book,run_id=self.run_id)
 def test_idempotence_and_cli_exit_codes(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});a=CandidateReconciler().reconcile(self.book,run_id=self.run_id);b=CandidateReconciler().reconcile(self.book,run_id=self.run_id);self.assertEqual(a.reconcile_hash,b.reconcile_hash);self.assertTrue(b.reused)
  x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"reconcile","--path",str(self.book),"--run",self.run_id,"--json"],text=True,capture_output=True);self.assertEqual(x.returncode,0,x.stderr);self.assertEqual(json.loads(x.stdout)["state"],"reconciled")
if __name__=="__main__":unittest.main()
