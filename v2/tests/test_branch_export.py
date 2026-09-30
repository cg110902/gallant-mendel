from __future__ import annotations
import json,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from novel_kernel.branch_ops import BranchOperationError,BranchService
from novel_kernel.events import EventLog,build_event
from novel_kernel.export import ExportError,ExportService
from novel_kernel.storage import sha256_bytes
ROOT=Path(__file__).resolve().parents[1]
class BranchExportTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.book=Path(self.t.name)/"book";log=EventLog(self.book);log.initialize();self.prose="第一章。\n";h=sha256_bytes(self.prose.encode());e=build_event(event_id="event_00000000000000000000000000000001",event_type="chapter.committed",book_id="book_test",branch_id="main",parent_event_id=None,story_seq=1,recorded_at="2026-09-30T00:00:00Z",actor_type="human",actor_id="editor",payload={"chapter_id":"ch_001","prose_hash":h,"audit_decision_hash":"sha256:"+"0"*64});log.append(e);(self.book/"chapters").mkdir();(self.book/"chapters/ch_001.md").write_text(self.prose)
 def tearDown(self):self.t.cleanup()
 def test_branch_fork_and_rollback_are_non_destructive(self):
  log=EventLog(self.book);before=(log.log_path.read_bytes(),log.verify().heads["main"]);r=BranchService().create(self.book,branch_id="experiment",mode="non_destructive_rollback");self.assertTrue(r.main_head_unchanged);self.assertEqual(log.verify().heads["main"],before[1]);self.assertEqual(log.read_lineage("experiment")[-1]["event_type"],"branch.created")
  with self.assertRaises(BranchOperationError):BranchService().create(self.book,branch_id="experiment")
 def test_export_is_deterministic_and_rejects_tamper(self):
  a=ExportService().export(self.book);b=ExportService().export(self.book);self.assertEqual(a.manifest_hash,b.manifest_hash);self.assertEqual(a.files,b.files);self.assertEqual(a.chapter_count,1)
  epub=self.book/a.files[0]["path"] if a.files[0]["format"]=="epub" else self.book/next(x["path"] for x in a.files if x["format"]=="epub")
  with zipfile.ZipFile(epub) as z:self.assertEqual(z.namelist()[0],"mimetype");self.assertEqual(z.read("mimetype"),b"application/epub+zip")
  (self.book/"chapters/ch_001.md").write_text("tampered")
  with self.assertRaises(ExportError):ExportService().export(self.book)
 def test_export_rejects_symlinked_authority_input(self):
  chapter=self.book/"chapters/ch_001.md";real=self.book/"real.md";chapter.replace(real);chapter.symlink_to(real)
  with self.assertRaises(ExportError):ExportService().export(self.book)
 def test_cli_branch_and_export(self):
  branch=subprocess.run([sys.executable,str(ROOT/"studio.py"),"branch","create","--path",str(self.book),"--branch","draft","--json"],text=True,capture_output=True);self.assertEqual(branch.returncode,0,branch.stderr);self.assertEqual(json.loads(branch.stdout)["branch_id"],"draft")
  export=subprocess.run([sys.executable,str(ROOT/"studio.py"),"export","--path",str(self.book),"--format","markdown,json,epub","--json"],text=True,capture_output=True);self.assertEqual(export.returncode,0,export.stderr);self.assertEqual(json.loads(export.stdout)["chapter_count"],1)
if __name__=="__main__":unittest.main()
