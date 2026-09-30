from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.candidate_reconcile import CandidateReconciler
from novel_kernel.extraction import CandidateExtractor
from novel_kernel.hard_audit import HardInvariantAuditor
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionIntegrityError,ProductionPlanner
from novel_kernel.storage import atomic_write_json,sha256_json
from novel_kernel.writer_runtime import WriterRunController
ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
class HardAuditTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_demo";shutil.copytree(FIX,self.book/"outline");p=self.book/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v));OutlineCompiler().compile(self.book/"outline");OutlineBootstrapper().bootstrap(self.book/"outline");plan=ProductionPlanner().plan(self.book,chapter_id="ch_001");self.run_id=plan.run_id;self.run=Path(plan.run_path);ContextPackBuilder().build(self.book,run_id=self.run_id);self.controller=WriterRunController();self.controller.start_task(self.book,task_id=plan.task_id)
 def tearDown(self):self.temp.cleanup()
 def mutate_context(self,fn):
  p=self.run/"context-pack.json";pack=json.loads(p.read_text());fn(pack);atomic_write_json(p,pack);s=self.run/"status.json";status=json.loads(s.read_text());status["context_hash"]=sha256_json(pack);atomic_write_json(s,status)
 def prepare(self,*claims):
  prose="凌云。"+"".join(f'<!-- novel:claim {json.dumps(x,separators=(",",":"))} -->' for x in claims);(self.run/"prose.md").write_text(prose);self.controller.request_review(self.book,run_id=self.run_id);self.controller.decide_review(self.book,run_id=self.run_id,decision="approve",actor="editor");CandidateExtractor().extract(self.book,run_id=self.run_id);CandidateReconciler().reconcile(self.book,run_id=self.run_id)
 def rules(self,report):return {x["rule_id"] for x in report.findings}
 def test_required_candidate_passes_without_authority_write(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});before=(self.book/"ledger"/"events.jsonl").read_bytes();r=HardInvariantAuditor().audit(self.book,run_id=self.run_id);self.assertTrue(r.ok);self.assertEqual(r.state,"audit_passed");self.assertEqual(before,(self.book/"ledger"/"events.jsonl").read_bytes())
 def test_missing_intent_remains_review_not_hard(self):
  self.prepare();r=HardInvariantAuditor().audit(self.book,run_id=self.run_id);self.assertFalse(r.has_hard_violation);self.assertTrue(r.requires_human_review);self.assertIn("reconcile.intent_missing",self.rules(r));self.assertEqual(r.state,"audit_review")
 def test_capability_knowledge_time_location_and_obligation_rules(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"capability_use","value":"magic"},{"subject_id":"char_lin_yun","predicate":"knows","value":"fact_bootstrap_ba165c6944d1e415"},{"subject_id":"char_lin_yun","predicate":"story_time","value":"story:0019-04-02T08:00"},{"subject_id":"char_lin_yun","predicate":"location","value":"char_master"},{"subject_id":"char_lin_yun","predicate":"obligation_touch","value":"ob_missing"});r=HardInvariantAuditor().audit(self.book,run_id=self.run_id);self.assertTrue({"capability_prerequisite","knowledge_boundary","time_window","location_scope","obligation_active"}<=self.rules(r));self.assertEqual(r.state,"audit_failed")
 def test_dead_actor_rule(self):
  def dead(pack):
   next(x for x in pack["authoritative_context"]["facets"] if x["object_id"]=="char_lin_yun" and x["facet_type"]=="status")["payload"]["state"]="dead"
  self.mutate_context(dead);self.prepare({"subject_id":"char_lin_yun","predicate":"acts","value":"attack"});r=HardInvariantAuditor().audit(self.book,run_id=self.run_id);self.assertIn("dead_actor",self.rules(r))
 def test_resource_source_allows_possession_and_blocks_unknown(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"resource_use","value":"item_seal"},{"subject_id":"char_lin_yun","predicate":"resource_use","value":"char_master"});r=HardInvariantAuditor().audit(self.book,run_id=self.run_id);self.assertEqual(sum(x["rule_id"]=="resource_source" for x in r.findings),1)
 def test_reconcile_tamper_is_integrity_error(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"status","value":"exposed"});p=self.run/"candidate-reconcile.json";v=json.loads(p.read_text());v["state"]="reconcile_review";atomic_write_json(p,v)
  with self.assertRaises(ProductionIntegrityError):HardInvariantAuditor().audit(self.book,run_id=self.run_id)
 def test_idempotence_and_cli_hard_exit(self):
  self.prepare({"subject_id":"char_lin_yun","predicate":"capability_use","value":"magic"});a=HardInvariantAuditor().audit(self.book,run_id=self.run_id);b=HardInvariantAuditor().audit(self.book,run_id=self.run_id);self.assertEqual(a.audit_hash,b.audit_hash);self.assertTrue(b.reused);x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"audit","hard","--path",str(self.book),"--run",self.run_id,"--json"],capture_output=True);self.assertEqual(x.returncode,3)
if __name__=="__main__":unittest.main()
