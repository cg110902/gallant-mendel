from __future__ import annotations
import json,unittest
from novel_kernel.provider_runtime import OpenAICompatibleRuntime,ProviderBudget,ProviderConfigError
from novel_kernel.storage import canonical_json_bytes,sha256_bytes
from novel_kernel.writer_runtime import RuntimeRequest
class ProviderRuntimeTests(unittest.TestCase):
 def request(self,limit=1000):
  data=canonical_json_bytes({"schema_version":"context-pack.v1","context_budget":{"hard_limit_chars":limit},"objective":"test"});return RuntimeRequest(data,sha256_bytes(data),"attempt_001")
 def test_endpoint_and_credentials_are_validated(self):
  for url in ("http://api.example/v1/chat/completions","https://key:secret@api.example/v1","https://api.example/v1?key=secret"):
   with self.assertRaises(ProviderConfigError):OpenAICompatibleRuntime(endpoint=url,model="m",api_key="secret")
 def test_success_has_bounded_request_and_usage(self):
  seen={}
  def transport(url,headers,body,timeout):
   seen.update(url=url,headers=headers,body=json.loads(body),timeout=timeout);return 200,json.dumps({"choices":[{"message":{"content":"候选正文"}}],"usage":{"completion_tokens":4,"total_tokens":20}}).encode()
  runtime=OpenAICompatibleRuntime(endpoint="https://api.example/v1/chat/completions",model="writer",api_key="top-secret",budget=ProviderBudget(100,20,100,5),transport=transport);r=runtime.invoke(self.request())
  self.assertTrue(r.ok);self.assertEqual(r.metadata["total_tokens"],20);self.assertEqual(seen["body"]["max_tokens"],20);self.assertEqual(seen["headers"]["Authorization"],"Bearer top-secret");self.assertNotIn("top-secret",json.dumps(runtime.invocation_metadata())+json.dumps(r.metadata))
 def test_output_and_usage_budget_are_hard_failures(self):
  def transport(*args):return 200,json.dumps({"choices":[{"message":{"content":"x"*11}}],"usage":{"completion_tokens":2,"total_tokens":3}}).encode()
  r=OpenAICompatibleRuntime(endpoint="https://api.example/v1",model="m",api_key="secret",budget=ProviderBudget(10,5,10,5),transport=transport).invoke(self.request());self.assertFalse(r.ok);self.assertEqual(r.error,"response budget exceeded")
 def test_http_failure_does_not_capture_body_or_key(self):
  def transport(*args):return 401,b'{"error":"top-secret diagnostic"}'
  r=OpenAICompatibleRuntime(endpoint="https://api.example/v1",model="m",api_key="top-secret",transport=transport).invoke(self.request());self.assertFalse(r.ok);self.assertNotIn("top-secret",r.stderr+r.error)
 def test_context_budget_is_checked_before_transport(self):
  called=[]
  runtime=OpenAICompatibleRuntime(endpoint="https://api.example/v1",model="m",api_key="secret",transport=lambda *x:called.append(x))
  r=runtime.invoke(self.request(limit=1));self.assertFalse(r.ok);self.assertFalse(called)
if __name__=="__main__":unittest.main()
