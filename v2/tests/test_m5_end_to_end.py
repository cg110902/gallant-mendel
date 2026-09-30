"""M5 final acceptance: one chapter from approved prose to queryable authority."""
from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.events import EventLog
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionPlanner
from novel_kernel.temporal import TemporalStateQuery
from novel_kernel.writer_runtime import WriterRunController
ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"

class M5EndToEndTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_demo"
  shutil.copytree(FIX,self.book/"outline");manifest=self.book/"outline"/"00-manifest.json";value=json.loads(manifest.read_text());value["status"]="approved";value["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};manifest.write_text(json.dumps(value))
  OutlineCompiler().compile(self.book/"outline");OutlineBootstrapper().bootstrap(self.book/"outline")
  plan=ProductionPlanner().plan(self.book,chapter_id="ch_001");self.run_id=plan.run_id;self.run=Path(plan.run_path);ContextPackBuilder().build(self.book,run_id=self.run_id)
  writer=WriterRunController();writer.start_task(self.book,task_id=plan.task_id);(self.run/"prose.md").write_text('凌云的身份已经暴露。<!-- novel:claim {"subject_id":"char_lin_yun","predicate":"status","value":"exposed"} -->');writer.request_review(self.book,run_id=self.run_id);writer.decide_review(self.book,run_id=self.run_id,decision="approve",actor="editor")
 def tearDown(self):self.temp.cleanup()
 def cli(self,*args,expected=(0,)):
  result=subprocess.run([sys.executable,str(ROOT/"studio.py"),*args],cwd=ROOT,text=True,capture_output=True)
  self.assertIn(result.returncode,expected,result.stderr+result.stdout);return json.loads(result.stdout) if result.stdout.strip().startswith("{") else result.stdout
 def test_one_chapter_pipeline_preserves_candidate_boundary_then_commits_queryable_fact(self):
  log=EventLog(self.book);authority_before=log.log_path.read_bytes();count_before=len(log.read_events());common=("--path",str(self.book),"--run",self.run_id,"--json")
  extraction=self.cli("extract",*common);self.assertGreater(extraction["claim_count"],0)
  reconcile=self.cli("reconcile",*common);self.assertIn(reconcile["state"],{"reconciled","reconcile_review"})
  hard=self.cli("audit","hard",*common,expected=(0,4));self.assertNotEqual(hard["state"],"audit_failed")
  self.cli("audit","semantic",*common);self.cli("audit","style",*common);semantic=json.loads((self.run/"semantic-audit-report.json").read_text());style=json.loads((self.run/"style-audit-report.json").read_text());self.assertTrue(semantic["descriptive_only"]);self.assertFalse(style["thresholds_applied"])
  gate=self.cli("audit","gate",*common[:-1],"--decision","approve","--actor","editor","--json");self.assertEqual(gate["state"],"audit_approved")
  self.assertEqual(authority_before,log.log_path.read_bytes(),"candidate/reconcile/audit stages mutated authority")
  commit=self.cli("commit","chapter",*common[:-1],"--actor","human.editor","--json");self.assertEqual(commit["state"],"published");self.assertEqual((self.book/"chapters"/"ch_001.md").read_bytes(),(self.run/"prose.md").read_bytes());self.assertGreater(len(log.read_events()),count_before)
  queried=TemporalStateQuery().query(self.book,as_of="ch_001");facts=[x for x in queried.facts if x["subject_id"]=="char_lin_yun" and x["predicate"]=="status"]
  self.assertEqual([x["value"] for x in facts],["exposed"]);self.assertEqual(queried.cutoff["event_id"],commit["commit_head"])
  cli_state=self.cli("state","query","--path",str(self.book),"--as-of","ch_001","--json");self.assertEqual(cli_state["cutoff"]["event_id"],commit["commit_head"])
  report=json.loads((self.run/"chapter-commit-report.json").read_text());self.assertEqual(report["chapter_hash"],commit["chapter_hash"]);self.assertEqual(json.loads((self.run/"status.json").read_text())["state"],"published")

if __name__=="__main__":unittest.main()
