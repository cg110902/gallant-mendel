"""M6.5 warning-only calibrated advisory audit for an approved Run."""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from .candidate_reconcile import _load
from .production import ProductionInputError,ProductionIntegrityError,_publish
from .soft_audit import _inputs
from .soft_calibration import FILLERS,PERSONA,_features
from .storage import atomic_write_json,sha256_json
from .threshold_calibration import CONFIG,validate_bundle

@dataclass(frozen=True)
class AdvisoryAuditReport:
 ok:bool;schema_version:str;book_id:str;task_id:str;run_id:str;state:str;finding_count:int;advisory_only:bool;blocking:bool;threshold_bundle_hash:str;advisory_audit_hash:str;reused:bool

def _persona_feature(text:str,pack:dict[str,Any])->tuple[dict[str,Any],str|None]:
 matches=PERSONA.findall(text);annotations=[]
 for raw in matches:
  try:value=json.loads(raw)
  except json.JSONDecodeError:continue
  if isinstance(value,dict) and set(value)=={"subject_id","value"} and all(isinstance(value[x],str) and value[x] for x in value):annotations.append(value)
 baselines={}
 for facet in pack["authoritative_context"]["facets"]:
  baseline=facet.get("payload",{}).get("persona_baseline")
  if facet.get("facet_type")=="psychology" and isinstance(baseline,str) and baseline:baselines[facet["object_id"]]=baseline
 if len(annotations)!=1:return {"annotation_count":len(matches),"baseline_present":False,"candidate_present":bool(annotations),"persona_baseline_mismatch":None},"requires exactly one valid subject-bound persona annotation"
 item=annotations[0];baseline=baselines.get(item["subject_id"])
 if baseline is None:return {"annotation_count":len(matches),"baseline_present":False,"candidate_present":True,"persona_baseline_mismatch":None},"subject has no frozen psychology.persona_baseline"
 return {"annotation_count":len(matches),"baseline_present":True,"candidate_present":True,"persona_baseline_mismatch":item["value"]!=baseline},None

def _as_number(value:Any)->float|None:
 if isinstance(value,bool):return float(value)
 if isinstance(value,(int,float)) and not isinstance(value,bool):return float(value)
 return None
class AdvisoryAuditor:
 def audit(self,book_root:Path|str,*,run_id:str,thresholds_path:Path|str,evaluated_at:str)->AdvisoryAuditReport:
  run,req,status,pack,claims,evidence,reconcile,hard=_inputs(Path(book_root),run_id);bundle=validate_bundle(_load(Path(thresholds_path)))
  try:when=datetime.fromisoformat(evaluated_at);start=datetime.fromisoformat(bundle["calibrated_at"]);end=datetime.fromisoformat(bundle["expires_at"])
  except (TypeError,ValueError) as exc:raise ProductionInputError("--evaluated-at and threshold dates must be ISO-8601") from exc
  if when.tzinfo is None or not start<=when<=end:raise ProductionInputError("advisory evaluation time is outside calibrated threshold validity")
  text=(run/"prose.md").read_text();thresholds={x["detector_id"]:x["threshold"]["value"] for x in bundle["thresholds"]};feature_rows=[];findings=[]
  persona,reason=_persona_feature(text,pack);feature_map={"persona_drift":(persona,reason),"trope_repeat":(_features({"prose":text,"detector_id":"trope_repeat","context":{}}),None),"word_count_cheat":(_features({"prose":text,"detector_id":"word_count_cheat","context":{"filler_tokens":list(FILLERS)}}),None)}
  for detector in ("persona_drift","trope_repeat","word_count_cheat"):
   features,unavailable=feature_map[detector];metric,_=CONFIG[detector];value=_as_number(features.get(metric));threshold=thresholds[detector];detected=value is not None and value>=threshold;row={"detector_id":detector,"metric":metric,"feature_value":value,"threshold":threshold,"detected":detected,"unavailable_reason":unavailable,"features":features};feature_rows.append(row)
   if detected:
    base={"detector_id":detector,"metric":metric,"feature_value":value,"threshold":threshold,"severity":"warning","message":f"calibrated advisory threshold matched: {metric} >= {threshold}"};findings.append({"finding_id":"advisory_"+sha256_json(base).removeprefix("sha256:")[:24],**base})
  report_base={"schema_version":"advisory-audit-report.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"prose_hash":status["review_prose_hash"],"hard_audit_hash":status["audit_hash"],"threshold_bundle_hash":bundle["bundle_hash"],"evaluated_at":evaluated_at,"advisory_only":True,"blocking":False,"thresholds_applied":True,"features":feature_rows,"findings":findings,"finding_count":len(findings)};audit_hash=sha256_json(report_base);doc={**report_base,"advisory_audit_hash":audit_hash};reused=_publish(run/"advisory-audit-report.json",doc);atomic_write_json(run/"status.json",{**status,"advisory_audit_hash":audit_hash});return AdvisoryAuditReport(True,"advisory-audit-report.v1",req["book_id"],req["task_id"],run_id,status["state"],len(findings),True,False,bundle["bundle_hash"],audit_hash,reused)
