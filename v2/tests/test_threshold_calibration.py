from __future__ import annotations
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.calibration import CalibrationIntegrityError
from novel_kernel.threshold_calibration import evaluate_holdout,select_thresholds,validate_bundle
ROOT=Path(__file__).resolve().parents[1];G=ROOT/"calibration"/"soft-v1"
def docs():return tuple(json.loads((G/x).read_text()) for x in ("soft-features.v1.json","soft-corpus.labels.v1.json","soft-split-manifest.v1.json"))
class ThresholdCalibrationTests(unittest.TestCase):
 def test_train_candidates_and_calibration_freeze_three_warning_thresholds(self):
  features,labels,split=docs();bundle=select_thresholds(features,labels,split,calibrated_at="2026-09-29T00:00:00+00:00",expires_at="2026-12-29T00:00:00+00:00",owner="quality");validate_bundle(bundle);values={x["detector_id"]:x["threshold"]["value"] for x in bundle["thresholds"]};self.assertEqual(values["persona_drift"],1.0);self.assertEqual(values["trope_repeat"],2.0);self.assertAlmostEqual(values["word_count_cheat"],0.5915492957746479);self.assertTrue(all(x["threshold"]["severity"]=="warning" and x["threshold"]["sample_size"]==22 for x in bundle["thresholds"]));self.assertFalse(bundle["holdout_used"])
  self.assertTrue(all(x["train_metrics"]["balanced_accuracy"]==1 and x["calibration_metrics"]["balanced_accuracy"]==1 for x in bundle["selections"]))
 def test_holdout_labels_do_not_influence_selected_values(self):
  features,labels,split=docs();a=select_thresholds(features,labels,split,calibrated_at="2026-09-29T00:00:00+00:00",expires_at="2026-12-29T00:00:00+00:00",owner="quality");parts={x["sample_id"]:x["split"] for x in split["entries"]}
  for row in labels["labels"]:
   if parts[row["sample_id"]]=="holdout":row["expected_detected"]=not row["expected_detected"]
  from novel_kernel.storage import sha256_json;base={k:v for k,v in labels.items() if k!="labels_hash"};labels["labels_hash"]=sha256_json(base);b=select_thresholds(features,labels,split,calibrated_at="2026-09-29T00:00:00+00:00",expires_at="2026-12-29T00:00:00+00:00",owner="quality");self.assertEqual([x["threshold"]["value"] for x in a["thresholds"]],[x["threshold"]["value"] for x in b["thresholds"]]);self.assertEqual(a["selections"],b["selections"])
 def test_one_shot_holdout_is_complete_and_perfect_on_frozen_template_corpus(self):
  features,labels,split=docs();bundle=json.loads((G/"soft-threshold-bundle.v1.json").read_text());report=evaluate_holdout(bundle,features,labels,split);self.assertEqual(report["totals"],{"tp":12,"fp":0,"tn":12,"fn":0});self.assertEqual(len(report["results"]),24);parts={x["sample_id"]:x["split"] for x in split["entries"]};self.assertTrue(all(parts[x["sample_id"]]=="holdout" for x in report["results"]));self.assertTrue(report["one_shot"])
 def test_hash_tamper_and_used_bundle_are_rejected(self):
  features,labels,split=docs();bundle=json.loads((G/"soft-threshold-bundle.v1.json").read_text());bundle["thresholds"][0]["threshold"]["value"]=0
  with self.assertRaises(CalibrationIntegrityError):validate_bundle(bundle)
  bundle=json.loads((G/"soft-threshold-bundle.v1.json").read_text());bundle["holdout_used"]=True
  with self.assertRaises(Exception):evaluate_holdout(bundle,features,labels,split)
 def test_cli_replays_versioned_bundle_and_receipt_idempotently(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);thresholds=root/"thresholds.json";holdout=root/"holdout.json";common=["--features",str(G/"soft-features.v1.json"),"--labels",str(G/"soft-corpus.labels.v1.json"),"--split",str(G/"soft-split-manifest.v1.json")]
   a=subprocess.run([sys.executable,str(ROOT/"studio.py"),"calibrate","thresholds",*common,"--output",str(thresholds),"--calibrated-at","2026-09-29T00:00:00+00:00","--expires-at","2026-12-29T00:00:00+00:00","--owner","quality","--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(a.returncode,0,a.stderr);b=subprocess.run([sys.executable,str(ROOT/"studio.py"),"calibrate","holdout","--thresholds",str(thresholds),*common,"--output",str(holdout),"--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(b.returncode,0,b.stderr);self.assertEqual((json.loads(b.stdout)["tp"],json.loads(b.stdout)["fn"]),(12,0));self.assertEqual(thresholds.read_bytes(),(G/"soft-threshold-bundle.v1.json").read_bytes());self.assertEqual(holdout.read_bytes(),(G/"soft-holdout-report.v1.json").read_bytes())
if __name__=="__main__":unittest.main()
