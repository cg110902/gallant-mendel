"""M6.3 leakage-resistant soft corpus and label-free feature extraction."""
from __future__ import annotations
import json,re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .calibration import CalibrationInputError,CalibrationIntegrityError,load_json
from .storage import atomic_write_json,canonical_json_bytes,sha256_bytes,sha256_json

DETECTORS=("persona_drift","trope_repeat","word_count_cheat")
SPLITS=("train","calibration","holdout")
PERSONA=re.compile(r"<!--\s*novel:persona\s+(\{.*?\})\s*-->",re.DOTALL)
FILLERS=("其实","然后","于是")
@dataclass(frozen=True)
class SoftCorpusReport:
 ok:bool;schema_version:str;output_dir:str;sample_count:int;label_count:int;samples_hash:str;labels_hash:str;split_hash:str
@dataclass(frozen=True)
class SoftFeatureReport:
 ok:bool;schema_version:str;output_path:str;record_count:int;samples_hash:str;split_hash:str;features_hash:str

def _split(index:int)->str:return "train" if index<=12 else "calibration" if index<=22 else "holdout"
def _positive(index:int)->bool:
 local=index if index<=12 else index-12 if index<=22 else index-22
 limit=6 if index<=12 else 5 if index<=22 else 4
 return local<=limit
def _persona(index:int,positive:bool)->tuple[str,dict[str,Any]]:
 baseline=f"persona_baseline_{index:02d}";candidate=f"persona_drift_{index:02d}" if positive else baseline;annotation=canonical_json_bytes({"value":candidate}).decode();return f"角色在第{index}个受控场景中行动。<!-- novel:persona {annotation} -->",{"persona_baseline":baseline}
def _trope(index:int,positive:bool)->tuple[str,dict[str,Any]]:
 if positive:
  phrase=f"第{index}号危机突然出现";prose=(phrase+"。")*(3+index%5)+f"第{index}号场景结束。"
 else:prose="".join(f"第{index}号场景的第{n}步发生不同变化。" for n in range(1,6+index%3))
 return prose,{}
def _word(index:int,positive:bool)->tuple[str,dict[str,Any]]:
 if positive:
  filler=FILLERS[index%len(FILLERS)];prose=(filler+"。")*(20+index)+f"第{index}号有效信息。"
 else:prose="".join(f"第{index}号线索推进到不同阶段{n}。" for n in range(1,11+index%4))
 return prose,{"filler_tokens":list(FILLERS)}
def build_soft_corpus()->tuple[dict[str,Any],dict[str,Any],dict[str,Any]]:
 samples=[];labels=[];entries=[];builders={"persona_drift":_persona,"trope_repeat":_trope,"word_count_cheat":_word}
 for detector in DETECTORS:
  for index in range(1,31):
   positive=_positive(index);prose,context=builders[detector](index,positive);sample_id=f"soft_{detector}_{index:02d}";base={"sample_id":sample_id,"detector_id":detector,"prose":prose,"prose_hash":sha256_bytes(prose.encode()),"context":context};samples.append({**base,"sample_hash":sha256_json(base)});labels.append({"sample_id":sample_id,"expected_detected":positive});entries.append({"sample_id":sample_id,"detector_id":detector,"split":_split(index)})
 samples_base={"schema_version":"soft-corpus.samples.v1","corpus_id":"soft-calibration-v1","samples":samples};samples_doc={**samples_base,"samples_hash":sha256_json(samples_base)};labels_base={"schema_version":"soft-corpus.labels.v1","samples_hash":samples_doc["samples_hash"],"labels":labels};labels_doc={**labels_base,"labels_hash":sha256_json(labels_base)};split_base={"schema_version":"soft-split-manifest.v1","samples_hash":samples_doc["samples_hash"],"strategy":"stratified-fixed-v1","entries":entries};split_doc={**split_base,"split_hash":sha256_json(split_base)};return samples_doc,labels_doc,split_doc
def _check_hash(doc:dict[str,Any],field:str,label:str)->None:
 base={k:v for k,v in doc.items() if k!=field}
 if doc.get(field)!=sha256_json(base):raise CalibrationIntegrityError(f"{label} hash mismatch")
def validate_soft_inputs(samples:dict[str,Any],split:dict[str,Any])->tuple[dict[str,Any],dict[str,Any]]:
 if samples.get("schema_version")!="soft-corpus.samples.v1" or split.get("schema_version")!="soft-split-manifest.v1":raise CalibrationInputError("invalid soft corpus or split schema_version")
 _check_hash(samples,"samples_hash","samples");_check_hash(split,"split_hash","split")
 if split.get("samples_hash")!=samples["samples_hash"]:raise CalibrationIntegrityError("split does not bind samples")
 rows=samples.get("samples");entries=split.get("entries")
 if not isinstance(rows,list) or len(rows)!=90 or not isinstance(entries,list) or len(entries)!=90:raise CalibrationIntegrityError("soft corpus requires exactly 90 samples and split entries")
 ids=set();prose_hashes=set();index={}
 for row in rows:
  base={k:v for k,v in row.items() if k!="sample_hash"};prose=row.get("prose")
  if row.get("sample_hash")!=sha256_json(base) or not isinstance(prose,str) or row.get("prose_hash")!=sha256_bytes(prose.encode()):raise CalibrationIntegrityError("soft sample hash mismatch")
  if row.get("sample_id") in ids or row.get("prose_hash") in prose_hashes or row.get("detector_id") not in DETECTORS:raise CalibrationIntegrityError("duplicate ID/prose or unknown detector")
  context=row.get("context")
  if row["detector_id"]=="persona_drift" and (not isinstance(context,dict) or set(context)!={"persona_baseline"} or not isinstance(context["persona_baseline"],str)):raise CalibrationIntegrityError("invalid persona feature context")
  if row["detector_id"]=="trope_repeat" and context!={}:raise CalibrationIntegrityError("trope feature context must be empty")
  if row["detector_id"]=="word_count_cheat" and (not isinstance(context,dict) or context.get("filler_tokens")!=list(FILLERS) or set(context)!={"filler_tokens"}):raise CalibrationIntegrityError("invalid word-count feature context")
  ids.add(row["sample_id"]);prose_hashes.add(row["prose_hash"]);index[row["sample_id"]]=row
 seen=set();counts={(d,s):0 for d in DETECTORS for s in SPLITS}
 for entry in entries:
  sid=entry.get("sample_id");detector=entry.get("detector_id");part=entry.get("split")
  if sid not in index or sid in seen or detector!=index[sid]["detector_id"] or part not in SPLITS:raise CalibrationIntegrityError("invalid or duplicate split entry")
  seen.add(sid);counts[(detector,part)]+=1
 if seen!=ids:raise CalibrationIntegrityError("split does not cover every sample")
 expected={"train":12,"calibration":10,"holdout":8}
 if any(counts[(d,s)]!=expected[s] for d in DETECTORS for s in SPLITS):raise CalibrationIntegrityError(f"split is not frozen layout: {counts}")
 return samples,split
def validate_soft_labels(samples:dict[str,Any],labels:dict[str,Any],split:dict[str,Any])->dict[str,Any]:
 samples,split=validate_soft_inputs(samples,split)
 if labels.get("schema_version")!="soft-corpus.labels.v1" or labels.get("samples_hash")!=samples["samples_hash"]:raise CalibrationIntegrityError("labels do not bind samples")
 _check_hash(labels,"labels_hash","labels");rows=labels.get("labels")
 if not isinstance(rows,list) or len(rows)!=90:raise CalibrationIntegrityError("soft labels require exactly 90 rows")
 parts={x["sample_id"]:(x["detector_id"],x["split"]) for x in split["entries"]};seen=set();counts={(d,s):[0,0] for d in DETECTORS for s in SPLITS}
 for row in rows:
  sid=row.get("sample_id");expected=row.get("expected_detected")
  if sid not in parts or sid in seen or not isinstance(expected,bool) or set(row)!={"sample_id","expected_detected"}:raise CalibrationIntegrityError("invalid or duplicate soft label")
  seen.add(sid);detector,part=parts[sid];counts[(detector,part)][int(expected)]+=1
 expected_counts={"train":[6,6],"calibration":[5,5],"holdout":[4,4]}
 if any(counts[(d,s)]!=expected_counts[s] for d in DETECTORS for s in SPLITS):raise CalibrationIntegrityError(f"labels are not frozen stratified layout: {counts}")
 return labels
def _sentences(text:str)->list[str]:return [re.sub(r"\s+","",x) for x in re.split(r"[。！？!?]+",re.sub(r"<!--.*?-->","",text,flags=re.DOTALL)) if x.strip()]
def _features(row:dict[str,Any])->dict[str,Any]:
 text=row["prose"];detector=row["detector_id"];sentences=_sentences(text);counts={x:sentences.count(x) for x in set(sentences)};maximum=max(counts.values(),default=0);unique=len(counts);ratio=None if not sentences else unique/len(sentences)
 if detector=="persona_drift":
  matches=PERSONA.findall(text);candidate=None
  if len(matches)==1:
   try:value=json.loads(matches[0]);candidate=value.get("value") if isinstance(value,dict) and set(value)=={"value"} and isinstance(value.get("value"),str) else None
   except json.JSONDecodeError:candidate=None
  baseline=row["context"].get("persona_baseline");return {"annotation_count":len(matches),"baseline_present":isinstance(baseline,str) and bool(baseline),"candidate_present":isinstance(candidate,str) and bool(candidate),"persona_baseline_mismatch":candidate!=baseline if isinstance(candidate,str) and isinstance(baseline,str) else None}
 if detector=="trope_repeat":return {"sentence_count":len(sentences),"unique_sentence_count":unique,"unique_sentence_ratio":ratio,"max_normalized_sentence_frequency":maximum,"repeated_sentence_excess":sum(max(0,x-1) for x in counts.values())}
 nonspace=sum(not x.isspace() for x in text);tokens=row["context"].get("filler_tokens",list(FILLERS));filler_chars=sum(text.count(token)*len(token) for token in tokens);return {"non_whitespace_char_count":nonspace,"sentence_count":len(sentences),"unique_sentence_ratio":ratio,"max_normalized_sentence_frequency":maximum,"filler_character_ratio":None if not nonspace else filler_chars/nonspace}
def extract_features(samples:dict[str,Any],split:dict[str,Any])->dict[str,Any]:
 samples,split=validate_soft_inputs(samples,split);parts={x["sample_id"]:x["split"] for x in split["entries"]};records=[]
 for row in samples["samples"]:
  feature=_features(row);base={"sample_id":row["sample_id"],"sample_hash":row["sample_hash"],"detector_id":row["detector_id"],"split":parts[row["sample_id"]],"extractor_id":"soft_feature_extractor","extractor_version":"v1","features":feature};records.append({**base,"feature_hash":sha256_json(base)})
 records.sort(key=lambda x:x["sample_id"]);base={"schema_version":"soft-features.v1","samples_hash":samples["samples_hash"],"split_hash":split["split_hash"],"label_free":True,"records":records};return {**base,"features_hash":sha256_json(base)}
class SoftCalibrationService:
 def write_corpus(self,output_dir:Path|str)->SoftCorpusReport:
  samples,labels,split=build_soft_corpus();validate_soft_labels(samples,labels,split);out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);atomic_write_json(out/"soft-corpus.samples.v1.json",samples);atomic_write_json(out/"soft-corpus.labels.v1.json",labels);atomic_write_json(out/"soft-split-manifest.v1.json",split);return SoftCorpusReport(True,"soft-calibration-corpus.v1",str(out),90,90,samples["samples_hash"],labels["labels_hash"],split["split_hash"])
 def write_features(self,corpus_path:Path|str,split_path:Path|str,output:Path|str)->SoftFeatureReport:
  samples=load_json(Path(corpus_path));split=load_json(Path(split_path));features=extract_features(samples,split);path=Path(output);path.parent.mkdir(parents=True,exist_ok=True);atomic_write_json(path,features);return SoftFeatureReport(True,"soft-features.v1",str(path),len(features["records"]),features["samples_hash"],features["split_hash"],features["features_hash"])
