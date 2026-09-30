"""M5.4 deterministic descriptive semantic/style reports and human audit gate."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .candidate_reconcile import _load,_verify_inputs
from .events import EventLog
from .production import ProductionInputError,ProductionIntegrityError,ProductionStaleError,_publish
from .storage import atomic_write_json,sha256_file,sha256_json

HARD_STATES={"audit_passed","audit_review","audit_failed"};SOFT_STATES=HARD_STATES|{"soft_audit_ready","audit_approved","needs_rework"}
@dataclass(frozen=True)
class SoftAuditReport:
 ok:bool;schema_version:str;book_id:str;task_id:str;run_id:str;report_kind:str;state:str;report_path:str;report_hash:str;reused:bool
@dataclass(frozen=True)
class AuditGateReport:
 ok:bool;schema_version:str;book_id:str;task_id:str;run_id:str;state:str;decision:str;decision_id:str;decision_hash:str

def _inputs(book:Path,run_id:str):
 run=book/"runs"/run_id
 if not run.is_dir():raise ProductionInputError(f"unknown run: {run_id}")
 req=_load(run/"request.json");status=_load(run/"status.json");pack=_load(run/"context-pack.json");claims=_load(run/"candidate-claims.json");delta=_load(run/"candidate-state-delta.json");evidence=_load(run/"evidence.json");reconcile=_load(run/"candidate-reconcile.json");hard=_load(run/"hard-audit-report.json")
 if status.get("state") not in SOFT_STATES:raise ProductionInputError(f"cannot soft-audit from state: {status.get('state')}")
 head=EventLog(book).read_lineage("main")[-1]["event_id"];pointer=_load(book/"compiled"/"current.json")
 if head!=req.get("authority_head") or pointer.get("compile_id")!=req.get("compile_id"):raise ProductionStaleError("run authority or compile pointer is stale")
 _verify_inputs(run,status,pack,claims,delta,evidence)
 rb={k:v for k,v in reconcile.items() if k!="reconcile_hash"};hb={k:v for k,v in hard.items() if k!="audit_hash"}
 if sha256_json(rb)!=status.get("reconcile_hash") or sha256_json(hb)!=status.get("audit_hash") or hard.get("audit_hash")!=status.get("audit_hash"):raise ProductionIntegrityError("audit input hash chain mismatch")
 return run,req,status,pack,claims,evidence,reconcile,hard
def _advance(run:Path,status:dict,kind:str,report_hash:str)->str:
 hard_state=status.get("hard_audit_state",status["state"] if status["state"] in HARD_STATES else None)
 updated={**status,"hard_audit_state":hard_state,kind+"_audit_hash":report_hash}
 other="style_audit_hash" if kind=="semantic" else "semantic_audit_hash"
 if updated.get(other):updated["state"]="soft_audit_ready"
 atomic_write_json(run/"status.json",updated);return updated["state"]
class SoftAuditor:
 def semantic(self,book_root:Path|str,*,run_id:str)->SoftAuditReport:
  run,req,status,pack,claims,evidence,reconcile,hard=_inputs(Path(book_root),run_id);required=pack["intent_contract"].get("required_changes",[]);counts=reconcile["counts"];claim_list=claims["claims"];bound=sum(bool(x.get("evidence_ids")) for x in claim_list)
  metrics={"required_change_count":len(required),"intent_fulfilled_count":counts["intent_fulfilled"],"intent_missing_count":counts["intent_missing"],"emergent_candidate_count":counts["emergent_candidate"],"candidate_claim_count":len(claim_list),"evidence_binding_count":len(evidence["bindings"]),"claims_with_evidence_count":bound,"claim_evidence_coverage":None if not claim_list else bound/len(claim_list),"hard_finding_count":hard["counts"]["hard"],"review_finding_count":hard["counts"]["review"]}
  observations=[]
  if metrics["intent_missing_count"]:observations.append("required_changes_missing")
  if metrics["emergent_candidate_count"]:observations.append("emergent_candidates_require_review")
  if metrics["hard_finding_count"]:observations.append("hard_findings_present")
  base={"schema_version":"semantic-audit-report.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"prose_hash":status["review_prose_hash"],"context_hash":status["context_hash"],"extraction_hash":status["extraction_hash"],"reconcile_hash":status["reconcile_hash"],"hard_audit_hash":status["audit_hash"],"descriptive_only":True,"metrics":metrics,"observations":observations};h=sha256_json(base);doc={**base,"semantic_audit_hash":h};path=run/"semantic-audit-report.json";reused=_publish(path,doc);state=_advance(run,status,"semantic",h);return SoftAuditReport(True,"soft-audit-run-report.v1",req["book_id"],req["task_id"],run_id,"semantic",state,str(path),h,reused)
 def style(self,book_root:Path|str,*,run_id:str)->SoftAuditReport:
  run,req,status,pack,claims,evidence,reconcile,hard=_inputs(Path(book_root),run_id);text=(run/"prose.md").read_text();paragraphs=[x for x in re.split(r"\n\s*\n",text) if x.strip()];sentences=[x for x in re.split(r"[。！？!?]+",text) if x.strip()];dialogue_chars=sum(len("".join(x)) for x in re.findall(r"“([^”]*)”|「([^」]*)」",text));nonspace=sum(not x.isspace() for x in text);metrics={"unicode_char_count":len(text),"non_whitespace_char_count":nonspace,"paragraph_count":len(paragraphs),"sentence_count":len(sentences),"cjk_char_count":sum("\u4e00"<=x<="\u9fff" for x in text),"dialogue_char_count":dialogue_chars,"dialogue_ratio":None if not nonspace else dialogue_chars/nonspace,"claim_annotation_count":text.count("<!-- novel:claim")}
  base={"schema_version":"style-audit-report.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"prose_hash":status["review_prose_hash"],"hard_audit_hash":status["audit_hash"],"descriptive_only":True,"thresholds_applied":False,"metrics":metrics};h=sha256_json(base);doc={**base,"style_audit_hash":h};path=run/"style-audit-report.json";reused=_publish(path,doc);state=_advance(run,status,"style",h);return SoftAuditReport(True,"soft-audit-run-report.v1",req["book_id"],req["task_id"],run_id,"style",state,str(path),h,reused)
 def gate(self,book_root:Path|str,*,run_id:str,decision:str,actor:str,note:str="")->AuditGateReport:
  book=Path(book_root);run,req,status,pack,claims,evidence,reconcile,hard=_inputs(book,run_id)
  if status["state"]!="soft_audit_ready":raise ProductionInputError(f"audit gate requires soft_audit_ready, got {status['state']}")
  if decision not in {"approve","rework"}:raise ProductionInputError("decision must be approve or rework")
  if not actor.strip() or len(actor)>128:raise ProductionInputError("actor must be non-empty and at most 128 characters")
  if len(note)>2000:raise ProductionInputError("note exceeds 2000 characters")
  if decision=="approve" and status.get("hard_audit_state")=="audit_failed":raise ProductionStaleError("hard-failed run cannot be approved")
  semantic=_load(run/"semantic-audit-report.json");style=_load(run/"style-audit-report.json")
  semantic_hash=sha256_json({k:v for k,v in semantic.items() if k!="semantic_audit_hash"});style_hash=sha256_json({k:v for k,v in style.items() if k!="style_audit_hash"})
  if semantic_hash!=semantic.get("semantic_audit_hash") or style_hash!=style.get("style_audit_hash") or semantic_hash!=status.get("semantic_audit_hash") or style_hash!=status.get("style_audit_hash"):raise ProductionIntegrityError("soft audit report hash mismatch")
  bindings={"prose_hash":status["review_prose_hash"],"context_hash":status["context_hash"],"extraction_hash":status["extraction_hash"],"reconcile_hash":status["reconcile_hash"],"hard_audit_hash":status["audit_hash"],"semantic_audit_hash":status["semantic_audit_hash"],"style_audit_hash":status["style_audit_hash"]};base={"schema_version":"audit-decision.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"decision":decision,"actor":actor,"note":note,"bindings":bindings};decision_hash=sha256_json(base);decision_id="audit_decision_"+decision_hash.removeprefix("sha256:")[:24];doc={**base,"decision_id":decision_id,"decision_hash":decision_hash};_publish(run/"audit-decision.json",doc);state="audit_approved" if decision=="approve" else "needs_rework";atomic_write_json(run/"status.json",{**status,"state":state,"audit_decision_hash":decision_hash});return AuditGateReport(True,"audit-gate-report.v1",req["book_id"],req["task_id"],run_id,state,decision,decision_id,decision_hash)
