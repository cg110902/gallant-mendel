"""M5.2 deterministic reconciliation of evidence-bound candidate fact deltas."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .events import EventLog
from .production import ProductionInputError,ProductionIntegrityError,ProductionStaleError,_publish
from .storage import atomic_write_json,canonical_json_bytes,sha256_bytes,sha256_file,sha256_json

HARD={"unregistered_subject","forbidden_change","contradiction"}
@dataclass(frozen=True)
class CandidateReconcileReport:
 ok:bool;schema_version:str;book_id:str;task_id:str;run_id:str;state:str;classifications:tuple[dict[str,Any],...];counts:dict[str,int];has_hard_violation:bool;requires_human_review:bool;reconcile_hash:str;reused:bool

def _load(path:Path)->dict:
 def pairs(items):
  out={}
  for key,value in items:
   if key in out:raise ValueError(f"duplicate key: {key}")
   out[key]=value
  return out
 try:
  raw=path.read_bytes();value=json.loads(raw.decode(),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(f"invalid constant: {x}")))
  if canonical_json_bytes(value)!=raw:raise ValueError("artifact is not canonical JSON")
  return value
 except Exception as exc:raise ProductionIntegrityError(f"invalid artifact {path}: {exc}") from exc
def _signature(subject:str,predicate:str,value:Any)->str:
 rendered=value if isinstance(value,str) else canonical_json_bytes(value).decode()
 return f"{subject}.{predicate}={rendered}"
def _verify_inputs(run:Path,status:dict,pack:dict,claims:dict,delta:dict,evidence:dict)->None:
 prose=run/"prose.md";prose_hash=sha256_file(prose)
 if prose_hash!=status.get("review_prose_hash") or prose_hash!=claims.get("prose_hash") or prose_hash!=delta.get("prose_hash") or prose_hash!=evidence.get("prose_hash"):raise ProductionStaleError("candidate artifacts do not bind approved prose")
 if status.get("context_hash")!=sha256_json(pack) or claims.get("context_hash")!=status.get("context_hash") or delta.get("context_hash")!=status.get("context_hash"):raise ProductionStaleError("candidate artifacts do not bind frozen context")
 expected=sha256_json({"claims":claims,"delta":delta,"evidence":evidence})
 if expected!=status.get("extraction_hash"):raise ProductionIntegrityError("extraction hash mismatch")
 text=prose.read_text();bindings={x.get("evidence_id"):x for x in evidence.get("bindings",[])}
 if len(bindings)!=len(evidence.get("bindings",[])):raise ProductionIntegrityError("duplicate evidence ID")
 for eid,item in bindings.items():
  try:quote=text[item["start_char"]:item["end_char"]]
  except Exception as exc:raise ProductionIntegrityError("invalid evidence span") from exc
  if item.get("prose_hash")!=prose_hash or quote!=item.get("quote") or sha256_bytes(quote.encode())!=item.get("quote_hash"):raise ProductionIntegrityError(f"broken evidence binding: {eid}")
 claim_by_id={x.get("claim_id"):x for x in claims.get("claims",[])}
 if len(claim_by_id)!=len(claims.get("claims",[])):raise ProductionIntegrityError("duplicate claim ID")
 for claim in claim_by_id.values():
  if any(eid not in bindings or bindings[eid].get("target_id")!=claim["claim_id"] for eid in claim.get("evidence_ids",[])):raise ProductionIntegrityError(f"claim evidence mismatch: {claim.get('claim_id')}")
 seen=set()
 for item in delta.get("deltas",[]):
  if item.get("delta_id") in seen:raise ProductionIntegrityError("duplicate delta ID")
  seen.add(item.get("delta_id"));claim=claim_by_id.get(item.get("claim_id"))
  if claim is None or any(item.get(k)!=claim.get(k) for k in ("subject_id","predicate","value","evidence_ids")):raise ProductionIntegrityError(f"delta claim mismatch: {item.get('delta_id')}")
class CandidateReconciler:
 def reconcile(self,book_root:Path|str,*,run_id:str)->CandidateReconcileReport:
  book=Path(book_root);run=book/"runs"/run_id
  if not run.is_dir():raise ProductionInputError(f"unknown run: {run_id}")
  req=_load(run/"request.json");status=_load(run/"status.json");pack=_load(run/"context-pack.json");claims=_load(run/"candidate-claims.json");delta=_load(run/"candidate-state-delta.json");evidence=_load(run/"evidence.json")
  if status.get("state") not in {"extracted","reconcile_pending","reconciled","reconcile_review","reconcile_blocked"}:raise ProductionInputError(f"cannot reconcile from state: {status.get('state')}")
  head=EventLog(book).read_lineage("main")[-1]["event_id"];pointer=_load(book/"compiled"/"current.json")
  if head!=req.get("authority_head") or pointer.get("compile_id")!=req.get("compile_id"):raise ProductionStaleError("run authority or compile pointer is stale")
  _verify_inputs(run,status,pack,claims,delta,evidence);atomic_write_json(run/"status.json",{**status,"state":"reconcile_pending"})
  objects={x["object_id"] for x in pack["authoritative_context"]["objects"]};baseline={}
  for fact in pack["authoritative_context"]["facts"]:
   if fact.get("status") not in {None,"asserted"}:continue
   key=(fact["subject_id"],fact["predicate"]);encoded=canonical_json_bytes(fact["value"])
   if key in baseline and baseline[key]!=encoded:raise ProductionIntegrityError(f"frozen authority has conflicting active facts: {key}")
   baseline[key]=encoded
  intent=pack["intent_contract"];required=set(intent.get("required_changes",[]));forbidden=set(intent.get("forbidden_changes",[]));matched=set();classes=[]
  for item in delta.get("deltas",[]):
   subject=item["subject_id"];predicate=item["predicate"];value=item["value"];signature=_signature(subject,predicate,value);lhs=f"{subject}.{predicate}";key=(subject,predicate);encoded=canonical_json_bytes(value)
   if subject not in objects:classification="unregistered_subject";reason="subject is absent from frozen object registry"
   elif lhs in forbidden or signature in forbidden:classification="forbidden_change";reason="change is forbidden by intent contract"
   elif key in baseline and baseline[key]!=encoded:classification="contradiction";reason="candidate differs from frozen active fact"
   elif key in baseline:classification="no_change";reason="candidate equals frozen active fact"
   elif signature in required:classification="intent_fulfilled";reason="candidate matches required change";matched.add(signature)
   else:classification="emergent_candidate";reason="candidate is registered but not required or forbidden"
   if signature in required and classification not in HARD:matched.add(signature)
   classes.append({"domain":"candidate_delta","item_id":item["delta_id"],"claim_id":item["claim_id"],"signature":signature,"classification":classification,"reason":reason,"evidence_ids":item["evidence_ids"]})
  for signature in sorted(required-matched):classes.append({"domain":"intent","item_id":None,"claim_id":None,"signature":signature,"classification":"intent_missing","reason":"required change has no matching candidate delta","evidence_ids":[]})
  classes.sort(key=lambda x:(x["domain"],x["signature"],x["item_id"] or ""));names=("unregistered_subject","forbidden_change","contradiction","no_change","intent_fulfilled","emergent_candidate","intent_missing");counts={n:sum(x["classification"]==n for x in classes) for n in names};hard=any(counts[n] for n in HARD);review=counts["emergent_candidate"]>0 or counts["intent_missing"]>0;state="reconcile_blocked" if hard else ("reconcile_review" if review else "reconciled")
  base={"schema_version":"candidate-reconcile.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"chapter_id":req["chapter_id"],"context_hash":status["context_hash"],"extraction_hash":status["extraction_hash"],"state":state,"classifications":classes,"counts":counts,"has_hard_violation":hard,"requires_human_review":review};reconcile_hash=sha256_json(base);doc={**base,"reconcile_hash":reconcile_hash};reused=_publish(run/"candidate-reconcile.json",doc);atomic_write_json(run/"status.json",{**status,"state":state,"reconcile_hash":reconcile_hash})
  return CandidateReconcileReport(not hard and not review,"candidate-reconcile.v1",req["book_id"],req["task_id"],run_id,state,tuple(classes),counts,hard,review,reconcile_hash,reused)
