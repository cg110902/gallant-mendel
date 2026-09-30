"""M6.2 isolated execution of mutation gold samples through real M5 gates."""
from __future__ import annotations
import json,shutil,tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .calibration import EvaluationReport,evaluate,load_json,validate_corpus
from .candidate_reconcile import CandidateReconciler
from .events import EventLog
from .extraction import CandidateExtractor
from .hard_audit import HardInvariantAuditor
from .outline_bootstrap import OutlineBootstrapper
from .outline_compile import OutlineCompiler
from .production import ContextPackBuilder,ProductionInputError,ProductionPlanner
from .soft_audit import SoftAuditor
from .storage import atomic_write_json,canonical_json_bytes,sha256_json
from .writer_runtime import WriterRunController

@dataclass(frozen=True)
class MutationHarnessReport:
 ok:bool;schema_version:str;output_dir:str;corpus_hash:str;observation_count:int;detected_count:int;false_negative_count:int;authority_unchanged:bool;harness_hash:str

_DETECTORS={"extraction":("candidate_extractor","M5.1"),"reconcile":("candidate_reconciler","M5.2"),"hard_audit":("hard_invariant_auditor","M5.3"),"human_review":("semantic_audit","M5.4"),"calibrated_style":("style_audit_descriptive","M5.4")}

def _prepare(fixture:Path,prose:str,assumptions:dict[str,Any],root:Path)->tuple[Path,str,Path,bytes]:
 book=root/"book_demo";shutil.copytree(fixture,book/"outline");manifest=book/"outline"/"00-manifest.json";value=json.loads(manifest.read_text());value["status"]="approved";value["approval"]={"owner":"calibration","approved_at":"2026-09-29T18:00:00+08:00"};manifest.write_text(json.dumps(value))
 OutlineCompiler().compile(book/"outline");OutlineBootstrapper().bootstrap(book/"outline");plan=ProductionPlanner().plan(book,chapter_id="ch_001");run_id=plan.run_id;run=Path(plan.run_path);ContextPackBuilder().build(book,run_id=run_id);writer=WriterRunController();writer.start_task(book,task_id=plan.task_id);(run/"prose.md").write_text(prose);writer.request_review(book,run_id=run_id);writer.decide_review(book,run_id=run_id,decision="approve",actor="calibration")
 if assumptions.get("char_dead_status")=="dead":
  pack=json.loads((run/"context-pack.json").read_text());pack["authoritative_context"]["objects"].append({"object_id":"char_dead","type":"character","canonical_name":"亡者","aliases":[],"status":"active","created_event":"event_00000000000000000000000000000001","supersedes":None});pack["authoritative_context"]["objects"].sort(key=lambda x:x["object_id"]);pack["authoritative_context"]["facets"].append({"object_id":"char_dead","facet_type":"status","facet_version":1,"payload":{"state":"dead"},"valid_from":"story:initial","valid_to":None,"source_refs":["calibration:KillThenAct"],"recorded_event":"event_00000000000000000000000000000001"});pack["authoritative_context"]["facets"].sort(key=lambda x:(x["object_id"],x["facet_type"]));atomic_write_json(run/"context-pack.json",pack);status=json.loads((run/"status.json").read_text());status["context_hash"]=sha256_json(pack);atomic_write_json(run/"status.json",status)
 return book,run_id,run,EventLog(book).log_path.read_bytes()

def _execute(case:dict[str,Any],variant:str,fixture:Path)->tuple[dict[str,Any],dict[str,Any]]:
 prose=case[variant]["prose"];gate=case["expected_gate"];rule=case["expected_rule"];detector,version=_DETECTORS[gate];detected=False;evidence=[];terminal="not_run"
 with tempfile.TemporaryDirectory(prefix="mutation-harness-") as temp:
  book,run_id,run,before=_prepare(fixture,prose,case["oracle_assumptions"],Path(temp))
  if gate=="extraction":
   try:CandidateExtractor().extract(book,run_id=run_id);terminal="extracted"
   except ProductionInputError as exc:
    terminal="input_rejected"
    if rule=="unregistered_subject" and "claim subject is not registered" in str(exc):detected=True;evidence=["exception:unregistered_subject"]
    else:raise
  else:
   CandidateExtractor().extract(book,run_id=run_id);reconciled=CandidateReconciler().reconcile(book,run_id=run_id);terminal=reconciled.state
   if gate=="reconcile":
    hits=[x for x in reconciled.classifications if x["classification"]==rule];detected=bool(hits);evidence=[f"candidate-reconcile.json#{x['classification']}:{x['signature']}" for x in hits]
   else:
    hard=HardInvariantAuditor().audit(book,run_id=run_id);terminal=hard.state
    if gate=="hard_audit":
     hits=[x for x in hard.findings if x["rule_id"]==rule];detected=bool(hits);evidence=[f"hard-audit-report.json#{x['finding_id']}" for x in hits]
    elif gate=="human_review":
     SoftAuditor().semantic(book,run_id=run_id);semantic=json.loads((run/"semantic-audit-report.json").read_text());detected=rule in semantic.get("observations",[]);terminal="semantic_descriptive";evidence=[f"semantic-audit-report.json#{rule}"] if detected else []
    else:
     SoftAuditor().style(book,run_id=run_id);style=json.loads((run/"style-audit-report.json").read_text());detected=bool(style.get("thresholds_applied")) and rule in style.get("observations",[]);terminal="style_descriptive";evidence=[f"style-audit-report.json#{rule}"] if detected else []
  unchanged=before==EventLog(book).log_path.read_bytes()
  if not unchanged:raise RuntimeError(f"mutation harness changed authority: {case['sample_id']}:{variant}")
 observation={"sample_id":case["sample_id"],"variant":variant,"gate":gate,"detected":detected,"detector_id":detector,"detector_version":version,"evidence_refs":evidence}
 result={"sample_id":case["sample_id"],"mutator_id":case["mutator_id"],"variant":variant,"expected_gate":gate,"expected_rule":rule,"detected":detected,"detector_id":detector,"detector_version":version,"terminal":terminal,"authority_unchanged":True,"evidence_refs":evidence}
 return observation,result

class MutationHarness:
 def run(self,corpus_path:Path|str,fixture:Path|str,output_dir:Path|str,*,window_size:int=3)->MutationHarnessReport:
  corpus=validate_corpus(load_json(Path(corpus_path)));fixture_path=Path(fixture)
  if not (fixture_path/"00-manifest.json").is_file():raise ProductionInputError(f"outline fixture is invalid: {fixture_path}")
  detections=[];results=[]
  for case in corpus["mutations"]:
   for variant in ("clean","mutated"):
    observation,result=_execute(case,variant,fixture_path);detections.append(observation);results.append(result)
  observations={"schema_version":"mutation-observations.v1","detections":detections,"chapter_errors":[]};calibration=evaluate(corpus,observations,window_size);out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);atomic_write_json(out/"mutation-observations.v1.json",observations);atomic_write_json(out/"calibration-report.v1.json",calibration)
  false_negatives=sum(x["outcome"]=="fn" for x in calibration["detections"]);base={"schema_version":"mutation-harness-report.v1","corpus_hash":corpus["corpus_hash"],"observations_hash":sha256_json(observations),"calibration_report_hash":calibration["evaluation_hash"],"observation_count":len(detections),"detected_count":sum(x["detected"] for x in detections),"false_negative_count":false_negatives,"authority_unchanged":all(x["authority_unchanged"] for x in results),"runs":results};h=sha256_json(base);atomic_write_json(out/"mutation-harness-report.v1.json",{**base,"harness_hash":h})
  return MutationHarnessReport(True,"mutation-harness-report.v1",str(out),corpus["corpus_hash"],len(detections),sum(x["detected"] for x in detections),false_negatives,True,h)
