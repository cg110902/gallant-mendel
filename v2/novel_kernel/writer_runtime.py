"""M4.2 candidate Writer runtime boundary and recoverable run controller."""
from __future__ import annotations
import json
from dataclasses import asdict,dataclass,field
from pathlib import Path
from typing import Protocol
from .production import ProductionInputError,ProductionIntegrityError,ProductionStaleError,_publish
from .storage import atomic_write_bytes,atomic_write_json,canonical_json_bytes,sha256_bytes,sha256_file

@dataclass(frozen=True)
class RuntimeRequest:
 context_pack_bytes:bytes;context_hash:str;attempt_id:str
@dataclass(frozen=True)
class RuntimeResult:
 ok:bool;prose:str;writer_notes:str;stdout:str;stderr:str;error:str|None=None;metadata:dict=field(default_factory=dict)
class ModelRuntime(Protocol):
 name:str
 def invoke(self,request:RuntimeRequest)->RuntimeResult:...
class OfflineWriterRuntime:
 """Deterministic protocol adapter for tests and offline operation; not a quality model."""
 name="offline"
 def invoke(self,request:RuntimeRequest)->RuntimeResult:
  pack=json.loads(request.context_pack_bytes);c=pack["constraints"];intent=pack["intent_contract"]
  prose=(f"# {pack['chapter_id']} 候选稿\n\n"
         f"视角人物 {c['pov']} 身处 {c['location']}。本章目标是 {pack['objective']}。\n\n"
         f"候选叙事围绕既定行动展开：{'、'.join(intent.get('required_actions',[])) or '保持既定推进'}。"
         "此稿仅用于运行时协议验证，等待抽取、审计与人工修订。\n")
  notes="offline adapter generated a deterministic candidate; no literary-quality claim.\n"
  return RuntimeResult(True,prose,notes,f"writer attempt {request.attempt_id} completed\n","",None)
@dataclass(frozen=True)
class RunReport:
 ok:bool;schema_version:str;book_id:str;task_id:str;run_id:str;state:str;attempt_id:str|None;runtime:str|None;prose_path:str|None;prose_hash:str|None

def _read(path:Path)->dict:
 try:return json.loads(path.read_text())
 except Exception as exc:raise ProductionIntegrityError(f"invalid artifact {path}: {exc}") from exc
def _sentinel(book:Path)->dict[str,str|None]:
 paths=("ledger/events.jsonl","ledger/heads.json","state/state.db","compiled/current.json")
 return {p:sha256_file(book/p) if (book/p).is_file() else None for p in paths}
def _write_once(path:Path,data:bytes)->None:
 if path.exists():
  if path.read_bytes()!=data:raise ProductionIntegrityError(f"existing attempt artifact differs: {path}")
  return
 path.parent.mkdir(parents=True,exist_ok=True);atomic_write_bytes(path,data)
def _status(run:Path)->dict:return _read(run/"status.json")
def _save_status(run:Path,status:dict)->None:atomic_write_json(run/"status.json",status)
class WriterRunController:
 def __init__(self,runtimes:dict[str,ModelRuntime]|None=None):self.runtimes=runtimes or {"offline":OfflineWriterRuntime()}
 def _runtime(self,name:str)->ModelRuntime:
  runtime=self.runtimes.get(name)
  if runtime is not None:return runtime
  if name=="openai-compatible":
   try:
    from .provider_runtime import OpenAICompatibleRuntime
    return OpenAICompatibleRuntime.from_env()
   except Exception as exc:raise ProductionInputError(f"provider configuration invalid: {exc}") from None
  raise ProductionInputError(f"unknown runtime: {name}")
 def _paths(self,book:Path,run_id:str)->tuple[Path,dict,dict,dict]:
  run=book/"runs"/run_id
  if not run.is_dir():raise ProductionInputError(f"unknown run: {run_id}")
  return run,_read(run/"request.json"),_read(run/"context-pack.json"),_status(run)
 def _validate_context(self,pack:dict,status:dict,path:Path)->None:
  actual=sha256_bytes(canonical_json_bytes(pack))
  if status.get("context_hash")!=actual:raise ProductionStaleError("context hash differs from frozen run status")
  if path.read_bytes()!=canonical_json_bytes(pack):raise ProductionIntegrityError("context pack is not canonical")
 def _report(self,req:dict,status:dict)->RunReport:
  return RunReport(status.get("state") not in {"writer_failed","violated"},"writer-run-report.v1",req["book_id"],req["task_id"],req["run_id"],status["state"],status.get("attempt_id"),status.get("runtime"),status.get("prose_path"),status.get("prose_hash"))
 def start_task(self,book_root:Path|str,*,task_id:str,runtime_name:str="offline")->RunReport:
  book=Path(book_root);task_path=book/"production"/"tasks"/f"{task_id}.json"
  if not task_path.is_file():raise ProductionInputError(f"unknown task: {task_id}")
  return self._execute(book,_read(task_path)["run_id"],runtime_name,{"context_ready"})
 def resume(self,book_root:Path|str,*,run_id:str,runtime_name:str="offline")->RunReport:
  return self._execute(Path(book_root),run_id,runtime_name,{"writer_running","writer_failed","needs_rework"})
 def _execute(self,book:Path,run_id:str,runtime_name:str,allowed:set[str])->RunReport:
  run,req,pack,status=self._paths(book,run_id);self._validate_context(pack,status,run/"context-pack.json")
  if status["state"] not in allowed:raise ProductionInputError(f"cannot execute writer from state: {status['state']}")
  runtime=self._runtime(runtime_name)
  number=int(status.get("attempt_count",0))+1;attempt_id=f"attempt_{number:03d}";attempt=run/"attempts"/attempt_id
  runtime_config=getattr(runtime,"invocation_metadata",lambda:{})()
  before=_sentinel(book);request_doc={"schema_version":"writer-invocation.v1","run_id":run_id,"attempt_id":attempt_id,"runtime":runtime_name,"context_hash":status["context_hash"],"runtime_config":runtime_config}
  _publish(attempt/"request.json",request_doc)
  running={**status,"state":"writer_running","attempt_count":number,"attempt_id":attempt_id,"runtime":runtime_name};_save_status(run,running)
  try:result=runtime.invoke(RuntimeRequest(canonical_json_bytes(pack),status["context_hash"],attempt_id))
  except Exception as exc:result=RuntimeResult(False,"","","",str(exc),f"runtime exception: {type(exc).__name__}")
  _write_once(attempt/"stdout.log",result.stdout.encode());_write_once(attempt/"stderr.log",result.stderr.encode())
  if result.prose:_write_once(attempt/"prose.md",result.prose.encode())
  if result.writer_notes:_write_once(attempt/"writer-notes.md",result.writer_notes.encode())
  result_doc={"schema_version":"writer-result.v1","run_id":run_id,"attempt_id":attempt_id,"runtime":runtime_name,"ok":result.ok,"prose_hash":sha256_bytes(result.prose.encode()) if result.prose else None,"error":result.error,"metadata":result.metadata};_publish(attempt/"result.json",result_doc)
  after=_sentinel(book)
  if before!=after:
   violated={**running,"state":"violated","authority_sentinel_before":before,"authority_sentinel_after":after};_save_status(run,violated);raise ProductionIntegrityError("writer changed protected authority files")
  if not result.ok:
   failed={**running,"state":"writer_failed","error":result.error or "runtime failed"};_save_status(run,failed);return self._report(req,failed)
  prose=result.prose.encode();_write_once(run/"prose.md",prose);_write_once(run/"writer-notes.md",result.writer_notes.encode())
  ready={**running,"state":"draft_ready","prose_path":"prose.md","prose_hash":sha256_bytes(prose),"error":None};_save_status(run,ready);return self._report(req,ready)
 def status(self,book_root:Path|str,*,run_id:str)->RunReport:
  _,req,_,status=self._paths(Path(book_root),run_id);return self._report(req,status)
 def request_review(self,book_root:Path|str,*,run_id:str)->RunReport:
  run,req,_,status=self._paths(Path(book_root),run_id)
  if status["state"]!="draft_ready":raise ProductionInputError(f"cannot request review from state: {status['state']}")
  prose=run/"prose.md"
  if not prose.is_file():raise ProductionIntegrityError("draft_ready run has no prose.md")
  number=int(status.get("review_count",0))+1;review_id=f"review_{number:03d}";prose_hash=sha256_file(prose)
  checkpoint={"schema_version":"human-checkpoint.v1","run_id":run_id,"review_id":review_id,"context_hash":status["context_hash"],"prose_hash":prose_hash,"state":"pending"};_publish(run/"reviews"/review_id/"checkpoint.json",checkpoint)
  pending={**status,"state":"human_review","review_count":number,"review_id":review_id,"review_prose_hash":prose_hash};_save_status(run,pending);return self._report(req,pending)
 def decide_review(self,book_root:Path|str,*,run_id:str,decision:str,actor:str,note:str="")->RunReport:
  run,req,_,status=self._paths(Path(book_root),run_id)
  if status["state"]!="human_review":raise ProductionInputError(f"cannot decide review from state: {status['state']}")
  if decision not in {"approve","rework"}:raise ProductionInputError("decision must be approve or rework")
  if not actor.strip() or len(actor)>128:raise ProductionInputError("actor must be non-empty and at most 128 characters")
  if len(note)>2000:raise ProductionInputError("review note exceeds 2000 characters")
  prose_hash=sha256_file(run/"prose.md")
  if prose_hash!=status["review_prose_hash"]:raise ProductionStaleError("prose changed while human review was pending")
  review_id=status["review_id"];record={"schema_version":"human-decision.v1","run_id":run_id,"review_id":review_id,"decision":decision,"actor":actor,"note":note,"context_hash":status["context_hash"],"prose_hash":prose_hash};_publish(run/"reviews"/review_id/"decision.json",record)
  decided={**status,"state":"extraction_ready" if decision=="approve" else "needs_rework","review_decision":decision,"review_actor":actor};_save_status(run,decided);return self._report(req,decided)
 def abort(self,book_root:Path|str,*,run_id:str)->RunReport:
  run,req,_,status=self._paths(Path(book_root),run_id)
  if status["state"]=="aborted":return self._report(req,status)
  if status["state"] not in {"context_ready","writer_running","writer_failed"}:raise ProductionInputError(f"cannot abort from state: {status['state']}")
  aborted={**status,"state":"aborted"};_save_status(run,aborted);return self._report(req,aborted)
