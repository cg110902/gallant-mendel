from __future__ import annotations
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.mutation_harness import MutationHarness
ROOT=Path(__file__).resolve().parents[1];CORPUS=ROOT/"calibration"/"mutation-corpus.v1.json";FIXTURE=ROOT/"workspace"/"_fixture"/"outline"/"valid-semantic"/"outline"
class MutationHarnessTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.out=Path(cls.temp.name)/"baseline";cls.result=MutationHarness().run(CORPUS,FIXTURE,cls.out)
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def test_real_gates_produce_honest_seven_tp_three_fn_and_ten_tn(self):
  report=json.loads((self.out/"calibration-report.v1.json").read_text());totals={x:sum(m[x] for m in report["confusion_matrices"]) for x in ("tp","fp","tn","fn")};self.assertEqual(totals,{"tp":7,"fp":0,"tn":10,"fn":3});missed={x["sample_id"] for x in report["detections"] if x["outcome"]=="fn"};self.assertEqual(missed,{"mutation_05_personadrift","mutation_09_troperepeat","mutation_10_wordcountcheat"})
 def test_all_variants_execute_without_authority_mutation(self):
  report=json.loads((self.out/"mutation-harness-report.v1.json").read_text());self.assertEqual(len(report["runs"]),20);self.assertTrue(report["authority_unchanged"]);self.assertTrue(all(x["authority_unchanged"] for x in report["runs"]));self.assertFalse(any(x["detected"] for x in report["runs"] if x["variant"]=="clean"))
 def test_baseline_artifacts_are_byte_deterministic(self):
  baseline=ROOT/"calibration"/"baseline"
  for name in ("mutation-observations.v1.json","calibration-report.v1.json","mutation-harness-report.v1.json"):self.assertEqual((baseline/name).read_bytes(),(self.out/name).read_bytes(),name)
 def test_detector_identity_and_real_evidence_are_recorded(self):
  value=json.loads((self.out/"mutation-observations.v1.json").read_text());hits=[x for x in value["detections"] if x["detected"]];self.assertEqual(len(hits),7);self.assertTrue(all(x["detector_id"] and x["detector_version"] and x["evidence_refs"] for x in hits));self.assertIn("hard_invariant_auditor",{x["detector_id"] for x in hits})
 def test_cli_run(self):
  with tempfile.TemporaryDirectory() as temp:
   result=subprocess.run([sys.executable,str(ROOT/"studio.py"),"calibrate","run","--corpus",str(CORPUS),"--fixture",str(FIXTURE),"--output-dir",temp,"--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(result.returncode,0,result.stderr);value=json.loads(result.stdout);self.assertEqual((value["detected_count"],value["false_negative_count"]),(7,3));self.assertTrue(value["authority_unchanged"])
if __name__=="__main__":unittest.main()
