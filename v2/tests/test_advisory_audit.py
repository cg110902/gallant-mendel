from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.advisory_audit import AdvisoryAuditor
from novel_kernel.candidate_reconcile import CandidateReconciler
from novel_kernel.events import EventLog
from novel_kernel.extraction import CandidateExtractor
from novel_kernel.hard_audit import HardInvariantAuditor
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionInputError,ProductionPlanner
from novel_kernel.soft_audit import SoftAuditor
from novel_kernel.storage import atomic_write_json,sha256_json
from novel_kernel.writer_runtime import WriterRunController
ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline";THRESHOLDS=ROOT/"calibration"/"soft-v1"/"soft-threshold-bundle.v1.json"
class AdvisoryAuditTests(unittest.TestCase):
 def make_run(self,prose,persona=False):
  temp=tempfile.TemporaryDirectory();book=Path(temp.name)/"book_demo";shutil.copytree(FIX,book/"outline");p=book/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v));OutlineCompiler().compile(book/"outline");OutlineBootstrapper().bootstrap(book/"outline");plan=ProductionPlanner().plan(book,chapter_id="ch_001");run_id=plan.run_id;run=Path(plan.run_path);ContextPackBuilder().build(book,run_id=run_id);writer=WriterRunController();writer.start_task(book,task_id=plan.task_id);(run/"prose.md").write_text(prose);writer.request_review(book,run_id=run_id);writer.decide_review(book,run_id=run_id,decision="approve",actor="editor")
  if persona:
   pack=json.loads((run/"context-pack.json").read_text());facet=next(x for x in pack["authoritative_context"]["facets"] if x["object_id"]=="char_lin_yun" and x["facet_type"]=="psychology");facet["payload"]["persona_baseline"]="cautious";atomic_write_json(run/"context-pack.json",pack);status=json.loads((run/"status.json").read_text());status["context_hash"]=sha256_json(pack);atomic_write_json(run/"status.json",status)
  CandidateExtractor().extract(book,run_id=run_id);CandidateReconciler().reconcile(book,run_id=run_id);HardInvariantAuditor().audit(book,run_id=run_id);return temp,book,run_id,run
 def test_three_calibrated_matches_are_warning_only_and_authority_read_only(self):
  prose="其实。"*80+'<!-- novel:persona {"subject_id":"char_lin_yun","value":"cruel"} --><!-- novel:claim {"subject_id":"char_lin_yun","predicate":"status","value":"exposed"} -->';temp,book,run_id,run=self.make_run(prose,True)
  try:
   log=EventLog(book);before=log.log_path.read_bytes();state=json.loads((run/"status.json").read_text())["state"];report=AdvisoryAuditor().audit(book,run_id=run_id,thresholds_path=THRESHOLDS,evaluated_at="2026-09-30T00:00:00+00:00");self.assertEqual(report.finding_count,3);doc=json.loads((run/"advisory-audit-report.json").read_text());self.assertTrue(doc["advisory_only"]);self.assertFalse(doc["blocking"]);self.assertTrue(all(x["severity"]=="warning" for x in doc["findings"]));self.assertEqual(log.log_path.read_bytes(),before);self.assertEqual(json.loads((run/"status.json").read_text())["state"],state)
  finally:temp.cleanup()
 def test_clean_run_has_no_finding_and_missing_persona_baseline_is_unavailable(self):
  prose='凌云的身份暴露。<!-- novel:persona {"subject_id":"char_lin_yun","value":"cruel"} --><!-- novel:claim {"subject_id":"char_lin_yun","predicate":"status","value":"exposed"} -->';temp,book,run_id,run=self.make_run(prose)
  try:
   report=AdvisoryAuditor().audit(book,run_id=run_id,thresholds_path=THRESHOLDS,evaluated_at="2026-09-30T00:00:00+00:00");self.assertEqual(report.finding_count,0);doc=json.loads((run/"advisory-audit-report.json").read_text());persona=next(x for x in doc["features"] if x["detector_id"]=="persona_drift");self.assertIsNone(persona["feature_value"]);self.assertIn("no frozen",persona["unavailable_reason"])
  finally:temp.cleanup()
 def test_advisory_does_not_change_human_gate_contract(self):
  prose='凌云身份暴露。<!-- novel:claim {"subject_id":"char_lin_yun","predicate":"status","value":"exposed"} -->';temp,book,run_id,run=self.make_run(prose)
  try:
   AdvisoryAuditor().audit(book,run_id=run_id,thresholds_path=THRESHOLDS,evaluated_at="2026-09-30T00:00:00+00:00");a=SoftAuditor();a.semantic(book,run_id=run_id);a.style(book,run_id=run_id);gate=a.gate(book,run_id=run_id,decision="approve",actor="editor");self.assertEqual(gate.state,"audit_approved")
  finally:temp.cleanup()
 def test_expired_threshold_and_cli(self):
  prose='凌云身份暴露。<!-- novel:claim {"subject_id":"char_lin_yun","predicate":"status","value":"exposed"} -->';temp,book,run_id,run=self.make_run(prose)
  try:
   with self.assertRaises(ProductionInputError):AdvisoryAuditor().audit(book,run_id=run_id,thresholds_path=THRESHOLDS,evaluated_at="2027-01-01T00:00:00+00:00")
   x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"audit","advisory","--path",str(book),"--run",run_id,"--thresholds",str(THRESHOLDS),"--evaluated-at","2026-09-30T00:00:00+00:00","--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(x.returncode,0,x.stderr);self.assertEqual(json.loads(x.stdout)["state"],json.loads((run/"status.json").read_text())["state"])
  finally:temp.cleanup()
if __name__=="__main__":unittest.main()
