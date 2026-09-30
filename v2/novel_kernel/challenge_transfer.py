"""M6.5 frozen out-of-template transfer challenge for warning detectors."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .calibration import CalibrationIntegrityError,load_json
from .production import _publish
from .soft_calibration import FILLERS,_features
from .storage import canonical_json_bytes,sha256_bytes,sha256_json
from .threshold_calibration import CONFIG,validate_bundle

@dataclass(frozen=True)
class ChallengeReport:
 ok:bool;schema_version:str;output_dir:str;sample_count:int;tp:int;fp:int;tn:int;fn:int;challenge_hash:str;report_hash:str

def build_challenge()->dict[str,Any]:
 rows=[]
 for detector in ("persona_drift","trope_repeat","word_count_cheat"):
  for index in range(1,13):
   positive=index<=6;context={}
   if detector=="persona_drift":
    baseline=f"steady_{index}";context={"persona_baseline":baseline}
    if positive and index<=3:prose=f"换一种场景描述{index}。<!-- novel:persona "+canonical_json_bytes({"value":f"changed_{index}"}).decode()+" -->"
    elif positive:prose=f"在陌生压力下，他第{index}次表现得与往常性格完全相反。"
    elif index<=9:prose=f"角色维持一贯选择{index}。<!-- novel:persona "+canonical_json_bytes({"value":baseline}).decode()+" -->"
    else:prose=f"角色平稳完成不同任务{index}。"
   elif detector=="trope_repeat":
    if positive and index<=3:prose=(f"异形危机{index}再次逼近。"*4)+"场景转折。"
    elif positive:prose=(f"异形危机{index}再次逼近，"*5)+"但整段只使用一个句号。"
    else:prose="".join(f"挑战{index}发生互不重复的事件{n}。" for n in range(1,7))
   else:
    context={"filler_tokens":list(FILLERS)}
    if positive and index<=3:prose=(FILLERS[index%3]+"。")*30+f"挑战有效信息{index}。"
    elif positive:prose=("说到底。" if index%2 else "某种意义上。")*30+f"挑战有效信息{index}。"
    else:prose="".join(f"挑战{index}提供不同有效信息{n}。" for n in range(1,13))
   base={"sample_id":f"challenge_{detector}_{index:02d}","detector_id":detector,"prose":prose,"prose_hash":sha256_bytes(prose.encode()),"context":context,"expected_detected":positive,"template_relation":"in_contract" if positive and index<=3 else "out_of_template" if positive else "negative_control"};rows.append({**base,"sample_hash":sha256_json(base)})
 base={"schema_version":"soft-challenge-corpus.v1","challenge_id":"soft-transfer-challenge-v1","samples":rows};return {**base,"challenge_hash":sha256_json(base)}
def evaluate_challenge(corpus:dict,thresholds:dict)->dict[str,Any]:
 thresholds=validate_bundle(thresholds);base={k:v for k,v in corpus.items() if k!="challenge_hash"}
 if corpus.get("schema_version")!="soft-challenge-corpus.v1" or corpus.get("challenge_hash")!=sha256_json(base) or len(corpus.get("samples",[]))!=36:raise CalibrationIntegrityError("invalid challenge corpus")
 values={x["detector_id"]:x["threshold"]["value"] for x in thresholds["thresholds"]};results=[];matrices=[]
 for detector in ("persona_drift","trope_repeat","word_count_cheat"):
  rows=[]
  for sample in corpus["samples"]:
   if sample["detector_id"]!=detector:continue
   features=_features({"prose":sample["prose"],"detector_id":detector,"context":sample["context"]});metric,_=CONFIG[detector];raw=features.get(metric);value=float(raw) if isinstance(raw,(bool,int,float)) else None;detected=value is not None and value>=values[detector];expected=sample["expected_detected"];outcome="tp" if expected and detected else "fn" if expected else "fp" if detected else "tn";rows.append(outcome);results.append({"sample_id":sample["sample_id"],"detector_id":detector,"template_relation":sample["template_relation"],"feature_value":value,"threshold":values[detector],"expected_detected":expected,"actual_detected":detected,"outcome":outcome})
  counts={k:rows.count(k) for k in ("tp","fp","tn","fn")};matrices.append({"detector_id":detector,"sample_count":len(rows),**counts,"precision":None if counts["tp"]+counts["fp"]==0 else counts["tp"]/(counts["tp"]+counts["fp"]),"recall":counts["tp"]/(counts["tp"]+counts["fn"])})
 totals={k:sum(x[k] for x in matrices) for k in ("tp","fp","tn","fn")};base={"schema_version":"soft-challenge-report.v1","challenge_hash":corpus["challenge_hash"],"threshold_bundle_hash":thresholds["bundle_hash"],"sample_count":len(results),"matrices":matrices,"totals":totals,"results":sorted(results,key=lambda x:x["sample_id"]),"template_holdout_claim_separate":True};return {**base,"report_hash":sha256_json(base)}
class ChallengeTransferService:
 def run(self,thresholds_path:Path|str,output_dir:Path|str)->ChallengeReport:
  corpus=build_challenge();report=evaluate_challenge(corpus,load_json(Path(thresholds_path)));out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);_publish(out/"soft-challenge-corpus.v1.json",corpus);_publish(out/"soft-challenge-report.v1.json",report);t=report["totals"];return ChallengeReport(True,"soft-challenge-report.v1",str(out),report["sample_count"],t["tp"],t["fp"],t["tn"],t["fn"],corpus["challenge_hash"],report["report_hash"])
