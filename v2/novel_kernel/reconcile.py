"""M3.4 deterministic Intent/Reality ledger reconciliation."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any,Mapping
from .events import EVENT_ID_RE,EventLog,EventLogError
from .storage import canonical_json_bytes,sha256_json
from .temporal import TemporalQueryInputError,TemporalQueryIntegrityError,TemporalStateQuery
CLASSES=("intent_fulfilled","intent_missing","intent_changed_with_approval","emergent_valid","emergent_unregistered","contradiction","hard_violation")
@dataclass(frozen=True)
class IntentRealityDiffReport:
 ok:bool; schema_version:str; book_id:str; branch_id:str; cutoff:dict[str,Any]; scope_id:str
 intent:dict[str,Any]; reality:dict[str,Any]|None; classifications:tuple[dict[str,Any],...]
 counts:dict[str,int]; has_hard_violation:bool; diff_hash:str
def _copy(v):
 import json
 return json.loads(canonical_json_bytes(v).decode())
def _exact(v,fields,label):
 if not isinstance(v,Mapping) or set(v)!=fields:raise ValueError(f"{label} fields mismatch")
def _text(v,label):
 if not isinstance(v,str) or not v.strip():raise ValueError(f"{label} must be non-empty")
 return v
def _list(v,label):
 if not isinstance(v,list) or any(not isinstance(x,str) or not x for x in v) or len(set(v))!=len(v):raise ValueError(f"{label} must be a unique string array")
 return list(v)
def _refs(v):
 x=_list(v,"source_refs")
 if not x:raise ValueError("source_refs must not be empty")
 return x
def validate_intent(v):
 fields={"scope_id","scope_type","required_actions","required_changes","required_reveals","required_obligations","forbidden_changes","source_refs"};_exact(v,fields,"intent")
 if v["scope_type"] not in {"chapter","beat"}:raise ValueError("unsupported scope_type")
 return {"scope_id":_text(v["scope_id"],"scope_id"),"scope_type":v["scope_type"],"required_actions":_list(v["required_actions"],"required_actions"),"required_changes":_list(v["required_changes"],"required_changes"),"required_reveals":_list(v["required_reveals"],"required_reveals"),"required_obligations":_list(v["required_obligations"],"required_obligations"),"forbidden_changes":_list(v["forbidden_changes"],"forbidden_changes"),"source_refs":_refs(v["source_refs"])}
def validate_reality(v):
 fields={"scope_id","observed_actions","observed_changes","observed_reveals","observed_obligations","observed_entities","contradictions","approved_missing","approved_extras","source_event_id","source_refs"};_exact(v,fields,"reality")
 out={"scope_id":_text(v["scope_id"],"scope_id")}
 for key in ("observed_actions","observed_changes","observed_reveals","observed_obligations","observed_entities","contradictions"):out[key]=_list(v[key],key)
 for key in ("approved_missing","approved_extras"):
  value=v[key]
  if not isinstance(value,dict) or any(not isinstance(k,str) or not k or not isinstance(e,str) or EVENT_ID_RE.fullmatch(e) is None for k,e in value.items()):raise ValueError(f"{key} must map items to audit event IDs")
  out[key]=dict(value)
 source=v["source_event_id"]
 if not isinstance(source,str) or EVENT_ID_RE.fullmatch(source) is None:raise ValueError("source_event_id must be an event ID")
 out["source_event_id"]=source;out["source_refs"]=_refs(v["source_refs"]);return out
class IntentRealityQuery:
 def query(self,book_root:Path|str,*,scope_id:str,as_of:str,branch_id:str="main"):
  if not isinstance(scope_id,str) or not scope_id:raise TemporalQueryInputError("--scope is required")
  temporal=TemporalStateQuery();state=temporal.query(book_root,as_of=as_of,branch_id=branch_id)
  try:lineage=list(EventLog(book_root).read_lineage(branch_id))
  except EventLogError as exc:raise TemporalQueryIntegrityError(str(exc)) from exc
  prefix,_=temporal._cutoff(lineage,as_of);prior={};intents={};realities={}
  for e in prefix:
   kind=e["event_type"];p=e["payload"];eid=e["event_id"]
   try:
    if kind=="intent.registered":
     _exact(p,{"intent","evidence"},"intent payload");record=validate_intent(p["intent"]);sid=record["scope_id"]
     if sid in intents:raise ValueError("duplicate intent scope")
     record["registered_event"]=eid;intents[sid]=record
    elif kind=="reality.observed":
     _exact(p,{"reality","evidence"},"reality payload");record=validate_reality(p["reality"]);sid=record["scope_id"]
     if sid not in intents:raise ValueError("reality scope has no intent")
     if sid in realities:raise ValueError("duplicate reality scope")
     source=record["source_event_id"]
     if prior.get(source)!="chapter.committed":raise ValueError("reality source must be an earlier committed chapter")
     source_payload=prior[source+":payload"]
     if source_payload.get("chapter_id")!=sid:raise ValueError("reality source chapter does not match scope")
     for mapping in (record["approved_missing"],record["approved_extras"]):
      if any(prior.get(a)!="audit.completed" for a in mapping.values()):raise ValueError("approval must reference an earlier audit.completed")
     record["observed_event"]=eid;realities[sid]=record
   except (KeyError,TypeError,ValueError) as exc:raise TemporalQueryIntegrityError(f"cannot fold {eid} ({kind}): {exc}") from exc
   prior[eid]=kind;prior[eid+":payload"]=p
  if scope_id not in intents:raise TemporalQueryInputError(f"unknown intent scope at cutoff: {scope_id}")
  intent=intents[scope_id];reality=realities.get(scope_id);classes=[]
  domains=(("action","required_actions","observed_actions"),("change","required_changes","observed_changes"),("reveal","required_reveals","observed_reveals"),("obligation","required_obligations","observed_obligations"))
  for domain,required_key,observed_key in domains:
   required=set(intent[required_key]);observed=set(reality[observed_key]) if reality is not None and observed_key else set()
   missing_approved=reality["approved_missing"] if reality else {}
   extras_approved=reality["approved_extras"] if reality else {}
   for item in required:
    classification="intent_fulfilled" if item in observed else ("intent_changed_with_approval" if item in missing_approved else "intent_missing")
    classes.append({"domain":domain,"item":item,"classification":classification,"approval_event_id":missing_approved.get(item)})
   for item in observed-required:
    if domain=="change" and item in intent["forbidden_changes"]:classification="hard_violation"
    else:classification="emergent_valid" if item in extras_approved else "emergent_unregistered"
    classes.append({"domain":domain,"item":item,"classification":classification,"approval_event_id":extras_approved.get(item)})
  if reality:
   for item in reality["contradictions"]:classes.append({"domain":"contradiction","item":item,"classification":"contradiction","approval_event_id":None})
   for item in set(reality["observed_changes"])&set(intent["forbidden_changes"]):
    if not any(x["item"]==item and x["classification"]=="hard_violation" for x in classes):classes.append({"domain":"change","item":item,"classification":"hard_violation","approval_event_id":None})
  ordered=tuple(sorted(classes,key=lambda x:(x["domain"],x["item"],x["classification"])))
  counts={name:sum(x["classification"]==name for x in ordered) for name in CLASSES}
  base={"schema_version":"intent-reality-diff.v1","book_id":state.book_id,"branch_id":branch_id,"cutoff":state.cutoff,"scope_id":scope_id,"intent":_copy(intent),"reality":_copy(reality) if reality else None,"classifications":ordered,"counts":counts,"has_hard_violation":counts["hard_violation"]>0}
  return IntentRealityDiffReport(ok=True,**base,diff_hash=sha256_json(base))
