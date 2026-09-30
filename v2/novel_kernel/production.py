"""M4.1 deterministic production planning and ContextPack publication."""
from __future__ import annotations
import json
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Any
from .events import EventLog
from .knowledge import KnowledgeBoundaryQuery
from .obligations import ObligationStateQuery
from .outline import OutlineError
from .outline_readiness import OutlineReadinessChecker
from .reconcile import IntentRealityQuery
from .storage import atomic_write_json,canonical_json_bytes,sha256_json
from .temporal import TemporalStateQuery
class ProductionInputError(OutlineError):exit_code=1
class ProductionStaleError(OutlineError):exit_code=3
class ProductionIntegrityError(OutlineError):exit_code=6
class ProductionResourceGuardError(OutlineError):exit_code=7
@dataclass(frozen=True)
class ProductionPlanReport:
 ok:bool;schema_version:str;book_id:str;chapter_id:str;task_id:str;run_id:str;state:str;reused:bool;task_path:str;run_path:str;plan_hash:str
@dataclass(frozen=True)
class ContextBuildReport:
 ok:bool;schema_version:str;book_id:str;chapter_id:str;task_id:str;run_id:str;state:str;reused:bool;context_path:str;context_hash:str
def _publish(path:Path,value:dict)->bool:
 data=canonical_json_bytes(value)
 if path.exists():
  if path.read_bytes()!=data:raise ProductionIntegrityError(f"existing deterministic artifact differs: {path}")
  return True
 path.parent.mkdir(parents=True,exist_ok=True);atomic_write_json(path,value);return False
class ProductionPlanner:
 def plan(self,book_root:Path|str,*,chapter_id:str)->ProductionPlanReport:
  book=Path(book_root);ready=OutlineReadinessChecker().check(book/"outline",expected_book_id=book.name)
  if chapter_id!=ready.chapter_id:raise ProductionInputError(f"M4.1 supports next ready chapter only: {ready.chapter_id}")
  try:number=int(chapter_id.split("_",1)[1])
  except Exception as exc:raise ProductionInputError("chapter must be ch_<number>") from exc
  events=EventLog(book).read_lineage("main");head=events[-1]
  if head["story_seq"]>=number:raise ProductionStaleError("target chapter is not after authority head story_seq")
  seed={"book_id":ready.book_id,"chapter_id":chapter_id,"compile_id":ready.compile_id,"authority_head":ready.authority_head,"projection_state_hash":ready.projection_state_hash}
  token=sha256_json(seed).removeprefix("sha256:")[:24];task_id="task_"+token;run_id="run_"+token
  dag=[{"node_id":"draft","depends_on":[],"gate":"context_ready","enabled":True},{"node_id":"extract","depends_on":["draft"],"gate":"future_m4_2","enabled":False},{"node_id":"audit","depends_on":["extract"],"gate":"future_m5","enabled":False},{"node_id":"commit","depends_on":["audit"],"gate":"future_m5","enabled":False}]
  task={"schema_version":"production-task.v1",**seed,"task_id":task_id,"run_id":run_id,"task_kind":"draft_chapter","dag":dag,"forbidden_actions":["append_events","modify_state_db","write_chapters","invoke_model"]}
  request={"schema_version":"production-request.v1",**seed,"task_id":task_id,"run_id":run_id,"task_path":f"production/tasks/{task_id}.json"}
  status={"schema_version":"run-status.v1","book_id":ready.book_id,"task_id":task_id,"run_id":run_id,"state":"planned","context_hash":None}
  task_path=book/"production"/"tasks"/f"{task_id}.json";run=book/"runs"/run_id
  reused=_publish(task_path,task);r1=_publish(run/"request.json",request);r2=_publish(run/"status.json",status)
  return ProductionPlanReport(True,"production-plan-report.v1",ready.book_id,chapter_id,task_id,run_id,"planned",reused and r1 and r2,str(task_path),str(run),sha256_json({"task":task,"request":request,"status":status}))
class ContextPackBuilder:
 def build(self,book_root:Path|str,*,run_id:str)->ContextBuildReport:
  book=Path(book_root);run=book/"runs"/run_id;request_path=run/"request.json"
  if not request_path.is_file():raise ProductionInputError(f"unknown run: {run_id}")
  try:req=json.loads(request_path.read_text())
  except Exception as exc:raise ProductionIntegrityError(f"invalid request: {exc}") from exc
  head=EventLog(book).read_lineage("main")[-1]["event_id"]
  pointer=json.loads((book/"compiled"/"current.json").read_text())
  if head!=req["authority_head"] or pointer["compile_id"]!=req["compile_id"]:raise ProductionStaleError("production plan is stale")
  chapter=req["chapter_id"];generation=book/"compiled"/pointer["generation"];objects=json.loads((generation/"objects.json").read_text())["objects"];chapter_data=next(x["data"] for x in objects if x["object_id"]==chapter);pov=chapter_data["pov"]
  state=TemporalStateQuery().query(book,as_of="head");knowledge=KnowledgeBoundaryQuery().query(book,holder_id=pov,as_of="head");obligations=ObligationStateQuery().query(book,as_of="head",status="active");intent=IntentRealityQuery().query(book,scope_id=chapter,as_of="head")
  pack={"schema_version":"context-pack.v1","book_id":req["book_id"],"chapter_id":chapter,"task_id":req["task_id"],"run_id":run_id,"authority_head":head,"compile_id":req["compile_id"],"objective":chapter_data["purpose"],"constraints":{"pov":pov,"location":chapter_data["location"],"time":chapter_data["time"],"must_not_include":chapter_data["intent"]["forbidden"]},"authoritative_context":{"objects":state.objects,"facets":state.facets,"facts":state.facts,"relations":state.relations,"character_knowledge":knowledge.holder_edges,"reader_knowledge":knowledge.reader_edges,"open_obligations":obligations.obligations},"intent_contract":intent.intent,"context_budget":{"hard_limit_chars":28000,"target_fill_ratio":0.55},"output_contract":{"required_files":["prose.md"],"optional_files":["writer-notes.md"]},"forbidden_actions":["modify_state_db","append_events","write_outside_run"]}
  context_hash=sha256_json(pack);path=run/"context-pack.json";reused=_publish(path,pack);status={"schema_version":"run-status.v1","book_id":req["book_id"],"task_id":req["task_id"],"run_id":run_id,"state":"context_ready","context_hash":context_hash}
  status_path=run/"status.json"
  if status_path.exists():
   old=json.loads(status_path.read_text())
   if old["state"] not in {"planned","context_ready"}:raise ProductionIntegrityError("invalid run state")
   if old["state"]=="context_ready" and old!=status:raise ProductionIntegrityError("context-ready status differs")
  atomic_write_json(status_path,status)
  return ContextBuildReport(True,"context-build-report.v1",req["book_id"],chapter,req["task_id"],run_id,"context_ready",reused,str(path),context_hash)
