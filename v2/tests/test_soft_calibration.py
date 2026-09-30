from __future__ import annotations
import json,subprocess,sys,tempfile,unittest
from collections import Counter,defaultdict
from pathlib import Path
from novel_kernel.calibration import CalibrationIntegrityError
from novel_kernel.soft_calibration import DETECTORS,build_soft_corpus,extract_features,validate_soft_inputs,validate_soft_labels
from novel_kernel.storage import canonical_json_bytes
ROOT=Path(__file__).resolve().parents[1];GOLD=ROOT/"calibration"/"soft-v1"
class SoftCalibrationTests(unittest.TestCase):
 def test_corpus_is_deterministic_unique_and_label_separated(self):
  a=build_soft_corpus();b=build_soft_corpus();self.assertEqual([canonical_json_bytes(x) for x in a],[canonical_json_bytes(x) for x in b]);samples,labels,split=a;validate_soft_labels(samples,labels,split);self.assertEqual(len(samples["samples"]),90);self.assertEqual(len({x["prose_hash"] for x in samples["samples"]}),90);self.assertNotIn("expected_detected",canonical_json_bytes(samples).decode());self.assertNotIn("expected_detected",canonical_json_bytes(split).decode())
 def test_split_is_stratified_before_feature_extraction(self):
  samples,labels,split=build_soft_corpus();gold={x["sample_id"]:x["expected_detected"] for x in labels["labels"]};counts=Counter((x["detector_id"],x["split"],gold[x["sample_id"]]) for x in split["entries"])
  for detector in DETECTORS:
   self.assertEqual((counts[(detector,"train",False)],counts[(detector,"train",True)]),(6,6));self.assertEqual((counts[(detector,"calibration",False)],counts[(detector,"calibration",True)]),(5,5));self.assertEqual((counts[(detector,"holdout",False)],counts[(detector,"holdout",True)]),(4,4))
 def test_features_are_label_free_explainable_and_bound(self):
  samples,labels,split=build_soft_corpus();value=extract_features(samples,split);raw=canonical_json_bytes(value).decode();self.assertTrue(value["label_free"]);self.assertNotIn("expected_detected",raw);self.assertEqual(len(value["records"]),90);self.assertTrue(all(x["sample_hash"] and x["feature_hash"] and x["extractor_version"]=="v1" for x in value["records"]));shapes=defaultdict(set)
  for row in value["records"]:shapes[row["detector_id"]].update(row["features"])
  self.assertIn("persona_baseline_mismatch",shapes["persona_drift"]);self.assertIn("repeated_sentence_excess",shapes["trope_repeat"]);self.assertIn("filler_character_ratio",shapes["word_count_cheat"])
 def test_holdout_features_exist_but_labels_are_not_consumed(self):
  samples,labels,split=build_soft_corpus();features=extract_features(samples,split);holdout=[x for x in features["records"] if x["split"]=="holdout"];self.assertEqual(len(holdout),24);label_map={x["sample_id"]:x["expected_detected"] for x in labels["labels"]};self.assertEqual(sum(label_map[x["sample_id"]] for x in holdout),12);self.assertTrue(all("expected_detected" not in x and "label" not in x for x in holdout))
 def test_hash_tamper_and_cross_split_duplicate_are_rejected(self):
  samples,labels,split=build_soft_corpus();samples["samples"][0]["prose"]="tampered"
  with self.assertRaises(CalibrationIntegrityError):validate_soft_inputs(samples,split)
  samples,labels,split=build_soft_corpus();split["entries"][0]["sample_id"]=split["entries"][1]["sample_id"];base={k:v for k,v in split.items() if k!="split_hash"};from novel_kernel.storage import sha256_json;split["split_hash"]=sha256_json(base)
  with self.assertRaises(CalibrationIntegrityError):validate_soft_inputs(samples,split)
 def test_cli_outputs_match_versioned_gold_bytes(self):
  with tempfile.TemporaryDirectory() as temp:
   out=Path(temp)/"soft";a=subprocess.run([sys.executable,str(ROOT/"studio.py"),"calibrate","soft-corpus","--output-dir",str(out),"--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(a.returncode,0,a.stderr);features=out/"soft-features.v1.json";b=subprocess.run([sys.executable,str(ROOT/"studio.py"),"calibrate","features","--corpus",str(out/"soft-corpus.samples.v1.json"),"--split",str(out/"soft-split-manifest.v1.json"),"--output",str(features),"--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(b.returncode,0,b.stderr)
   for name in ("soft-corpus.samples.v1.json","soft-corpus.labels.v1.json","soft-split-manifest.v1.json","soft-features.v1.json"):self.assertEqual((GOLD/name).read_bytes(),(out/name).read_bytes(),name)
if __name__=="__main__":unittest.main()
