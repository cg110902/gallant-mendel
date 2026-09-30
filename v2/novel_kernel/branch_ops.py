"""M7.3 explicit branch forks and non-destructive rollback markers."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .events import ACTOR_RE,BRANCH_ID_RE,FORBIDDEN_ACTORS,EventLog,EventLogError,build_event
from .storage import sha256_json

class BranchOperationError(Exception):
 exit_code=1

@dataclass(frozen=True)
class BranchOperationReport:
 ok:bool;schema_version:str;book_id:str;branch_id:str;source_branch:str;fork_event_id:str;marker_event_id:str;mode:str;main_head_unchanged:bool;report_hash:str

class BranchService:
 def create(self,book_root:Path|str,*,branch_id:str,from_event:str|None=None,source_branch:str="main",actor:str="human.editor",mode:str="fork")->BranchOperationReport:
  if BRANCH_ID_RE.fullmatch(branch_id or "") is None or branch_id=="main":raise BranchOperationError("branch ID must be valid and must not be main")
  if ACTOR_RE.fullmatch(actor or "") is None or actor in FORBIDDEN_ACTORS:raise BranchOperationError("actor must be an authorized core actor ID")
  if mode not in {"fork","non_destructive_rollback"}:raise BranchOperationError("unsupported branch operation mode")
  log=EventLog(book_root)
  try: state=log.verify();source=list(log.read_lineage(source_branch))
  except EventLogError as exc:raise BranchOperationError(str(exc)) from exc
  if branch_id in state.heads:raise BranchOperationError(f"branch already exists: {branch_id}")
  fork=from_event or source[-1]["event_id"];by_id={x["event_id"]:x for x in source}
  if fork not in by_id:raise BranchOperationError("fork event must belong to source branch lineage")
  source_event=by_id[fork];main_before=state.heads.get("main")
  payload={"branch_id":branch_id,"source_branch":source_branch,"fork_event_id":fork,"mode":mode}
  marker_id="event_"+sha256_json(payload).removeprefix("sha256:")[:32]
  marker=build_event(event_id=marker_id,event_type="branch.created",book_id=state.book_id or "",branch_id=branch_id,parent_event_id=fork,story_seq=source_event["story_seq"],actor_type="human",actor_id=actor,payload=payload)
  try:log.append(marker)
  except EventLogError as exc:raise BranchOperationError(str(exc)) from exc
  main_after=log.verify().heads.get("main");base={"schema_version":"branch-operation-report.v1","book_id":state.book_id,"branch_id":branch_id,"source_branch":source_branch,"fork_event_id":fork,"marker_event_id":marker_id,"mode":mode,"main_head_unchanged":main_before==main_after}
  return BranchOperationReport(True,**base,report_hash=sha256_json(base))
