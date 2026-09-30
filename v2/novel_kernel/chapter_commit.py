"""M5.5 recoverable, journaled chapter authority commit."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .candidate_reconcile import _load,_verify_inputs
from .events import ACTOR_RE,FORBIDDEN_ACTORS,EventLog,EventLogError,ParentConflictError,ResourceGuardError,build_event,utc_now
from .production import ProductionInputError,ProductionIntegrityError,ProductionResourceGuardError,ProductionStaleError,_publish
from .projection import ProjectionStore
from .storage import atomic_write_bytes,atomic_write_json,canonical_json_bytes,sha256_bytes,sha256_file,sha256_json

@dataclass(frozen=True)
class ChapterCommitReport:
 ok:bool;schema_version:str;book_id:str;task_id:str;run_id:str;chapter_id:str;state:str;event_ids:tuple[str,...];commit_head:str;chapter_path:str;chapter_hash:str;projection_state_hash:str;commit_hash:str;reused:bool

def _event_id(run_id:str,kind:str,index:int,decision_hash:str)->str:
 return "event_"+sha256_json({"run_id":run_id,"kind":kind,"index":index,"decision_hash":decision_hash}).removeprefix("sha256:")[:32]
def _fact_id(run_id:str,delta_id:str)->str:return "fact_commit_"+sha256_json({"run_id":run_id,"delta_id":delta_id}).removeprefix("sha256:")[:24]
def _validate_gate(run:Path,status:dict)->dict:
 decision=_load(run/"audit-decision.json");base={k:v for k,v in decision.items() if k not in {"decision_id","decision_hash"}}
 if decision.get("decision")!="approve" or sha256_json(base)!=decision.get("decision_hash") or decision.get("decision_hash")!=status.get("audit_decision_hash"):raise ProductionIntegrityError("audit approval hash chain mismatch")
 expected="audit_decision_"+decision["decision_hash"].removeprefix("sha256:")[:24]
 if decision.get("decision_id")!=expected:raise ProductionIntegrityError("audit decision ID mismatch")
 for key,value in decision["bindings"].items():
  status_key={"prose_hash":"review_prose_hash","hard_audit_hash":"audit_hash"}.get(key,key)
  if status.get(status_key)!=value:raise ProductionIntegrityError(f"audit decision binding mismatch: {key}")
 return decision
def _build_events(req,status,pack,claims,delta,evidence,reconcile,decision,actor,recorded_at):
 run_id=req["run_id"];book_id=req["book_id"];chapter=req["chapter_id"];story_seq=int(chapter.split("_",1)[1]);decision_hash=decision["decision_hash"];parent=req["authority_head"];events=[];index=0
 def add(kind,payload,evidence_refs=()):
  nonlocal parent,index
  eid=_event_id(run_id,kind,index,decision_hash);event=build_event(event_id=eid,event_type=kind,book_id=book_id,branch_id="main",parent_event_id=parent,story_seq=story_seq,recorded_at=recorded_at,actor_type="human",actor_id=actor,source_run_id=run_id,payload=payload,evidence_refs=evidence_refs);events.append(event);parent=eid;index+=1;return eid
 audit_id=add("audit.completed",{"decision":"approve","decision_id":decision["decision_id"],"decision_hash":decision_hash,"hard_audit_hash":status["audit_hash"],"semantic_audit_hash":status["semantic_audit_hash"],"style_audit_hash":status["style_audit_hash"]})
 binding={x["evidence_id"]:x for x in evidence["bindings"]};classes={x["item_id"]:x["classification"] for x in reconcile["classifications"] if x["item_id"]};committed=[]
 for item in sorted(delta["deltas"],key=lambda x:x["delta_id"]):
  if classes.get(item["delta_id"])=="no_change":continue
  eid=_event_id(run_id,"fact.asserted",index,decision_hash);records=[]
  for ref in item["evidence_ids"]:
   source=binding[ref];records.append({"evidence_id":ref,"source_type":"chapter","source_ref":f"chapters/{chapter}.md","locator":{"start":source["start_char"],"end":source["end_char"]},"content_hash":source["quote_hash"],"excerpt":source["quote"],"recorded_event":eid})
  fact={"fact_id":_fact_id(run_id,item["delta_id"]),"subject_id":item["subject_id"],"predicate":item["predicate"],"value":item["value"],"valid_from":pack["constraints"]["time"]["end"],"valid_to":None,"recorded_event":eid,"confidence":"confirmed","status":"asserted","evidence_refs":item["evidence_ids"]}
  add("fact.asserted",{"fact":fact,"evidence":records},item["evidence_ids"]);committed.append((item,classes.get(item["delta_id"])))
 chapter_id=add("chapter.committed",{"chapter_id":chapter,"prose_hash":status["review_prose_hash"],"audit_decision_hash":decision_hash})
 intent=pack["intent_contract"];observed_changes=[f'{x[0]["subject_id"]}.{x[0]["predicate"]}={x[0]["value"] if isinstance(x[0]["value"],str) else canonical_json_bytes(x[0]["value"]).decode()}' for x in committed];required=set(intent.get("required_actions",[])+intent.get("required_changes",[])+intent.get("required_reveals",[])+intent.get("required_obligations",[]));observed=set(observed_changes);approved_missing={x:audit_id for x in sorted(required-observed)};approved_extras={f'{x[0]["subject_id"]}.{x[0]["predicate"]}={x[0]["value"] if isinstance(x[0]["value"],str) else canonical_json_bytes(x[0]["value"]).decode()}':audit_id for x in committed if x[1]=="emergent_candidate"}
 reality={"scope_id":chapter,"observed_actions":[],"observed_changes":observed_changes,"observed_reveals":[],"observed_obligations":[],"observed_entities":sorted({x["object_id"] for x in claims["entity_mentions"]}),"contradictions":[],"approved_missing":approved_missing,"approved_extras":approved_extras,"source_event_id":chapter_id,"source_refs":[f"run:{run_id}/candidate-reconcile.json"]};reality_id=add("reality.observed",{"reality":reality,"evidence":[]})
 add("state.reconciled",{"chapter_id":chapter,"reality_event_id":reality_id,"candidate_reconcile_hash":status["reconcile_hash"],"audit_decision_hash":decision_hash})
 return events
class ChapterCommitter:
 def commit(self,book_root:Path|str,*,run_id:str,actor:str)->ChapterCommitReport:
  book=Path(book_root);run=book/"runs"/run_id
  if ACTOR_RE.fullmatch(actor or "") is None or actor in FORBIDDEN_ACTORS:raise ProductionInputError("--actor must be an authorized core actor ID")
  if not run.is_dir():raise ProductionInputError(f"unknown run: {run_id}")
  req=_load(run/"request.json");status=_load(run/"status.json");pack=_load(run/"context-pack.json");claims=_load(run/"candidate-claims.json");delta=_load(run/"candidate-state-delta.json");evidence=_load(run/"evidence.json");reconcile=_load(run/"candidate-reconcile.json")
  if status.get("state") not in {"audit_approved","commit_prepared","authority_committed","published"}:raise ProductionInputError(f"cannot commit from state: {status.get('state')}")
  _verify_inputs(run,status,pack,claims,delta,evidence);decision=_validate_gate(run,status);prose_path=run/"prose.md";prose=prose_path.read_bytes()
  if sha256_bytes(prose)!=status.get("review_prose_hash"):raise ProductionStaleError("approved prose changed before commit")
  intent_path=run/"commit-intent.json"
  if intent_path.exists():intent=_load(intent_path);events=intent["events"]
  else:
   lineage=EventLog(book).read_lineage("main")
   if lineage[-1]["event_id"]!=req["authority_head"]:raise ProductionStaleError("authority head changed before commit")
   pointer=_load(book/"compiled"/"current.json")
   if pointer["compile_id"]!=req["compile_id"]:raise ProductionStaleError("compile pointer changed before commit")
   recorded_at=utc_now();events=_build_events(req,status,pack,claims,delta,evidence,reconcile,decision,actor,recorded_at);base={"schema_version":"commit-intent.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"chapter_id":req["chapter_id"],"actor":actor,"recorded_at":recorded_at,"authority_parent":req["authority_head"],"prose_hash":status["review_prose_hash"],"audit_decision_hash":decision["decision_hash"],"events":events};intent={**base,"intent_hash":sha256_json(base)};_publish(intent_path,intent)
  intent_base={k:v for k,v in intent.items() if k!="intent_hash"}
  if intent.get("intent_hash")!=sha256_json(intent_base):raise ProductionIntegrityError("commit intent hash mismatch")
  if intent.get("actor")!=actor or intent.get("prose_hash")!=status["review_prose_hash"] or intent.get("audit_decision_hash")!=decision["decision_hash"]:raise ProductionIntegrityError("commit intent binding mismatch")
  atomic_write_json(run/"status.json",{**status,"state":"commit_prepared"});log=EventLog(book);existing={x["event_id"]:x for x in log.read_events()};present=[]
  for event in events:
   if event["event_id"] not in existing:break
   if canonical_json_bytes(existing[event["event_id"]])!=canonical_json_bytes(event):raise ProductionIntegrityError(f"committed event differs: {event['event_id']}")
   present.append(event["event_id"])
  if any(x["event_id"] in existing for x in events[len(present):]):raise ProductionIntegrityError("commit events are not a contiguous prefix")
  if len(present)<len(events):
   current=log.read_lineage("main")[-1]["event_id"]
   expected_parent=events[len(present)]["parent_event_id"]
   if current!=expected_parent:raise ProductionStaleError("authority advanced outside prepared commit")
   try:log.append_many(events[len(present):])
   except (ResourceGuardError,ParentConflictError) as exc:raise ProductionResourceGuardError(f"authority concurrency guard: {exc}") from exc
   except EventLogError as exc:raise ProductionIntegrityError(f"authority append failed: {exc}") from exc
  status={**status,"state":"authority_committed","commit_head":events[-1]["event_id"]};atomic_write_json(run/"status.json",status);chapter_path=book/"chapters"/f"{req['chapter_id']}.md";chapter_path.parent.mkdir(parents=True,exist_ok=True)
  if chapter_path.exists() and chapter_path.read_bytes()!=prose:raise ProductionIntegrityError("published chapter differs from approved prose")
  if not chapter_path.exists():atomic_write_bytes(chapter_path,prose)
  projection=ProjectionStore(book).update(log);chapter_hash=sha256_file(chapter_path);base={"schema_version":"chapter-commit-report.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"chapter_id":req["chapter_id"],"state":"published","event_ids":[x["event_id"] for x in events],"commit_head":events[-1]["event_id"],"chapter_path":f"chapters/{req['chapter_id']}.md","chapter_hash":chapter_hash,"projection_state_hash":projection.state_hash};commit_hash=sha256_json(base);doc={**base,"commit_hash":commit_hash};reused=_publish(run/"chapter-commit-report.json",doc);atomic_write_json(run/"status.json",{**status,"state":"published","chapter_hash":chapter_hash,"commit_hash":commit_hash})
  return ChapterCommitReport(True,"chapter-commit-report.v1",req["book_id"],req["task_id"],run_id,req["chapter_id"],"published",tuple(base["event_ids"]),events[-1]["event_id"],str(chapter_path),chapter_hash,projection.state_hash,commit_hash,reused)
