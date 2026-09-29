from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.extraction import CandidateExtractor
from novel_kernel.outline_bootstrap import OutlineBootstrapper
from novel_kernel.outline_compile import OutlineCompiler
from novel_kernel.production import ContextPackBuilder,ProductionIntegrityError,ProductionPlanner,ProductionStaleError
from novel_kernel.writer_runtime import WriterRunController
ROOT=Path(__file__).resolve().parents[1];FIX=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
class ExtractionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_demo";shutil.copytree(FIX,self.book/"outline");p=self.book/"outline"/"00-manifest.json";v=json.loads(p.read_text());v["status"]="approved";v["approval"]={"owner":"author","approved_at":"2026-09-29T18:00:00+08:00"};p.write_text(json.dumps(v));OutlineCompiler().compile(self.book/"outline");OutlineBootstrapper().bootstrap(self.book/"outline");plan=ProductionPlanner().plan(self.book,chapter_id="ch_001");self.run_id=plan.run_id;ContextPackBuilder().build(self.book,run_id=self.run_id);self.controller=WriterRunController();self.controller.start_task(self.book,task_id=plan.task_id);self.run=Path(plan.run_path)
 def tearDown(self):self.temp.cleanup()
 def approve(self,text):
  (self.run/"prose.md").write_text(text);self.controller.request_review(self.book,run_id=self.run_id);self.controller.decide_review(self.book,run_id=self.run_id,decision="approve",actor="editor")
 def test_extracts_registered_mentions_claim_delta_and_exact_evidence(self):
  prose='凌云抵达边城。\n<!-- novel:claim {"subject_id":"char_lin_yun","predicate":"status","value":"exposed"} -->';self.approve(prose);before=(self.book/"ledger"/"events.jsonl").read_bytes();r=CandidateExtractor().extract(self.book,run_id=self.run_id);self.assertEqual((r.claim_count,r.delta_count),(1,1));self.assertGreaterEqual(r.entity_mention_count,2);self.assertFalse(r.semantic_completeness);self.assertEqual(before,(self.book/"ledger"/"events.jsonl").read_bytes())
  ev=json.loads((self.run/"evidence.json").read_text());self.assertTrue(all(prose[x["start_char"]:x["end_char"]]==x["quote"] for x in ev["bindings"]));claims=json.loads((self.run/"candidate-claims.json").read_text());self.assertEqual(claims["claims"][0]["confidence"],"candidate");self.assertFalse(json.loads((self.run/"candidate-state-delta.json").read_text())["authoritative"])
 def test_plain_prose_is_conservative_not_semantically_complete(self):
  self.approve("凌云看见了远处的灯。") ;r=CandidateExtractor().extract(self.book,run_id=self.run_id);self.assertEqual(r.claim_count,0);self.assertFalse(r.semantic_completeness)
 def test_unknown_subject_and_duplicate_json_key_are_rejected(self):
  for annotation in ('{"subject_id":"char_unknown","predicate":"status","value":"x"}','{"subject_id":"char_lin_yun","predicate":"status","value":1,"value":2}'):
   with self.subTest(annotation=annotation):
    # Each subcase gets a fresh approved run fixture through manual status reset.
    self.approve(f'<!-- novel:claim {annotation} -->')
    with self.assertRaises(Exception):CandidateExtractor().extract(self.book,run_id=self.run_id)
    status=json.loads((self.run/"status.json").read_text());status["state"]="draft_ready";(self.run/"status.json").write_text(json.dumps(status,separators=(",",":"),sort_keys=True))
 def test_approved_prose_change_is_stale(self):
  self.approve("凌云。") ;(self.run/"prose.md").write_text("凌云。changed")
  with self.assertRaises(ProductionStaleError):CandidateExtractor().extract(self.book,run_id=self.run_id)
 def test_idempotence_and_conflicting_artifact(self):
  self.approve("凌云。") ;a=CandidateExtractor().extract(self.book,run_id=self.run_id);b=CandidateExtractor().extract(self.book,run_id=self.run_id);self.assertEqual(a.extraction_hash,b.extraction_hash);self.assertTrue(b.reused);(self.run/"evidence.json").write_text("{}")
  with self.assertRaises(ProductionIntegrityError):CandidateExtractor().extract(self.book,run_id=self.run_id)
 def test_cli_extract(self):
  self.approve("凌云。") ;x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"extract","--path",str(self.book),"--run",self.run_id,"--json"],text=True,capture_output=True);self.assertEqual(x.returncode,0,x.stderr);self.assertEqual(json.loads(x.stdout)["state"],"extracted")
if __name__=="__main__":unittest.main()
