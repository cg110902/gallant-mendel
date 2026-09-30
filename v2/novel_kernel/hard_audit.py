"""M5.3 deterministic hard-invariant audit over candidate artifacts."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .candidate_reconcile import _load,_verify_inputs
from .events import EventLog
from .production import ProductionInputError,ProductionIntegrityError,ProductionStaleError,_publish
from .storage import atomic_write_json,canonical_json_bytes,sha256_json

HARD_RECONCILE={"unregistered_subject","forbidden_change","contradiction"}
@dataclass(frozen=True)
class HardAuditReport:
 ok:bool;schema_version:str;book_id:str;task_id:str;run_id:str;state:str;findings:tuple[dict[str,Any],...];counts:dict[str,int];has_hard_violation:bool;requires_human_review:bool;audit_hash:str;reused:bool

def _finding(rule:str,severity:str,item:dict|None,message:str,evidence_ids:list[str]|None=None)->dict:
 base={"rule_id":rule,"severity":severity,"item_id":item.get("delta_id") if item else None,"claim_id":item.get("claim_id") if item else None,"evidence_ids":list(evidence_ids if evidence_ids is not None else (item.get("evidence_ids",[]) if item else [])),"message":message}
 return {"finding_id":"finding_"+sha256_json(base).removeprefix("sha256:")[:24],**base}
def _values(pack:dict):
 facets=pack["authoritative_context"]["facets"];relations=pack["authoritative_context"]["relations"]
 dead={x["object_id"] for x in facets if x.get("facet_type")=="status" and x.get("payload",{}).get("state") in {"dead","deceased"}}
 capabilities={}
 for x in facets:
  if x.get("facet_type")=="capability":capabilities.setdefault(x["object_id"],set()).update(x.get("payload",{}).get("capabilities",[]))
 possessions={(x["subject_id"],x["object_id"]) for x in relations if x.get("predicate")=="possesses"}
 knowledge={(x.get("holder_id"),x.get("knowledge_id")) for x in pack["authoritative_context"]["character_knowledge"]}
 obligations={x["obligation_id"] for x in pack["authoritative_context"]["open_obligations"]}
 objects={x["object_id"]:x for x in pack["authoritative_context"]["objects"]}
 return dead,capabilities,possessions,knowledge,obligations,objects
class HardInvariantAuditor:
 def audit(self,book_root:Path|str,*,run_id:str)->HardAuditReport:
  book=Path(book_root);run=book/"runs"/run_id
  if not run.is_dir():raise ProductionInputError(f"unknown run: {run_id}")
  req=_load(run/"request.json");status=_load(run/"status.json");pack=_load(run/"context-pack.json");claims=_load(run/"candidate-claims.json");delta=_load(run/"candidate-state-delta.json");evidence=_load(run/"evidence.json");reconcile=_load(run/"candidate-reconcile.json")
  if status.get("state") not in {"reconciled","reconcile_review","reconcile_blocked","audit_pending","audit_passed","audit_review","audit_failed"}:raise ProductionInputError(f"cannot hard-audit from state: {status.get('state')}")
  head=EventLog(book).read_lineage("main")[-1]["event_id"];pointer=_load(book/"compiled"/"current.json")
  if head!=req.get("authority_head") or pointer.get("compile_id")!=req.get("compile_id"):raise ProductionStaleError("run authority or compile pointer is stale")
  _verify_inputs(run,status,pack,claims,delta,evidence)
  reconcile_base={k:v for k,v in reconcile.items() if k!="reconcile_hash"}
  if sha256_json(reconcile_base)!=reconcile.get("reconcile_hash") or reconcile.get("reconcile_hash")!=status.get("reconcile_hash") or reconcile.get("extraction_hash")!=status.get("extraction_hash"):raise ProductionIntegrityError("candidate reconcile hash chain mismatch")
  atomic_write_json(run/"status.json",{**status,"state":"audit_pending"});items={x["delta_id"]:x for x in delta["deltas"]};findings=[]
  for x in reconcile["classifications"]:
   if x["classification"] in HARD_RECONCILE:findings.append(_finding("reconcile."+x["classification"],"hard",items.get(x["item_id"]),x["reason"],x["evidence_ids"]))
   elif x["classification"] in {"emergent_candidate","intent_missing"}:findings.append(_finding("reconcile."+x["classification"],"review",items.get(x["item_id"]),x["reason"],x["evidence_ids"]))
  dead,capabilities,possessions,knowledge,obligations,objects=_values(pack);window=pack["constraints"]["time"];chapter_location=pack["constraints"]["location"]
  for item in delta["deltas"]:
   subject=item["subject_id"];predicate=item["predicate"];value=item["value"]
   if predicate=="acts" and subject in dead:findings.append(_finding("dead_actor","hard",item,"dead character cannot act"))
   elif predicate=="story_time" and (not isinstance(value,str) or value<window["start"] or value>window["end"]):findings.append(_finding("time_window","hard",item,"story_time is outside the frozen chapter window"))
   elif predicate=="location" and (not isinstance(value,str) or value not in objects or objects[value].get("type")!="place" or value!=chapter_location):findings.append(_finding("location_scope","hard",item,"location is unregistered or outside the frozen chapter location"))
   elif predicate=="knows" and (subject,value) not in knowledge:findings.append(_finding("knowledge_boundary","hard",item,"character does not have the frozen knowledge edge"))
   elif predicate=="capability_use" and (not isinstance(value,str) or value not in capabilities.get(subject,set())):findings.append(_finding("capability_prerequisite","hard",item,"capability is absent from the frozen capability facet"))
   elif predicate=="resource_use" and (not isinstance(value,str) or value not in objects or objects[value].get("type")!="item" or (subject,value) not in possessions):findings.append(_finding("resource_source","hard",item,"resource is unregistered or not possessed in frozen authority"))
   elif predicate=="obligation_touch" and value not in obligations:findings.append(_finding("obligation_active","hard",item,"obligation is not open in frozen authority"))
  unique={x["finding_id"]:x for x in findings};findings=sorted(unique.values(),key=lambda x:(x["severity"],x["rule_id"],x["item_id"] or "",x["finding_id"]));counts={"hard":sum(x["severity"]=="hard" for x in findings),"review":sum(x["severity"]=="review" for x in findings)};hard=counts["hard"]>0;review=counts["review"]>0;state="audit_failed" if hard else ("audit_review" if review else "audit_passed")
  base={"schema_version":"hard-audit-report.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"chapter_id":req["chapter_id"],"context_hash":status["context_hash"],"extraction_hash":status["extraction_hash"],"reconcile_hash":status["reconcile_hash"],"state":state,"findings":findings,"counts":counts,"has_hard_violation":hard,"requires_human_review":review};audit_hash=sha256_json(base);doc={**base,"audit_hash":audit_hash};reused=_publish(run/"hard-audit-report.json",doc);atomic_write_json(run/"status.json",{**status,"state":state,"audit_hash":audit_hash})
  return HardAuditReport(not hard and not review,"hard-audit-report.v1",req["book_id"],req["task_id"],run_id,state,tuple(findings),counts,hard,review,audit_hash,reused)
