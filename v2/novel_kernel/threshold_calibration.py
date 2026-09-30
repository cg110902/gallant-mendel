"""M6.4 threshold selection and one-shot holdout receipt."""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from .calibration import CalibrationInputError,CalibrationIntegrityError,load_json,validate_threshold
from .production import _publish
from .soft_calibration import DETECTORS,validate_soft_inputs,validate_soft_labels
from .storage import sha256_json

CONFIG={"persona_drift":("persona_baseline_mismatch",">="),"trope_repeat":("repeated_sentence_excess",">="),"word_count_cheat":("filler_character_ratio",">=")}
@dataclass(frozen=True)
class ThresholdBundleReport:
 ok:bool;schema_version:str;output_path:str;bundle_hash:str;selection_hash:str;threshold_count:int;reused:bool
@dataclass(frozen=True)
class HoldoutReport:
 ok:bool;schema_version:str;output_path:str;threshold_bundle_hash:str;holdout_count:int;tp:int;fp:int;tn:int;fn:int;receipt_hash:str;reused:bool

def _number(value:Any)->float:
 if isinstance(value,bool):return float(value)
 if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):return float(value)
 raise CalibrationIntegrityError("calibration feature must be a finite number or boolean")
def _confusion(rows:list[tuple[float,bool]],threshold:float)->dict[str,Any]:
 tp=sum(label and value>=threshold for value,label in rows);fp=sum(not label and value>=threshold for value,label in rows);tn=sum(not label and value<threshold for value,label in rows);fn=sum(label and value<threshold for value,label in rows);tpr=None if tp+fn==0 else tp/(tp+fn);tnr=None if tn+fp==0 else tn/(tn+fp);balanced=None if tpr is None or tnr is None else (tpr+tnr)/2
 return {"tp":tp,"fp":fp,"tn":tn,"fn":fn,"precision":None if tp+fp==0 else tp/(tp+fp),"recall":tpr,"balanced_accuracy":balanced}
def _quantile(values:list[float],p:float)->float:
 if not values:raise CalibrationIntegrityError("cannot calibrate an empty distribution")
 ordered=sorted(values);return ordered[max(0,math.ceil(p*len(ordered))-1)]
def _candidates(values:list[float])->list[float]:
 unique=sorted(set(values));return sorted(set(unique+[(a+b)/2 for a,b in zip(unique,unique[1:])]))
def _bindings(features:dict,labels:dict,split:dict)->tuple[dict[str,dict],dict[str,bool],dict[str,str]]:
 if features.get("schema_version")!="soft-features.v1" or features.get("label_free") is not True:raise CalibrationInputError("invalid soft features")
 feature_base={k:v for k,v in features.items() if k!="features_hash"}
 if features.get("features_hash")!=sha256_json(feature_base) or features.get("split_hash")!=split.get("split_hash") or features.get("samples_hash")!=split.get("samples_hash"):raise CalibrationIntegrityError("feature hash/bindings mismatch")
 by_id={x["sample_id"]:x for x in features.get("records",[])}
 if len(by_id)!=90:raise CalibrationIntegrityError("features require 90 unique records")
 labels_by={x["sample_id"]:x["expected_detected"] for x in labels["labels"]};parts={x["sample_id"]:x["split"] for x in split["entries"]}
 if set(by_id)!=set(labels_by) or set(by_id)!=set(parts):raise CalibrationIntegrityError("features, labels, and split IDs differ")
 return by_id,labels_by,parts
def select_thresholds(features:dict,labels:dict,split:dict,*,calibrated_at:str,expires_at:str,owner:str)->dict[str,Any]:
 # validate labels against an immutable sample binding without requiring prose at this layer
 if split.get("schema_version")!="soft-split-manifest.v1" or labels.get("schema_version")!="soft-corpus.labels.v1" or labels.get("samples_hash")!=split.get("samples_hash"):raise CalibrationIntegrityError("labels/split binding mismatch")
 for doc,field in ((labels,"labels_hash"),(split,"split_hash")):
  if doc.get(field)!=sha256_json({k:v for k,v in doc.items() if k!=field}):raise CalibrationIntegrityError(f"{field} mismatch")
 if not isinstance(owner,str) or not owner:raise CalibrationInputError("threshold owner is required")
 try:start=datetime.fromisoformat(calibrated_at);end=datetime.fromisoformat(expires_at)
 except (TypeError,ValueError) as exc:raise CalibrationInputError("threshold dates must be ISO-8601") from exc
 if start.tzinfo is None or end.tzinfo is None or end<=start:raise CalibrationInputError("threshold expiry must follow timezone-aware calibration time")
 by_id,gold,parts=_bindings(features,labels,split);selections=[]
 for detector in DETECTORS:
  metric,direction=CONFIG[detector];train=[];calibration=[]
  for sid,row in by_id.items():
   if row["detector_id"]!=detector:continue
   value=_number(row["features"].get(metric));pair=(value,gold[sid])
   if parts[sid]=="train":train.append(pair)
   elif parts[sid]=="calibration":calibration.append(pair)
  candidates=_candidates([x[0] for x in train]);scored=[]
  for threshold in candidates:
   train_metrics=_confusion(train,threshold);calibration_metrics=_confusion(calibration,threshold);score=calibration_metrics["balanced_accuracy"]
   if score is None:raise CalibrationIntegrityError("calibration split lacks positive or negative class")
   scored.append((score,-calibration_metrics["fp"],calibration_metrics["tp"],threshold,train_metrics,calibration_metrics))
  winner=max(scored,key=lambda x:(x[0],x[1],x[2],x[4]["balanced_accuracy"],x[3]));values=[x[0] for x in train+calibration];selections.append({"detector_id":detector,"metric":metric,"direction":direction,"threshold":winner[3],"candidate_count":len(candidates),"train_sample_count":len(train),"calibration_sample_count":len(calibration),"train_metrics":winner[4],"calibration_metrics":winner[5],"distribution":{"p50":_quantile(values,.5),"p90":_quantile(values,.9),"p99":_quantile(values,.99)}})
 selection_base={"schema_version":"soft-threshold-selection.v1","samples_hash":features["samples_hash"],"labels_hash":labels["labels_hash"],"split_hash":split["split_hash"],"features_hash":features["features_hash"],"extractor_id":"soft_feature_extractor","extractor_version":"v1","selection_policy":"train-candidates-calibration-then-train-balanced-accuracy-v1","calibrated_at":calibrated_at,"expires_at":expires_at,"owner":owner,"selections":selections};selection_hash=sha256_json(selection_base);thresholds=[]
 for item in selections:
  threshold={"schema_version":"calibrated-threshold.v1","metric":item["metric"],"value":item["threshold"],"severity":"warning","calibrated_at":calibrated_at,"sample_size":item["train_sample_count"]+item["calibration_sample_count"],"distribution":item["distribution"],"rationale":f"{item['detector_id']} train candidates selected on frozen calibration split","owner":owner,"expires_at":expires_at,"corpus_hash":features["samples_hash"],"calibration_report_hash":selection_hash};validate_threshold(threshold);thresholds.append({"detector_id":item["detector_id"],"threshold":threshold})
 base={**selection_base,"selection_hash":selection_hash,"holdout_used":False,"thresholds":thresholds};return {**base,"bundle_hash":sha256_json(base)}
def validate_bundle(bundle:dict[str,Any])->dict[str,Any]:
 if bundle.get("schema_version")!="soft-threshold-selection.v1" or bundle.get("holdout_used") is not False:raise CalibrationInputError("invalid or already-used threshold bundle")
 base={k:v for k,v in bundle.items() if k!="bundle_hash"}
 if bundle.get("bundle_hash")!=sha256_json(base):raise CalibrationIntegrityError("threshold bundle hash mismatch")
 selection_base={k:v for k,v in bundle.items() if k not in {"selection_hash","holdout_used","thresholds","bundle_hash"}}
 if bundle.get("selection_hash")!=sha256_json(selection_base):raise CalibrationIntegrityError("threshold selection hash mismatch")
 seen=set()
 for item in bundle.get("thresholds",[]):
  detector=item.get("detector_id");threshold=validate_threshold(item.get("threshold",{}))
  if detector not in DETECTORS or detector in seen or threshold["calibration_report_hash"]!=bundle["selection_hash"] or threshold["corpus_hash"]!=bundle["samples_hash"]:raise CalibrationIntegrityError("invalid threshold binding")
  seen.add(detector)
 if seen!=set(DETECTORS):raise CalibrationIntegrityError("threshold bundle is incomplete")
 return bundle
def evaluate_holdout(bundle:dict,features:dict,labels:dict,split:dict)->dict[str,Any]:
 bundle=validate_bundle(bundle)
 if any(bundle.get(k)!=v for k,v in (("features_hash",features.get("features_hash")),("labels_hash",labels.get("labels_hash")),("split_hash",split.get("split_hash")),("samples_hash",features.get("samples_hash")))):raise CalibrationIntegrityError("holdout inputs differ from threshold bindings")
 by_id,gold,parts=_bindings(features,labels,split);thresholds={x["detector_id"]:x["threshold"]["value"] for x in bundle["thresholds"]};rows=[];matrices=[]
 for detector in DETECTORS:
  metric,_=CONFIG[detector];pairs=[]
  for sid in sorted(by_id):
   row=by_id[sid]
   if row["detector_id"]!=detector or parts[sid]!="holdout":continue
   value=_number(row["features"].get(metric));detected=value>=thresholds[detector];pairs.append((value,gold[sid]));rows.append({"sample_id":sid,"detector_id":detector,"feature_value":value,"threshold":thresholds[detector],"expected_detected":gold[sid],"actual_detected":detected,"outcome":"tp" if gold[sid] and detected else "fn" if gold[sid] else "fp" if detected else "tn"})
  matrices.append({"detector_id":detector,"sample_count":len(pairs),**_confusion(pairs,thresholds[detector])})
 totals={key:sum(x[key] for x in matrices) for key in ("tp","fp","tn","fn")};base={"schema_version":"soft-holdout-report.v1","threshold_bundle_hash":bundle["bundle_hash"],"labels_hash":labels["labels_hash"],"split_hash":split["split_hash"],"features_hash":features["features_hash"],"one_shot":True,"holdout_count":len(rows),"matrices":matrices,"totals":totals,"results":rows};return {**base,"receipt_hash":sha256_json(base)}
class ThresholdCalibrationService:
 def write_thresholds(self,features_path:Path|str,labels_path:Path|str,split_path:Path|str,output:Path|str,*,calibrated_at:str,expires_at:str,owner:str)->ThresholdBundleReport:
  bundle=select_thresholds(load_json(Path(features_path)),load_json(Path(labels_path)),load_json(Path(split_path)),calibrated_at=calibrated_at,expires_at=expires_at,owner=owner);reused=_publish(Path(output),bundle);return ThresholdBundleReport(True,"soft-threshold-selection.v1",str(output),bundle["bundle_hash"],bundle["selection_hash"],len(bundle["thresholds"]),reused)
 def write_holdout(self,thresholds_path:Path|str,features_path:Path|str,labels_path:Path|str,split_path:Path|str,output:Path|str)->HoldoutReport:
  report=evaluate_holdout(load_json(Path(thresholds_path)),load_json(Path(features_path)),load_json(Path(labels_path)),load_json(Path(split_path)));reused=_publish(Path(output),report);totals=report["totals"];return HoldoutReport(True,"soft-holdout-report.v1",str(output),report["threshold_bundle_hash"],report["holdout_count"],totals["tp"],totals["fp"],totals["tn"],totals["fn"],report["receipt_hash"],reused)
