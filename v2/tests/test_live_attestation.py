from __future__ import annotations
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.live_attestation import AttestationError,CHECK_IDS,finalize,template,write_template
from novel_kernel.storage import sha256_file
ROOT=Path(__file__).resolve().parents[1]
class LiveAttestationTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.input=self.root/"input.json";self.evidence=self.root/"transcript.txt";self.evidence.write_text("operator captured Antigravity transcript\n")
 def tearDown(self):self.t.cleanup()
 def complete(self):
  doc=template();doc.update({"ide_version":"1.2.3","os":"test-os","executed_at":"2026-09-30T18:00:00+08:00","operator":"human.editor"});binding={"path":"transcript.txt","sha256":sha256_file(self.evidence)}
  doc["checks"]=[{"id":x,"status":"pass","evidence":[binding]} for x in CHECK_IDS];self.input.write_text(json.dumps(doc));return doc
 def test_template_is_pending_and_never_claims_runtime_execution(self):
  doc=template();self.assertEqual(len(doc["checks"]),11);self.assertTrue(all(x["status"]=="pending" for x in doc["checks"]));self.assertNotIn("vendor_runtime_executed",doc)
  path=self.root/"template.json";write_template(path);self.assertEqual(json.loads(path.read_text())["vendor"],"antigravity")
 def test_complete_bundle_is_hash_bound_and_accepted(self):
  self.complete();report=finalize(self.input,self.root/"accepted.json");result=json.loads((self.root/"accepted.json").read_text());self.assertTrue(report.ok);self.assertTrue(result["vendor_runtime_executed"]);self.assertEqual((result["passed"],result["check_count"]),(11,11));self.assertTrue(result["surrogate_report_unchanged"])
  self.evidence.write_text("tampered")
  with self.assertRaises(AttestationError):finalize(self.input,self.root/"again.json")
 def test_pending_failed_missing_and_unsafe_evidence_are_rejected(self):
  doc=self.complete();doc["checks"][0]["status"]="pending";self.input.write_text(json.dumps(doc))
  with self.assertRaises(AttestationError):finalize(self.input,self.root/"out.json")
  doc=self.complete();doc["checks"][0]["evidence"][0]["path"]="../outside.txt";self.input.write_text(json.dumps(doc))
  with self.assertRaises(AttestationError):finalize(self.input,self.root/"out.json")
 def test_cli_prepare_and_attest(self):
  template_path=self.root/"template.json";p=subprocess.run([sys.executable,str(ROOT/"studio.py"),"ide","template","--output",str(template_path),"--json"],text=True,capture_output=True);self.assertEqual(p.returncode,0,p.stderr);self.assertFalse(json.loads(p.stdout)["vendor_runtime_executed"])
  self.complete();p=subprocess.run([sys.executable,str(ROOT/"studio.py"),"ide","attest","--input",str(self.input),"--output",str(self.root/"accepted.json"),"--json"],text=True,capture_output=True);self.assertEqual(p.returncode,0,p.stderr);self.assertTrue(json.loads(p.stdout)["vendor_runtime_executed"])
if __name__=="__main__":unittest.main()
