from __future__ import annotations
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.challenge_transfer import build_challenge,evaluate_challenge
from novel_kernel.threshold_calibration import validate_bundle
from novel_kernel.storage import canonical_json_bytes
ROOT=Path(__file__).resolve().parents[1];G=ROOT/"calibration"/"challenge-v1";T=ROOT/"calibration"/"soft-v1"/"soft-threshold-bundle.v1.json"
class ChallengeTransferTests(unittest.TestCase):
 def test_challenge_is_deterministic_balanced_and_distinct(self):
  a=build_challenge();b=build_challenge();self.assertEqual(canonical_json_bytes(a),canonical_json_bytes(b));self.assertEqual(len(a["samples"]),36);self.assertEqual(len({x["prose_hash"] for x in a["samples"]}),36);self.assertEqual(sum(x["expected_detected"] for x in a["samples"]),18);self.assertEqual(sum(x["template_relation"]=="out_of_template" for x in a["samples"]),9)
 def test_transfer_report_exposes_nine_false_negatives(self):
  corpus=build_challenge();thresholds=json.loads(T.read_text());report=evaluate_challenge(corpus,thresholds);self.assertEqual(report["totals"],{"tp":9,"fp":0,"tn":18,"fn":9});self.assertTrue(report["template_holdout_claim_separate"]);self.assertTrue(all(x["recall"]==0.5 for x in report["matrices"]));misses=[x for x in report["results"] if x["outcome"]=="fn"];self.assertEqual(len(misses),9);self.assertTrue(all(x["template_relation"]=="out_of_template" for x in misses))
 def test_cli_replays_frozen_challenge_bytes(self):
  with tempfile.TemporaryDirectory() as temp:
   x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"calibrate","challenge","--thresholds",str(T),"--output-dir",temp,"--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(x.returncode,0,x.stderr);self.assertEqual((json.loads(x.stdout)["tp"],json.loads(x.stdout)["fn"]),(9,9));self.assertEqual((Path(temp)/"soft-challenge-corpus.v1.json").read_bytes(),(G/"soft-challenge-corpus.v1.json").read_bytes());self.assertEqual((Path(temp)/"soft-challenge-report.v1.json").read_bytes(),(G/"soft-challenge-report.v1.json").read_bytes())
if __name__=="__main__":unittest.main()
