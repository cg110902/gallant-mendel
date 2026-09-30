from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from novel_kernel.compatibility_matrix import CAPABILITIES,PLATFORMS,CompatibilityMatrix
ROOT=Path(__file__).resolve().parents[1]
class CompatibilityMatrixTests(unittest.TestCase):
 def test_four_surrogate_matrices_execute_ten_portable_capabilities(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/"matrix.json";report=CompatibilityMatrix().run(ROOT,output=path);doc=json.loads(path.read_text())
   self.assertTrue(report.ok);self.assertEqual(len(CAPABILITIES),10);self.assertEqual(len(PLATFORMS),4);self.assertEqual(report.portable_cases_passed,10);self.assertFalse(report.vendor_runtime_executed)
   self.assertTrue(doc["live_attestation_required"]);self.assertFalse(doc["claims"]["real_vendor_ide_tested"])
   for matrix in doc["platform_matrices"]:
    self.assertEqual((matrix["passed"],matrix["total"]),(10,10));self.assertEqual(matrix["execution_mode"],"portable_core_surrogate");self.assertFalse(matrix["vendor_runtime_executed"])
if __name__=="__main__":unittest.main()
