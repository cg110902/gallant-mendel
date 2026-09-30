from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
from novel_kernel.candidate_reconcile import CandidateReconciler
from novel_kernel.chapter_commit import ChapterCommitter
from novel_kernel.events import EventLog,EventLogError,build_event
from novel_kernel.extraction import CandidateExtractor
from novel_kernel.hard_audit import HardInvariantAuditor
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionIntegrityError,ProductionPlanner,ProductionStaleError
from novel_kernel.soft_audit import SoftAuditor
from novel_kernel.writer_runtime import WriterRunController
ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
class ChapterCommitTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_demo";shutil.copytree(FIX,self.book/"outline");p=self.book/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v));OutlineCompiler().compile(self.book/"outline");OutlineBootstrapper().bootstrap(self.book/"outline");plan=ProductionPlanner().plan(self.book,chapter_id="ch_001");self.run_id=plan.run_id;self.run=Path(plan.run_path);ContextPackBuilder().build(self.book,run_id=self.run_id);c=WriterRunController();c.start_task(self.book,task_id=plan.task_id);prose='凌云。<!-- novel:claim {"subject_id":"char_lin_yun","predicate":"status","value":"exposed"} -->';(self.run/"prose.md").write_text(prose);c.request_review(self.book,run_id=self.run_id);c.decide_review(self.book,run_id=self.run_id,decision="approve",actor="editor");CandidateExtractor().extract(self.book,run_id=self.run_id);CandidateReconciler().reconcile(self.book,run_id=self.run_id);HardInvariantAuditor().audit(self.book,run_id=self.run_id);a=SoftAuditor();a.semantic(self.book,run_id=self.run_id);a.style(self.book,run_id=self.run_id);a.gate(self.book,run_id=self.run_id,decision="approve",actor="editor")
 def tearDown(self):self.temp.cleanup()
 def test_commit_appends_batch_publishes_exact_prose_and_updates_projection(self):
  before=len(EventLog(self.book).read_events());r=ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor");self.assertEqual(r.state,"published");self.assertEqual(len(EventLog(self.book).read_events())-before,len(r.event_ids));self.assertEqual((self.book/"chapters"/"ch_001.md").read_bytes(),(self.run/"prose.md").read_bytes());types=[x["event_type"] for x in EventLog(self.book).read_events()[-len(r.event_ids):]];self.assertEqual(types[0],"audit.completed");self.assertIn("chapter.committed",types);self.assertEqual(types[-1],"state.reconciled");self.assertTrue((self.book/"state"/"state.db").is_file())
 def test_commit_is_idempotent(self):
  a=ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor");count=len(EventLog(self.book).read_events());b=ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor");self.assertEqual(a.commit_hash,b.commit_hash);self.assertTrue(b.reused);self.assertEqual(count,len(EventLog(self.book).read_events()))
 def test_partial_complete_event_prefix_recovers(self):
  original=EventLog.append_many;called=[]
  def partial(log,events):
   events=tuple(events)
   if not called:called.append(True);original(log,events[:2]);raise EventLogError("injected interruption")
   return original(log,events)
  with mock.patch.object(EventLog,"append_many",partial):
   with self.assertRaises(ProductionIntegrityError):ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor")
  r=ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor");self.assertEqual(r.state,"published")
 def test_failure_before_append_and_after_append_before_publication_recover(self):
  original=EventLog.append_many
  with mock.patch.object(EventLog,"append_many",side_effect=EventLogError("before append")):
   with self.assertRaises(ProductionIntegrityError):ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor")
  import novel_kernel.chapter_commit as module
  with mock.patch.object(module,"atomic_write_bytes",side_effect=OSError("publication interrupted")):
   with self.assertRaises(OSError):ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor")
  count=len(EventLog(self.book).read_events());r=ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor");self.assertEqual(r.state,"published");self.assertEqual(count,len(EventLog(self.book).read_events()))
 def test_failure_after_publication_before_finalize_recovers(self):
  from novel_kernel.projection import ProjectionStore
  with mock.patch.object(ProjectionStore,"update",side_effect=RuntimeError("projection interrupted")):
   with self.assertRaises(RuntimeError):ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor")
  self.assertTrue((self.book/"chapters"/"ch_001.md").exists());count=len(EventLog(self.book).read_events());r=ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor");self.assertEqual(r.state,"published");self.assertEqual(count,len(EventLog(self.book).read_events()))
 def test_stale_authority_and_hash_tamper_are_rejected(self):
  log=EventLog(self.book);head=log.read_lineage("main")[-1]["event_id"];log.append(build_event(event_type="audit.completed",book_id="book_demo",branch_id="main",parent_event_id=head,story_seq=0,recorded_at="2026-09-29T21:00:00+08:00",actor_type="human",actor_id="external",payload={"later":True}))
  with self.assertRaises(ProductionStaleError):ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor")
  (self.run/"prose.md").write_text("tampered")
  with self.assertRaises((ProductionIntegrityError,ProductionStaleError)):ChapterCommitter().commit(self.book,run_id=self.run_id,actor="human.editor")
 def test_actor_guard_and_cli(self):
  with self.assertRaises(Exception):ChapterCommitter().commit(self.book,run_id=self.run_id,actor="writer")
  x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"commit","chapter","--path",str(self.book),"--run",self.run_id,"--actor","human.editor","--json"],text=True,capture_output=True);self.assertEqual(x.returncode,0,x.stderr);self.assertEqual(json.loads(x.stdout)["state"],"published")
if __name__=="__main__":unittest.main()
