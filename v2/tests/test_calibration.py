from __future__ import annotations
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.calibration import MUTATORS,CalibrationInputError,CalibrationIntegrityError,build_corpus,evaluate,validate_corpus,validate_threshold
from novel_kernel.storage import canonical_json_bytes
ROOT=Path(__file__).resolve().parents[1]
def observations(corpus):
 detections=[]
 detected={"KillThenAct","GhostCharacter","TimeReversal","KnowledgeLeak","HookRemoval","ForeshadowGhost","PowerJump"}
 for case in corpus["mutations"]:
  for variant in ("clean","mutated"):
   hit=variant=="mutated" and case["mutator_id"] in detected
   detections.append({"sample_id":case["sample_id"],"variant":variant,"gate":case["expected_gate"],"detected":hit,"detector_id":"m5-baseline","detector_version":"M5","evidence_refs":[]})
 return {"schema_version":"mutation-observations.v1","detections":detections,"chapter_errors":[{"chapter_index":1,"consistency_error_count":0},{"chapter_index":2,"consistency_error_count":1},{"chapter_index":3,"consistency_error_count":2},{"chapter_index":4,"consistency_error_count":0}]}
class CalibrationTests(unittest.TestCase):
 def test_offline_corpus_is_deterministic_complete_and_api_free(self):
  a=build_corpus();b=build_corpus();self.assertEqual(canonical_json_bytes(a),canonical_json_bytes(b));self.assertEqual(tuple(x["mutator_id"] for x in a["mutations"]),MUTATORS);self.assertEqual(len(a["mutations"]),10);self.assertFalse(a["oracle"]["external_api_used"]);validate_corpus(a)
  self.assertTrue(all(x["clean"]["expected_detected"] is False and x["mutated"]["expected_detected"] is True for x in a["mutations"]))
 def test_honest_confusion_matrices_record_soft_false_negatives(self):
  corpus=build_corpus();report=evaluate(corpus,observations(corpus),3);by={x["gate"]:x for x in report["confusion_matrices"]}
  self.assertEqual((by["hard_audit"]["tp"],by["hard_audit"]["fn"],by["hard_audit"]["fp"],by["hard_audit"]["tn"]),(5,0,0,5));self.assertEqual((by["human_review"]["fn"],by["calibrated_style"]["fn"]),(1,2));self.assertEqual(by["calibrated_style"]["recall"],0.0);self.assertEqual([x["ced"] for x in report["ced"]["windows"]],[1.0,1.0])
 def test_false_positive_and_null_denominator_are_not_hidden(self):
  corpus=build_corpus();value=observations(corpus);row=next(x for x in value["detections"] if x["variant"]=="clean" and x["gate"]=="extraction");row["detected"]=True;report=evaluate(corpus,value,5);gate=next(x for x in report["confusion_matrices"] if x["gate"]=="extraction");self.assertEqual(gate["fp"],1);self.assertEqual(gate["precision"],0.5);self.assertEqual(report["ced"]["windows"],[])
 def test_tamper_incomplete_observations_and_noncontiguous_ced_fail(self):
  corpus=build_corpus();corpus["mutations"][0]["mutated"]["prose"]="tampered"
  with self.assertRaises(CalibrationIntegrityError):validate_corpus(corpus)
  corpus=build_corpus();value=observations(corpus);value["detections"].pop()
  with self.assertRaises(CalibrationIntegrityError):evaluate(corpus,value,3)
  value=observations(corpus);value["chapter_errors"][2]["chapter_index"]=4
  with self.assertRaises(CalibrationIntegrityError):evaluate(corpus,value,3)
 def test_threshold_requires_provenance_distribution_and_expiry(self):
  value={"schema_version":"calibrated-threshold.v1","metric":"repetition_rate","value":0.18,"severity":"warning","calibrated_at":"2026-09-29T00:00:00+00:00","sample_size":120,"distribution":{"p50":0.07,"p90":0.16,"p99":0.24},"rationale":"controlled corpus quantiles","owner":"quality","expires_at":"2026-12-29T00:00:00+00:00","corpus_hash":"sha256:"+"1"*64,"calibration_report_hash":"sha256:"+"2"*64};self.assertEqual(validate_threshold(value),value)
  value["distribution"]={"p50":0.2,"p90":0.1,"p99":0.3}
  with self.assertRaises(CalibrationInputError):validate_threshold(value)
 def test_cli_writes_corpus_and_evaluation(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);corpus=root/"corpus.json";x=subprocess.run([sys.executable,str(ROOT/"studio.py"),"calibrate","corpus","--output",str(corpus),"--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(x.returncode,0,x.stderr);self.assertEqual(json.loads(x.stdout)["mutation_count"],10)
   value=json.loads(corpus.read_text());obs=root/"observations.json";obs.write_text(json.dumps(observations(value)));report=root/"report.json";y=subprocess.run([sys.executable,str(ROOT/"studio.py"),"calibrate","evaluate","--corpus",str(corpus),"--observations",str(obs),"--output",str(report),"--window-size","3","--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(y.returncode,0,y.stderr);self.assertEqual(json.loads(y.stdout)["observation_count"],20);self.assertTrue(report.is_file())
if __name__=="__main__":unittest.main()
