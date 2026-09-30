"""M7.2 portable-core compatibility surrogate shared by thin IDE adapters."""
from __future__ import annotations
import argparse,json,subprocess,sys,time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .storage import atomic_write_json,sha256_json
PLATFORMS=("antigravity","claude","cursor","codex")
CAPABILITIES=(
("skill_discovery","tests.test_agent_layout.AgentLayoutTests.test_four_layouts_have_at_least_ten_passing_checks"),
("workspace_init","tests.test_m0_cli.M0CliTests.test_init_creates_only_m0_layout"),
("context_pack","tests.test_production.ProductionTests.test_plan_and_context_are_deterministic_and_scoped"),
("writer_candidate","tests.test_writer_runtime.WriterRuntimeTests.test_offline_start_writes_only_candidate_run_artifacts"),
("writer_authority_guard","tests.test_writer_runtime.WriterRuntimeTests.test_authority_mutation_is_detected_and_blocks_run"),
("hard_error_detection","tests.test_hard_audit.HardAuditTests.test_dead_actor_rule"),
("hard_error_blocks_commit","tests.test_soft_audit.SoftAuditTests.test_hard_failed_cannot_approve_but_can_request_rework"),
("projection_rebuild","tests.test_projection.ProjectionTests.test_rebuild_is_logically_deterministic_and_survives_database_deletion"),
("interrupt_resume","tests.test_writer_runtime.WriterRuntimeTests.test_failed_attempt_is_evidenced_and_resume_uses_new_attempt"),
("no_api_key_doctor","tests.test_m0_cli.M0CliTests.test_doctor_no_api_key_returns_zero"),
)
@dataclass(frozen=True)
class CompatibilityReport:
 ok:bool;schema_version:str;platform_count:int;capability_count:int;portable_cases_passed:int;vendor_runtime_executed:bool;report_hash:str
class CompatibilityMatrix:
 def run(self,root:Path|str,*,output:Path|str)->CompatibilityReport:
  base=Path(root);portable=[]
  for capability,test_id in CAPABILITIES:
   started=time.monotonic();p=subprocess.run([sys.executable,"-m","unittest",test_id,"-v"],cwd=base,text=True,capture_output=True)
   portable.append({"capability":capability,"test_id":test_id,"passed":p.returncode==0,"exit_code":p.returncode,"duration_seconds":round(time.monotonic()-started,6),"stdout":p.stdout,"stderr":p.stderr})
  matrices=[]
  for platform in PLATFORMS:
   matrices.append({"platform":platform,"execution_mode":"portable_core_surrogate","vendor_runtime_executed":False,"cases":[{"capability":x["capability"],"status":"pass" if x["passed"] else "fail","evidence_test_id":x["test_id"]} for x in portable],"passed":sum(x["passed"] for x in portable),"total":len(portable)})
  document_base={"schema_version":"ide-compatibility-matrix.v1","ok":all(x["passed"] for x in portable),"portable_core_cases":portable,"platform_matrices":matrices,"platform_count":len(PLATFORMS),"capability_count":len(CAPABILITIES),"vendor_runtime_executed":False,"live_attestation_required":True,"claims":{"adapter_contract_tested":True,"real_vendor_ide_tested":False,"sandbox_enforcement_tested":False}}
  h=sha256_json(document_base);doc={**document_base,"report_hash":h};path=Path(output);path.parent.mkdir(parents=True,exist_ok=True);atomic_write_json(path,doc)
  return CompatibilityReport(all(x["passed"] for x in portable),"ide-compatibility-matrix.v1",4,10,sum(x["passed"] for x in portable),False,h)

def main(argv:list[str]|None=None)->int:
 parser=argparse.ArgumentParser(description="Run the M7.2 portable-core IDE compatibility surrogate")
 parser.add_argument("--output",type=Path,required=True)
 args=parser.parse_args(argv);report=CompatibilityMatrix().run(Path.cwd(),output=args.output)
 print(json.dumps({"ok":report.ok,"portable_cases_passed":report.portable_cases_passed,"output":str(args.output),"vendor_runtime_executed":False},sort_keys=True))
 return 0 if report.ok else 1

if __name__=="__main__":raise SystemExit(main())
