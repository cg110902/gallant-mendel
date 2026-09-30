from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.candidate_reconcile import CandidateReconciler
from novel_kernel.extraction import CandidateExtractor
from novel_kernel.hard_audit import HardInvariantAuditor
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionIntegrityError,ProductionPlanner,ProductionStaleError
from novel_kernel.soft_audit import SoftAuditor
from novel_kernel.storage import atomic_write_json
from novel_kernel.writer_runtime import WriterRunController
ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
class SoftAuditTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_demo";shutil.copytree(FIX,self.book/"outline");p=self.book/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v));OutlineCompiler().compile(self.book/"outline");OutlineBootstrapper().bootstrap(self.book/"outline");plan=ProductionPlanner().plan(self.book,chapter_id="ch_001");self.run_id=plan.run_id;self.run=Path(plan.run_path);ContextPackBuilder().build(self.book,run_id=self.run_id);self.controller=WriterRunController();self.controller.start_task(self.book,task_id=plan.task_id)
 def tearDown(self):self.temp.cleanup()
 def prepare(self,claim=None,text_prefix="凌云说：“走。”\n\n边城无声。"):
  annotation="" if claim is None else f'<!-- novel:claim {json.dumps(claim,separators=(",",":"))} -->';(self.run/"prose.md").write_text(text_prefix+annotation);self.controller.request_review(self.book,run_id=self.run_id);self.controller.decide_review(self.book,run_id=self.run_id,decision="approve",actor="editor");CandidateExtractor().extract(self.book,run_id=self.run_id);CandidateReconciler().reconcile(self.book,run_id=self.run_id);HardInvariantAuditor().audit(self.book,run_id=self.run_id)
 def test_reports_are_descriptive_bound_and_order_independent(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});a=SoftAuditor();style=a.style(self.book,run_id=self.run_id);semantic=a.semantic(self.book,run_id=self.run_id);self.assertEqual(semantic.state,"soft_audit_ready");s=json.loads((self.run/"style-audit-report.json").read_text());m=json.loads((self.run/"semantic-audit-report.json").read_text());self.assertTrue(s["descriptive_only"]);self.assertFalse(s["thresholds_applied"]);self.assertTrue(m["descriptive_only"]);self.assertEqual(m["metrics"]["intent_fulfilled_count"],1);self.assertGreater(s["metrics"]["dialogue_char_count"],0)
 def test_reports_are_idempotent(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});a=SoftAuditor();x=a.semantic(self.book,run_id=self.run_id);y=a.semantic(self.book,run_id=self.run_id);self.assertEqual(x.report_hash,y.report_hash);self.assertTrue(y.reused)
 def test_human_approve_binds_all_reports(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});a=SoftAuditor();a.semantic(self.book,run_id=self.run_id);a.style(self.book,run_id=self.run_id);r=a.gate(self.book,run_id=self.run_id,decision="approve",actor="editor",note="reviewed");self.assertEqual(r.state,"audit_approved");d=json.loads((self.run/"audit-decision.json").read_text());self.assertEqual(set(d["bindings"]),{"prose_hash","context_hash","extraction_hash","reconcile_hash","hard_audit_hash","semantic_audit_hash","style_audit_hash"})
 def test_hard_failed_cannot_approve_but_can_request_rework(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"capability_use","value":"magic"});a=SoftAuditor();a.semantic(self.book,run_id=self.run_id);a.style(self.book,run_id=self.run_id)
  with self.assertRaises(ProductionStaleError):a.gate(self.book,run_id=self.run_id,decision="approve",actor="editor")
  self.assertEqual(a.gate(self.book,run_id=self.run_id,decision="rework",actor="editor").state,"needs_rework")
 def test_gate_requires_both_reports_and_detects_tamper(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});a=SoftAuditor();a.semantic(self.book,run_id=self.run_id)
  with self.assertRaises(Exception):a.gate(self.book,run_id=self.run_id,decision="approve",actor="editor")
  a.style(self.book,run_id=self.run_id);p=self.run/"semantic-audit-report.json";v=json.loads(p.read_text());v["metrics"]["candidate_claim_count"]=99;atomic_write_json(p,v)
  with self.assertRaises(ProductionIntegrityError):a.gate(self.book,run_id=self.run_id,decision="approve",actor="editor")
 def test_cli_semantic_style_and_gate(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});base=[sys.executable,str(ROOT/"studio.py")]
  for kind in ("semantic","style"):
   x=subprocess.run(base+["audit",kind,"--path",str(self.book),"--run",self.run_id,"--json"],text=True,capture_output=True);self.assertEqual(x.returncode,0,x.stderr)
  x=subprocess.run(base+["audit","gate","--path",str(self.book),"--run",self.run_id,"--decision","approve","--actor","editor","--json"],text=True,capture_output=True);self.assertEqual(x.returncode,0,x.stderr);self.assertEqual(json.loads(x.stdout)["state"],"audit_approved")
if __name__=="__main__":unittest.main()
