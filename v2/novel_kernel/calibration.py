"""M6.1 deterministic offline oracle, mutation corpus, and honest metrics."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
from typing import Any
from datetime import datetime
import json
from .outline import OutlineError
from .storage import atomic_write_json,canonical_json_bytes,sha256_bytes,sha256_json

MUTATORS=("KillThenAct","GhostCharacter","TimeReversal","KnowledgeLeak","PersonaDrift","HookRemoval","ForeshadowGhost","PowerJump","TropeRepeat","WordCountCheat")
GATES=frozenset({"extraction","reconcile","hard_audit","human_review","calibrated_style"})
class CalibrationInputError(OutlineError):exit_code=1
class CalibrationIntegrityError(OutlineError):exit_code=6
@dataclass(frozen=True)
class CorpusReport:
 ok:bool;schema_version:str;output_path:str;corpus_hash:str;mutation_count:int;control_count:int
@dataclass(frozen=True)
class EvaluationReport:
 ok:bool;schema_version:str;output_path:str;corpus_hash:str;evaluation_hash:str;observation_count:int;gate_count:int;window_count:int

def _claim(subject:str,predicate:str,value:Any)->str:
 payload=canonical_json_bytes({"subject_id":subject,"predicate":predicate,"value":value}).decode()
 return f"<!-- novel:claim {payload} -->"
def _correct()->str:return "凌云的身份已经暴露。"+_claim("char_lin_yun","status","exposed")
def _case(mutator:str,index:int)->dict[str,Any]:
 clean=_correct();specs={
  "KillThenAct":("亡者仍然挥剑。"+_claim("char_dead","acts","draws_sword"),"hard_audit","dead_actor",{"char_dead_status":"dead"},"dead subject receives an action claim"),
  "GhostCharacter":("陌生人现身。"+_claim("char_ghost","status","active"),"extraction","unregistered_subject",{"registered_objects_exclude":"char_ghost"},"claim subject is absent from frozen objects"),
  "TimeReversal":("时间退回开篇之前。"+_claim("char_lin_yun","story_time","story:0000"),"hard_audit","time_window",{"chapter_window":["story:0001","story:0002"]},"story time falls before frozen chapter window"),
  "KnowledgeLeak":("凌云说出了未知秘密。"+_claim("char_lin_yun","knows","fact_hidden_lineage"),"hard_audit","knowledge_boundary",{"knowledge_edge_absent":["char_lin_yun","fact_hidden_lineage"]},"knowledge claim lacks frozen holder edge"),
  "PersonaDrift":("凌云突然以相反人格行事。"+_claim("char_lin_yun","persona","reckless_cruel"),"human_review","persona_drift",{"persona_baseline":"cautious_compassionate"},"persona differs from controlled baseline; deterministic detector not yet calibrated"),
  "HookRemoval":("凌云只是沉默。","reconcile","intent_missing",{"required_change":"char_lin_yun.status=exposed"},"required change annotation and fulfillment are removed"),
  "ForeshadowGhost":("不存在的伏笔被兑现。"+_claim("char_lin_yun","obligation_touch","obligation_missing"),"hard_audit","obligation_active",{"open_obligations_exclude":"obligation_missing"},"claim touches an obligation absent from frozen open set"),
  "PowerJump":("凌云无前置地瞬移。"+_claim("char_lin_yun","capability_use","teleport"),"hard_audit","capability_prerequisite",{"capabilities_exclude":"teleport"},"capability use lacks frozen prerequisite"),
  "TropeRepeat":("危机突然出现。"*8+_claim("char_lin_yun","status","exposed"),"calibrated_style","trope_repeat",{"reference_ngram":"危机突然出现"},"repeated trope phrase; threshold intentionally not supplied"),
  "WordCountCheat":("其实。"*80+_claim("char_lin_yun","status","exposed"),"calibrated_style","word_count_cheat",{"padding_token":"其实"},"padding inflates length without calibrated content threshold"),
 }
 prose,gate,rule,assumptions,description=specs[mutator];base={"sample_id":f"mutation_{index:02d}_{mutator.lower()}","mutator_id":mutator,"oracle_version":"offline-writer.v1","clean":{"prose":clean,"prose_hash":sha256_bytes(clean.encode()),"expected_detected":False},"mutated":{"prose":prose,"prose_hash":sha256_bytes(prose.encode()),"expected_detected":True},"expected_gate":gate,"expected_rule":rule,"oracle_assumptions":assumptions,"mutation_evidence":{"description":description,"mutated_excerpt":prose[:160]}}
 return {**base,"sample_hash":sha256_json(base)}
def build_corpus()->dict[str,Any]:
 cases=[_case(name,index) for index,name in enumerate(MUTATORS,1)];base={"schema_version":"mutation-corpus.v1","corpus_id":"m6_controlled_mutations_v1","oracle":{"writer_id":"offline-writer","writer_version":"v1","external_api_used":False,"seed":"m6-fixed-v1","controlled_correct_prose":_correct(),"controlled_correct_prose_hash":sha256_bytes(_correct().encode())},"gate_taxonomy":sorted(GATES),"mutations":cases}
 return {**base,"corpus_hash":sha256_json(base)}
def validate_corpus(value:dict[str,Any])->dict[str,Any]:
 if not isinstance(value,dict) or value.get("schema_version")!="mutation-corpus.v1":raise CalibrationInputError("invalid mutation corpus schema_version")
 base={k:v for k,v in value.items() if k!="corpus_hash"}
 if value.get("corpus_hash")!=sha256_json(base):raise CalibrationIntegrityError("mutation corpus hash mismatch")
 mutations=value.get("mutations")
 if not isinstance(mutations,list) or [x.get("mutator_id") for x in mutations]!=list(MUTATORS):raise CalibrationIntegrityError("mutation corpus must contain the frozen ten mutators in order")
 ids=set()
 for case in mutations:
  case_base={k:v for k,v in case.items() if k!="sample_hash"}
  if case.get("sample_hash")!=sha256_json(case_base):raise CalibrationIntegrityError(f"mutation sample hash mismatch: {case.get('sample_id')}")
  if case.get("sample_id") in ids or case.get("expected_gate") not in GATES:raise CalibrationIntegrityError("duplicate sample ID or unknown expected gate")
  ids.add(case["sample_id"])
  for variant,expected in (("clean",False),("mutated",True)):
   item=case.get(variant,{});prose=item.get("prose")
   if not isinstance(prose,str) or item.get("prose_hash")!=sha256_bytes(prose.encode()) or item.get("expected_detected") is not expected:raise CalibrationIntegrityError(f"invalid {variant} oracle: {case['sample_id']}")
 return value
def _matrix(tp:int,fp:int,tn:int,fn:int)->dict[str,Any]:
 return {"tp":tp,"fp":fp,"tn":tn,"fn":fn,"precision":None if tp+fp==0 else tp/(tp+fp),"recall":None if tp+fn==0 else tp/(tp+fn)}
def evaluate(corpus:dict[str,Any],observations:dict[str,Any],window_size:int)->dict[str,Any]:
 corpus=validate_corpus(corpus)
 if not isinstance(window_size,int) or isinstance(window_size,bool) or window_size<1:raise CalibrationInputError("window size must be a positive integer")
 if observations.get("schema_version")!="mutation-observations.v1":raise CalibrationInputError("invalid observations schema_version")
 rows=observations.get("detections");errors=observations.get("chapter_errors")
 if not isinstance(rows,list) or not isinstance(errors,list):raise CalibrationInputError("observations require detections and chapter_errors arrays")
 expected={}
 for case in corpus["mutations"]:
  for variant in ("clean","mutated"):expected[(case["sample_id"],variant)]=(case[variant]["expected_detected"],case["expected_gate"])
 seen={};normalized=[]
 for row in rows:
  if not isinstance(row,dict):raise CalibrationInputError("detection observation must be an object")
  key=(row.get("sample_id"),row.get("variant"))
  if key not in expected or key in seen:raise CalibrationIntegrityError("unknown or duplicate detection observation")
  if not isinstance(row.get("detected"),bool) or not isinstance(row.get("detector_id"),str) or not row["detector_id"] or not isinstance(row.get("detector_version"),str) or not row["detector_version"]:raise CalibrationInputError("detection requires boolean result and detector identity/version")
  exp,gate=expected[key]
  if row.get("gate")!=gate:raise CalibrationIntegrityError(f"observation gate mismatch: {key[0]}:{key[1]}")
  outcome="tp" if exp and row["detected"] else "fn" if exp else "fp" if row["detected"] else "tn";seen[key]=True;normalized.append({"sample_id":key[0],"variant":key[1],"gate":gate,"expected_detected":exp,"actual_detected":row["detected"],"outcome":outcome,"detector_id":row["detector_id"],"detector_version":row["detector_version"],"evidence_refs":row.get("evidence_refs",[])})
 if set(seen)!=set(expected):raise CalibrationIntegrityError(f"incomplete observations: expected {len(expected)}, got {len(seen)}")
 matrices=[]
 for gate in sorted(GATES):
  group=[x for x in normalized if x["gate"]==gate];counts={name:sum(x["outcome"]==name for x in group) for name in ("tp","fp","tn","fn")};matrices.append({"gate":gate,"sample_count":len(group),**_matrix(**counts)})
 chapter=[]
 for row in errors:
  if not isinstance(row,dict) or isinstance(row.get("chapter_index"),bool) or not isinstance(row.get("chapter_index"),int) or row["chapter_index"]<1 or isinstance(row.get("consistency_error_count"),bool) or not isinstance(row.get("consistency_error_count"),int) or row["consistency_error_count"]<0:raise CalibrationInputError("invalid chapter error observation")
  chapter.append((row["chapter_index"],row["consistency_error_count"]))
 chapter.sort();
 if len({x[0] for x in chapter})!=len(chapter) or any(b[0]!=a[0]+1 for a,b in zip(chapter,chapter[1:])):raise CalibrationIntegrityError("chapter error indexes must be unique and contiguous")
 windows=[]
 for i in range(0,max(0,len(chapter)-window_size+1)):
  part=chapter[i:i+window_size];count=sum(x[1] for x in part);windows.append({"start_chapter":part[0][0],"end_chapter":part[-1][0],"chapter_count":window_size,"consistency_error_count":count,"ced":count/window_size})
 base={"schema_version":"calibration-report.v1","corpus_hash":corpus["corpus_hash"],"observation_count":len(normalized),"confusion_matrices":matrices,"ced":{"definition":"consistency errors per chapter in a fixed contiguous chapter window","window_size":window_size,"windows":windows},"detections":sorted(normalized,key=lambda x:(x["sample_id"],x["variant"]))};return {**base,"evaluation_hash":sha256_json(base)}
def validate_threshold(value:dict[str,Any])->dict[str,Any]:
 required={"schema_version","metric","value","severity","calibrated_at","sample_size","distribution","rationale","owner","expires_at","corpus_hash","calibration_report_hash"}
 if not isinstance(value,dict) or set(value)!=required or value.get("schema_version")!="calibrated-threshold.v1":raise CalibrationInputError("invalid calibrated threshold fields")
 if not isinstance(value["metric"],str) or not value["metric"] or isinstance(value["value"],bool) or not isinstance(value["value"],(int,float)) or value["severity"] not in {"info","warning","hard"}:raise CalibrationInputError("invalid threshold metric, value, or severity")
 if isinstance(value["sample_size"],bool) or not isinstance(value["sample_size"],int) or value["sample_size"]<1 or not all(isinstance(value[x],str) and value[x] for x in ("rationale","owner")):raise CalibrationInputError("threshold requires positive sample size, rationale, and owner")
 dist=value["distribution"]
 if not isinstance(dist,dict) or set(dist)!={"p50","p90","p99"} or any(isinstance(dist[x],bool) or not isinstance(dist[x],(int,float)) for x in dist) or not dist["p50"]<=dist["p90"]<=dist["p99"]:raise CalibrationInputError("threshold distribution must have ordered p50/p90/p99")
 try:start=datetime.fromisoformat(value["calibrated_at"]);end=datetime.fromisoformat(value["expires_at"])
 except (TypeError,ValueError) as exc:raise CalibrationInputError("threshold dates must be ISO-8601") from exc
 if start.tzinfo is None or end.tzinfo is None or end<=start:raise CalibrationInputError("threshold expiry must be after timezone-aware calibration time")
 for field in ("corpus_hash","calibration_report_hash"):
  token=value[field]
  if not isinstance(token,str) or len(token)!=71 or not token.startswith("sha256:") or any(x not in "0123456789abcdef" for x in token[7:]):raise CalibrationInputError(f"invalid {field}")
 return json.loads(canonical_json_bytes(value).decode())

def load_json(path:Path)->dict[str,Any]:
 try:value=json.loads(path.read_text())
 except (OSError,json.JSONDecodeError) as exc:raise CalibrationInputError(f"cannot read JSON {path}: {exc}") from exc
 if not isinstance(value,dict):raise CalibrationInputError(f"JSON root must be object: {path}")
 return value
class CalibrationService:
 def write_corpus(self,output:Path|str)->CorpusReport:
  path=Path(output);path.parent.mkdir(parents=True,exist_ok=True);corpus=build_corpus();atomic_write_json(path,corpus);return CorpusReport(True,"mutation-corpus.v1",str(path),corpus["corpus_hash"],len(corpus["mutations"]),len(corpus["mutations"]))
 def write_evaluation(self,corpus_path:Path|str,observations_path:Path|str,output:Path|str,*,window_size:int=3)->EvaluationReport:
  corpus=load_json(Path(corpus_path));observations=load_json(Path(observations_path));report=evaluate(corpus,observations,window_size);path=Path(output);path.parent.mkdir(parents=True,exist_ok=True);atomic_write_json(path,report);return EvaluationReport(True,"calibration-report.v1",str(path),report["corpus_hash"],report["evaluation_hash"],report["observation_count"],len(report["confusion_matrices"]),len(report["ced"]["windows"]))
