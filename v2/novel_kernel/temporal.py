"""M3.1 read-only bitemporal and narrative as-of state queries."""
from __future__ import annotations
import re
from dataclasses import dataclass,asdict
from pathlib import Path
from typing import Any
from .events import EVENT_ID_RE,EventLog,EventLogError
from .objects import ModelValidationError,STORY_TIME_RE,validate_evidence,validate_facet,validate_fact,validate_object,validate_relation
from .outline import OutlineError
from .storage import canonical_json_bytes,sha256_json

CHAPTER_RE=re.compile(r"^ch_([0-9]+)$")
class TemporalQueryInputError(OutlineError):exit_code=1
class TemporalQueryInvariantError(OutlineError):exit_code=3
class TemporalQueryIntegrityError(OutlineError):exit_code=6
@dataclass(frozen=True)
class TemporalCutoff:
 selector:str
 event_id:str
 lineage_index:int
 story_seq:int
@dataclass(frozen=True)
class TemporalStateReport:
 ok:bool
 schema_version:str
 book_id:str
 branch_id:str
 cutoff:dict[str,Any]
 valid_at:str|None
 objects:tuple[dict[str,Any],...]
 facets:tuple[dict[str,Any],...]
 facts:tuple[dict[str,Any],...]
 relations:tuple[dict[str,Any],...]
 retired_object_count:int
 state_hash:str

def _copy(value:Any)->Any:
 import json
 return json.loads(canonical_json_bytes(value).decode())
def _rank(value:str)->tuple[int,str]|None:
 if value=="unknown":return None
 if value=="story:initial":return (0,"")
 return (1,value.removeprefix("story:"))
def _active(record:dict[str,Any],point:str|None)->bool:
 if point is None:return True
 start=_rank(record["valid_from"]);target=_rank(point);end=_rank(record["valid_to"]) if record["valid_to"] is not None else None
 if start is None or target is None:return False
 return start<=target and (end is None or target<end)

class TemporalStateQuery:
 def query(self,book_root:Path|str,*,as_of:str,valid_at:str|None=None,branch_id:str="main")->TemporalStateReport:
  if not isinstance(as_of,str) or not as_of:raise TemporalQueryInputError("--as-of requires head, an event ID, or ch_<number>")
  if valid_at is not None and STORY_TIME_RE.fullmatch(valid_at) is None:raise TemporalQueryInputError("--valid-at must be story:<ordered-key>")
  log=EventLog(book_root)
  try:lineage=list(log.read_lineage(branch_id))
  except EventLogError as exc:raise TemporalQueryIntegrityError(f"cannot read authority lineage: {exc}") from exc
  if not lineage:raise TemporalQueryInputError(f"authority lineage is empty: {branch_id}")
  prefix,cutoff=self._cutoff(lineage,as_of)
  objects:dict[str,dict[str,Any]]={};facets:dict[tuple[str,str],dict[str,Any]]={};facts:dict[str,dict[str,Any]]={};relations:dict[str,dict[str,Any]]={}
  for event in prefix:
   kind=event["event_type"];payload=event["payload"];event_id=event["event_id"]
   try:
    evidence_payload=payload.get("evidence",[]) if isinstance(payload,dict) else []
    if not isinstance(evidence_payload,list):raise ModelValidationError("event evidence must be an array")
    for evidence in evidence_payload:
     checked_evidence=validate_evidence(evidence)
     if checked_evidence["recorded_event"]!=event_id:raise ModelValidationError("evidence recorded_event does not match carrying event")
    if kind=="object.created":
     record=validate_object(payload["object"])
     if record["created_event"]!=event_id:raise ModelValidationError("object created_event does not match carrying event")
     if record["object_id"] in objects:raise ModelValidationError("duplicate object in temporal lineage")
     objects[record["object_id"]]=record
    elif kind=="object.renamed":
     record=objects.get(payload.get("object_id"))
     if record is None:raise ModelValidationError("rename target is absent")
     candidate=_copy(record);candidate["canonical_name"]=payload["canonical_name"];candidate["aliases"]=_copy(payload["aliases"])
     objects[record["object_id"]]=validate_object(candidate)
    elif kind=="object.retired":
     record=objects.get(payload.get("object_id"))
     if record is None:raise ModelValidationError("retire target is absent")
     candidate=_copy(record);candidate["status"]="retired";objects[record["object_id"]]=validate_object(candidate)
    elif kind=="facet.asserted":
     record=validate_facet(payload["facet"])
     if record["recorded_event"]!=event_id:raise ModelValidationError("facet recorded_event does not match carrying event")
     if record["object_id"] not in objects:raise ModelValidationError("facet target object is absent")
     facets[(record["object_id"],record["facet_type"])]=record
    elif kind=="facet.superseded":
     key=(payload["object_id"],payload["facet_type"])
     if key not in facets:raise ModelValidationError("superseded facet is absent")
     del facets[key]
    elif kind=="fact.asserted":
     record=validate_fact(payload["fact"])
     if record["recorded_event"]!=event_id:raise ModelValidationError("fact recorded_event does not match carrying event")
     if record["subject_id"] not in objects:raise ModelValidationError("fact subject is absent")
     if record["fact_id"] in facts:raise ModelValidationError("duplicate fact in temporal lineage")
     facts[record["fact_id"]]=record
    elif kind=="fact.disputed":
     record=facts.get(payload.get("fact_id"))
     if record is None:raise ModelValidationError("disputed fact is absent")
     record["status"]="disputed"
     for evidence in payload.get("evidence",[]):
      evidence_id=evidence.get("evidence_id")
      if evidence_id and evidence_id not in record["evidence_refs"]:record["evidence_refs"].append(evidence_id)
    elif kind=="relation.asserted":
     record=validate_relation(payload["relation"])
     if record["recorded_event"]!=event_id:raise ModelValidationError("relation recorded_event does not match carrying event")
     if record["subject_id"] not in objects or (record["object_id"] not in objects and record["object_id"] not in facts):raise ModelValidationError("relation endpoint is absent")
     if record["relation_id"] in relations:raise ModelValidationError("duplicate relation in temporal lineage")
     relations[record["relation_id"]]=record
    elif kind=="relation.invalidated":
     record=relations.get(payload.get("relation_id"))
     if record is None:raise ModelValidationError("invalidated relation is absent")
     candidate=_copy(record);candidate["valid_to"]=payload["valid_to"];relations[record["relation_id"]]=validate_relation(candidate)
   except (KeyError,TypeError,ModelValidationError) as exc:raise TemporalQueryIntegrityError(f"cannot fold {event_id} ({kind}): {exc}") from exc
  active_objects=tuple(sorted((_copy(v) for v in objects.values() if v["status"]=="active"),key=lambda x:x["object_id"]))
  active_facets=tuple(sorted((_copy(v) for v in facets.values() if _active(v,valid_at)),key=lambda x:(x["object_id"],x["facet_type"])))
  active_facts=tuple(sorted((_copy(v) for v in facts.values() if _active(v,valid_at)),key=lambda x:x["fact_id"]))
  active_relations=tuple(sorted((_copy(v) for v in relations.values() if _active(v,valid_at)),key=lambda x:x["relation_id"]))
  base={"schema_version":"temporal-state.v1","book_id":prefix[0]["book_id"],"branch_id":branch_id,"cutoff":asdict(cutoff),"valid_at":valid_at,"objects":active_objects,"facets":active_facets,"facts":active_facts,"relations":active_relations,"retired_object_count":sum(v["status"]=="retired" for v in objects.values())}
  return TemporalStateReport(True,base["schema_version"],base["book_id"],branch_id,base["cutoff"],valid_at,active_objects,active_facets,active_facts,active_relations,base["retired_object_count"],sha256_json(base))
 def _cutoff(self,lineage:list[dict[str,Any]],selector:str)->tuple[list[dict[str,Any]],TemporalCutoff]:
  if selector=="head":index=len(lineage)-1
  elif EVENT_ID_RE.fullmatch(selector):
   index=next((i for i,e in enumerate(lineage) if e["event_id"]==selector),-1)
   if index<0:raise TemporalQueryInputError(f"event is not in selected lineage: {selector}")
  else:
   match=CHAPTER_RE.fullmatch(selector)
   if match is None:raise TemporalQueryInputError("--as-of must be head, event_<32hex>, or ch_<positive-number>")
   previous=-1
   for event in lineage:
    if event["story_seq"]<previous:raise TemporalQueryInvariantError("chapter as-of requires nondecreasing story_seq along lineage")
    previous=event["story_seq"]
   chapter=int(match.group(1))
   if chapter<=0:raise TemporalQueryInputError("chapter selector must be positive")
   index=max((i for i,e in enumerate(lineage) if e["story_seq"]<=chapter),default=-1)
   if index<0:raise TemporalQueryInputError(f"no authority state exists as of {selector}")
  event=lineage[index]
  return lineage[:index+1],TemporalCutoff(selector,event["event_id"],index+1,event["story_seq"])
