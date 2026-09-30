from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from dataclasses import asdict
from pathlib import Path
from novel_kernel.events import EventLog,build_event
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler,OutlineCompileIntegrityError
from novel_kernel.outline_readiness import ContextReadinessError,OutlineReadinessChecker
from novel_kernel.projection import ProjectionStore
ROOT=Path(__file__).resolve().parents[1]; FIXTURE=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"; STUDIO=ROOT/"studio.py"
class ReadinessTests(unittest.TestCase):
 def book(self,parent:Path)->Path:
  b=parent/"book_demo";shutil.copytree(FIXTURE,b/"outline");p=b/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v,ensure_ascii=False));return b
 def ready_book(self,parent:Path)->Path:
  b=self.book(parent);OutlineCompiler().compile(b/"outline");OutlineBootstrapper().bootstrap(b/"outline");return b
 def test_first_chapter_prerequisites_are_ready(self):
  with tempfile.TemporaryDirectory() as t:
   b=self.ready_book(Path(t));r=OutlineReadinessChecker().check(b/"outline",expected_book_id="book_demo");self.assertTrue(r.ready);self.assertEqual(r.chapter_id,"ch_001");self.assertEqual(r.pov_id,"char_lin_yun");self.assertEqual(r.location_id,"place_border_town");self.assertEqual(r.arc_id,"arc_main_01");self.assertEqual(r.required_event_count,1);self.assertEqual(r.obligation_count,1);self.assertEqual(r.authority_event_count,26)
 def test_report_is_deterministic_and_read_only(self):
  with tempfile.TemporaryDirectory() as t:
   b=self.ready_book(Path(t));before={p.relative_to(b):p.read_bytes() for p in b.rglob("*") if p.is_file()};one=asdict(OutlineReadinessChecker().check(b/"outline"));two=asdict(OutlineReadinessChecker().check(b/"outline"));after={p.relative_to(b):p.read_bytes() for p in b.rglob("*") if p.is_file()};self.assertEqual(one,two);self.assertEqual(before,after)
 def test_readiness_before_bootstrap_is_hard_failure(self):
  with tempfile.TemporaryDirectory() as t:
   b=self.book(Path(t));OutlineCompiler().compile(b/"outline")
   with self.assertRaises(ContextReadinessError):OutlineReadinessChecker().check(b/"outline")
 def test_outline_change_after_bootstrap_is_not_ready(self):
  with tempfile.TemporaryDirectory() as t:
   b=self.ready_book(Path(t));(b/"outline"/"02-theme.json").write_text('{"changed":true}')
   with self.assertRaises(ContextReadinessError):OutlineReadinessChecker().check(b/"outline")
 def test_tampered_compiled_prerequisite_is_integrity_failure(self):
  with tempfile.TemporaryDirectory() as t:
   b=self.ready_book(Path(t));pointer=json.loads((b/"compiled"/"current.json").read_text());g=b/"compiled"/pointer["generation"];(g/"intent-ledger.json").write_text("tampered")
   with self.assertRaises(OutlineCompileIntegrityError):OutlineReadinessChecker().check(b/"outline")
 def test_later_authority_event_does_not_hide_bootstrap_marker(self):
  with tempfile.TemporaryDirectory() as t:
   b=self.ready_book(Path(t));log=EventLog(b);head=log.verify().heads["main"];event=build_event(event_type="audit.completed",book_id="book_demo",branch_id="main",parent_event_id=head,story_seq=1,recorded_at="2026-09-29T19:00:00+08:00",actor_type="human",actor_id="manual",payload={"report":"later"});log.append(event);ProjectionStore(b).update(log);r=OutlineReadinessChecker().check(b/"outline");self.assertEqual(r.authority_event_count,27);self.assertEqual(r.authority_head,event["event_id"])
class ReadinessCliTests(unittest.TestCase):
 def test_cli_ready_and_prebootstrap_exit_three(self):
  helper=ReadinessTests()
  with tempfile.TemporaryDirectory() as t:
   b=helper.ready_book(Path(t));cmd=[sys.executable,str(STUDIO),"outline","readiness","--path",str(b/"outline"),"--json"];r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(json.loads(r.stdout)["ready"])
  with tempfile.TemporaryDirectory() as t:
   b=helper.book(Path(t));OutlineCompiler().compile(b/"outline");cmd=[sys.executable,str(STUDIO),"outline","readiness","--path",str(b/"outline"),"--json"];r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);self.assertEqual(r.returncode,3);self.assertEqual(json.loads(r.stdout)["exit_code"],3)
if __name__=="__main__":unittest.main()
