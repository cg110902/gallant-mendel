"""M5.1 conservative candidate claim extraction with exact prose evidence."""
from __future__ import annotations
import json,re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .production import ProductionInputError,ProductionIntegrityError,ProductionStaleError,_publish
from .storage import atomic_write_json,sha256_bytes,sha256_file,sha256_json

PREDICATE=re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ANNOTATION=re.compile(r"<!--\s*novel:claim\s+(\{.*?\})\s*-->",re.DOTALL)
@dataclass(frozen=True)
class ExtractionReport:
 ok:bool;schema_version:str;book_id:str;task_id:str;run_id:str;state:str;entity_mention_count:int;claim_count:int;delta_count:int;evidence_count:int;semantic_completeness:bool;extraction_hash:str;reused:bool

def _load(path:Path)->dict:
 try:return json.loads(path.read_text(),object_pairs_hook=_pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(f"invalid constant {x}")))
 except Exception as exc:raise ProductionIntegrityError(f"invalid artifact {path}: {exc}") from exc
def _pairs(items):
 result={}
 for key,value in items:
  if key in result:raise ValueError(f"duplicate key: {key}")
  result[key]=value
 return result
def _validate_value(value:Any,depth:int=0)->None:
 if depth>6:raise ProductionInputError("claim value exceeds nesting limit")
 if value is None or isinstance(value,(str,bool,int)):return
 if isinstance(value,float):
  if value!=value or value in (float("inf"),float("-inf")):raise ProductionInputError("claim value must be finite")
  return
 if isinstance(value,list):
  if len(value)>64:raise ProductionInputError("claim value list is too large")
  for item in value:_validate_value(item,depth+1)
  return
 if isinstance(value,dict):
  if len(value)>64 or any(not isinstance(k,str) or len(k)>128 for k in value):raise ProductionInputError("claim value object is too large")
  for item in value.values():_validate_value(item,depth+1)
  return
 raise ProductionInputError("claim value is not JSON-compatible")
def _token(prefix:str,value:dict)->str:return prefix+sha256_json(value).removeprefix("sha256:")[:24]
def _evidence(run_id:str,prose_hash:str,text:str,start:int,end:int,kind:str,target_id:str)->dict:
 quote=text[start:end];base={"run_id":run_id,"prose_hash":prose_hash,"start_char":start,"end_char":end,"quote_hash":sha256_bytes(quote.encode()),"kind":kind,"target_id":target_id}
 return {"evidence_id":_token("evidence_",base),"source_path":"prose.md","quote":quote,**base}
class CandidateExtractor:
 def extract(self,book_root:Path|str,*,run_id:str)->ExtractionReport:
  book=Path(book_root);run=book/"runs"/run_id
  if not run.is_dir():raise ProductionInputError(f"unknown run: {run_id}")
  request=_load(run/"request.json");pack=_load(run/"context-pack.json");status=_load(run/"status.json")
  if status.get("state") not in {"extraction_ready","extracting","extracted"}:raise ProductionInputError(f"cannot extract from state: {status.get('state')}")
  if status.get("review_decision")!="approve":raise ProductionInputError("human approval is required before extraction")
  prose_path=run/"prose.md"
  if not prose_path.is_file():raise ProductionIntegrityError("approved run has no prose.md")
  prose=prose_path.read_text();prose_hash=sha256_file(prose_path)
  if prose_hash!=status.get("review_prose_hash"):raise ProductionStaleError("approved prose hash changed")
  if sha256_json(pack)!=status.get("context_hash"):raise ProductionStaleError("context hash changed")
  running={**status,"state":"extracting"};atomic_write_json(run/"status.json",running)
  objects=pack["authoritative_context"]["objects"];known={x["object_id"] for x in objects};mentions=[];evidence=[]
  terms=[]
  for obj in objects:
   for term in [obj["object_id"],obj["canonical_name"],*obj.get("aliases",[])]:
    if term and len(term)>=2:terms.append((term,obj["object_id"]))
  for term,object_id in sorted(set(terms),key=lambda x:(-len(x[0]),x[0],x[1])):
   for match in re.finditer(re.escape(term),prose):
    target={"object_id":object_id,"surface":term,"start_char":match.start(),"end_char":match.end()};mention_id=_token("mention_",{"run_id":run_id,"prose_hash":prose_hash,**target});ev=_evidence(run_id,prose_hash,prose,match.start(),match.end(),"entity_mention",mention_id);mentions.append({"mention_id":mention_id,"evidence_id":ev["evidence_id"],**target});evidence.append(ev)
  claims=[];deltas=[]
  for match in ANNOTATION.finditer(prose):
   try:value=json.loads(match.group(1),object_pairs_hook=_pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
   except Exception as exc:raise ProductionInputError(f"invalid claim annotation at char {match.start()}: {exc}") from exc
   if not isinstance(value,dict) or set(value)!={"subject_id","predicate","value"}:raise ProductionInputError("claim annotation requires only subject_id, predicate, value")
   if value["subject_id"] not in known:raise ProductionInputError(f"claim subject is not registered: {value['subject_id']}")
   if not isinstance(value["predicate"],str) or not PREDICATE.fullmatch(value["predicate"]):raise ProductionInputError("claim predicate is invalid")
   _validate_value(value["value"]);base={"run_id":run_id,"prose_hash":prose_hash,**value,"start_char":match.start(),"end_char":match.end()};claim_id=_token("claim_",base);ev=_evidence(run_id,prose_hash,prose,match.start(),match.end(),"candidate_claim",claim_id);claim={"claim_id":claim_id,"claim_kind":"fact","confidence":"candidate","evidence_ids":[ev["evidence_id"]],**value};delta_base={"claim_id":claim_id,"operation":"assert_fact","subject_id":value["subject_id"],"predicate":value["predicate"],"value":value["value"],"evidence_ids":[ev["evidence_id"]]};delta={"delta_id":_token("delta_",delta_base),**delta_base};claims.append(claim);deltas.append(delta);evidence.append(ev)
  mentions.sort(key=lambda x:(x["start_char"],x["end_char"],x["object_id"],x["mention_id"]));claims.sort(key=lambda x:x["claim_id"]);deltas.sort(key=lambda x:x["delta_id"]);evidence.sort(key=lambda x:x["evidence_id"])
  if any(prose[x["start_char"]:x["end_char"]]!=x["quote"] or sha256_bytes(x["quote"].encode())!=x["quote_hash"] for x in evidence):raise ProductionIntegrityError("evidence reverse binding failed")
  claims_doc={"schema_version":"candidate-claims.v1","book_id":request["book_id"],"run_id":run_id,"chapter_id":request["chapter_id"],"context_hash":status["context_hash"],"prose_hash":prose_hash,"semantic_completeness":False,"entity_mentions":mentions,"claims":claims}
  delta_doc={"schema_version":"candidate-state-delta.v1","book_id":request["book_id"],"run_id":run_id,"chapter_id":request["chapter_id"],"context_hash":status["context_hash"],"prose_hash":prose_hash,"deltas":deltas,"authoritative":False}
  evidence_doc={"schema_version":"extraction-evidence.v1","book_id":request["book_id"],"run_id":run_id,"prose_hash":prose_hash,"bindings":evidence}
  extraction_hash=sha256_json({"claims":claims_doc,"delta":delta_doc,"evidence":evidence_doc});report_doc={"schema_version":"extraction-report.v1","book_id":request["book_id"],"task_id":request["task_id"],"run_id":run_id,"state":"extracted","entity_mention_count":len(mentions),"claim_count":len(claims),"delta_count":len(deltas),"evidence_count":len(evidence),"semantic_completeness":False,"extraction_hash":extraction_hash}
  publications=[_publish(run/name,doc) for name,doc in (("candidate-claims.json",claims_doc),("candidate-state-delta.json",delta_doc),("evidence.json",evidence_doc),("extraction-report.json",report_doc))];reused=all(publications)
  done={**running,"state":"extracted","extraction_hash":extraction_hash};atomic_write_json(run/"status.json",done)
  return ExtractionReport(True,"extraction-report.v1",request["book_id"],request["task_id"],run_id,"extracted",len(mentions),len(claims),len(deltas),len(evidence),False,extraction_hash,reused)
