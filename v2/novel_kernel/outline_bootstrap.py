"""M2.5 approved compiled-generation bootstrap into core.v3 authority events."""
from __future__ import annotations
import hashlib,json,shutil,tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from .events import EventLog, EventLogError, build_event
from .outline import OutlineError
from .outline_compile import OutlineCompiler, OutlineCompileIntegrityError
from .outline_domain import OutlineDomainValidator
from .projection import ProjectionError, ProjectionStore
from .storage import canonical_json_bytes

class BootstrapInputError(OutlineError): exit_code=1
class BootstrapHumanGateError(OutlineError): exit_code=4
class BootstrapEnvironmentError(OutlineError): exit_code=5
class BootstrapIntegrityError(OutlineError): exit_code=6

@dataclass(frozen=True)
class BootstrapResult:
    ok: bool
    schema_version: str
    book_id: str
    compile_id: str
    event_count: int
    head_event_id: str
    projection_state_hash: str
    reused_bootstrap: bool
    approval_owner: str
    approval_time: str


def _hex(compile_id:str,kind:str,key:str,ordinal:int,length:int=32)->str:
    value=f"{compile_id}\0{kind}\0{key}\0{ordinal}".encode()
    return hashlib.sha256(value).hexdigest()[:length]

class OutlineBootstrapper:
    def __init__(self,validator:OutlineDomainValidator|None=None)->None:
        self.validator=validator or OutlineDomainValidator()

    def bootstrap(self,package_path:Path|str,*,expected_book_id:str|None=None)->BootstrapResult:
        report=self.validator.validate(package_path,expected_book_id=expected_book_id)
        owner,approved_at=self._approval(report.manifest)
        root=Path(report.package_path); book=root.parent; compiled=book/"compiled"; current=compiled/"current.json"
        if not current.is_file() or current.is_symlink():
            raise BootstrapInputError("compiled/current.json is required; run outline compile after approval")
        try:
            compile_id=OutlineCompiler._read_previous(current)
            pointer=json.loads(current.read_text(encoding="utf-8"))
        except OutlineCompileIntegrityError:
            raise
        except (OSError,json.JSONDecodeError) as exc:
            raise BootstrapIntegrityError(f"cannot read compiled current pointer: {exc}") from exc
        if pointer.get("source_package_hash")!=report.package_hash:
            raise BootstrapHumanGateError("compiled generation does not match the currently approved Outline Package")
        generation=compiled/pointer["generation"]
        events=self._plan(report.book_id,compile_id,generation,owner,approved_at)
        self._preflight(events)
        log=EventLog(book)
        try:
            existing=log.read_events() if log.log_path.exists() else []
        except EventLogError as exc:
            raise BootstrapIntegrityError(f"cannot verify existing authority log: {exc}") from exc
        reused=self._classify(existing,events)
        if not reused:
            try: log.append_many(events)
            except EventLogError as exc: raise BootstrapIntegrityError(f"cannot commit bootstrap event batch: {exc}") from exc
        try:
            projection=ProjectionStore(book).rebuild(log)
        except ProjectionError as exc:
            raise BootstrapIntegrityError(f"bootstrap events are authoritative but projection rebuild failed: {exc}") from exc
        return BootstrapResult(True,"outline.bootstrap.v1",report.book_id,compile_id,len(events),events[-1]["event_id"],projection.state_hash,reused,owner,approved_at)

    @staticmethod
    def _approval(manifest:dict[str,Any])->tuple[str,str]:
        if manifest.get("status") not in {"approved","frozen"}:
            raise BootstrapHumanGateError("Outline manifest must be approved or frozen before bootstrap")
        approval=manifest.get("approval")
        if not isinstance(approval,dict) or not isinstance(approval.get("owner"),str) or not approval["owner"].strip():
            raise BootstrapHumanGateError("Outline approval.owner is required before bootstrap")
        value=approval.get("approved_at")
        if not isinstance(value,str) or "T" not in value:
            raise BootstrapHumanGateError("Outline approval.approved_at must be a timezone-aware datetime")
        try: parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        except ValueError as exc: raise BootstrapHumanGateError("Outline approval.approved_at is invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise BootstrapHumanGateError("Outline approval.approved_at must include a timezone")
        return approval["owner"],value

    def _plan(self,book_id:str,compile_id:str,generation:Path,owner:str,recorded_at:str)->list[dict[str,Any]]:
        try:
            objects=json.loads((generation/"objects.json").read_text())['objects']
            initial=json.loads((generation/"initial-state.json").read_text())
            obligations=json.loads((generation/"obligations.json").read_text())['obligations']
            production=json.loads((generation/"production-manifest.yaml").read_text())
        except (OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
            raise BootstrapIntegrityError(f"compiled generation cannot produce bootstrap plan: {exc}") from exc
        descriptors:list[tuple[str,str,dict[str,Any],str]]=[]
        for item in sorted(objects,key=lambda x:x["object_id"]):
            descriptors.append(("object.created",item["object_id"],item,f"compiled:{compile_id}/objects.json#{item['object_id']}"))
        object_map={item["object_id"]:item for item in objects}
        facets:list[tuple[str,str,dict[str,Any],str]]=[]; facts:list[tuple[str,str,dict[str,Any],str]]=[]
        for entry in initial.get("characters",[]):
            oid=entry["character_id"]; state=entry["state"]; data=object_map[oid]["data"]; source=f"compiled:{compile_id}/initial-state.json#{oid}"
            candidates:dict[str,dict[str,Any]]={}
            if isinstance(state.get("location"),str): candidates["location"]={"place_id":state["location"]}
            if isinstance(state.get("status"),str): candidates["status"]={"state":state["status"]}
            motives=data.get("motives"); fears=data.get("fears")
            if isinstance(motives,dict) and motives and isinstance(fears,list) and fears:
                motive=str(motives.get("primary") or next(iter(motives.values())))
                candidates["psychology"]={"current_motive":motive,"want":motive,"fear":str(fears[0])}
            capabilities=data.get("capabilities")
            if isinstance(capabilities,list) and capabilities:
                payload={"capabilities":capabilities}
                if isinstance(data.get("constraints"),list): payload["limitations"]=data["constraints"]
                candidates["capability"]=payload
            if isinstance(data.get("constraints"),list) and data["constraints"]:
                candidates["constraint"]={"rules":data["constraints"],"severity":"hard"}
            if isinstance(data.get("arc_refs"),list) and data["arc_refs"]:
                candidates["arc"]={"stage":data["arc_refs"][0]}
            for facet_type,payload in candidates.items(): facets.append((oid,facet_type,payload,source))
            for predicate,value in sorted(state.items()):
                if predicate not in {"location","status"}:
                    facts.append((oid,predicate,{"value":value},source))
        for oid,facet_type,payload,source in sorted(facets,key=lambda x:(x[0],x[1])):
            descriptors.append(("facet.asserted",f"{oid}:{facet_type}",{"object_id":oid,"facet_type":facet_type,"payload":payload},source))
        for oid,predicate,payload,source in sorted(facts,key=lambda x:(x[0],x[1])):
            descriptors.append(("fact.asserted",f"{oid}:{predicate}",{"subject_id":oid,"predicate":predicate,"value":payload["value"]},source))
        relations=[]
        for item in initial.get("items",[]): relations.append((item["holder_id"],"possesses",item["item_id"]))
        for place in initial.get("places",[]): relations.append((place["place_id"],"belongs_to",place["faction_id"]))
        for subject,predicate,obj in sorted(relations):
            key=f"{subject}:{predicate}:{obj}"; source=f"compiled:{compile_id}/initial-state.json#{key}"
            descriptors.append(("relation.asserted",key,{"subject_id":subject,"predicate":predicate,"object_id":obj},source))
        for obligation in sorted(obligations,key=lambda x:x["id"]):
            source=f"compiled:{compile_id}/obligations.json#{obligation['id']}"
            descriptors.append(("obligation.created",obligation["id"],{"obligation":obligation,"compile_id":compile_id,"source_ref":source},source))
        audit_source=f"compiled:{compile_id}/production-manifest.yaml#approval"
        descriptors.append(("audit.completed","outline.bootstrap",{
            "audit_type":"outline.bootstrap","compile_id":compile_id,
            "source_package_hash":production["source_package_hash"],
            "approval":{"owner":owner,"approved_at":recorded_at},
            "planned_event_count":len(descriptors)+1,
        },audit_source))
        events=[]; parent=None; run_id="run_bootstrap_"+compile_id.removeprefix("sha256:")[:16]
        for ordinal,(kind,key,data,source) in enumerate(descriptors,1):
            event_id="event_"+_hex(compile_id,kind,key,ordinal)
            if kind=="object.created":
                raw=data["data"]; payload={"object":{"object_id":data["object_id"],"type":data["object_type"],"canonical_name":raw.get("name") or raw.get("canonical_name") or data["object_id"],"aliases":raw.get("aliases",[]),"status":"active","created_event":event_id,"supersedes":None},"evidence":[]}
            elif kind=="facet.asserted":
                payload={"facet":{"object_id":data["object_id"],"facet_type":data["facet_type"],"facet_version":1,"payload":data["payload"],"valid_from":"story:initial","valid_to":None,"source_refs":[source],"recorded_event":event_id},"evidence":[]}
            elif kind=="fact.asserted":
                fid="fact_bootstrap_"+_hex(compile_id,kind,key,ordinal,16)
                payload={"fact":{"fact_id":fid,"subject_id":data["subject_id"],"predicate":data["predicate"],"value":data["value"],"valid_from":"story:initial","valid_to":None,"recorded_event":event_id,"confidence":"confirmed","status":"asserted","evidence_refs":[source]},"evidence":[]}
            elif kind=="relation.asserted":
                rid="rel_bootstrap_"+_hex(compile_id,kind,key,ordinal,16)
                payload={"relation":{"relation_id":rid,"subject_id":data["subject_id"],"predicate":data["predicate"],"object_id":data["object_id"],"valid_from":"story:initial","valid_to":None,"recorded_event":event_id,"confidence":"confirmed","evidence_refs":[source]},"evidence":[]}
            else: payload=data
            event=build_event(event_id=event_id,event_type=kind,book_id=book_id,branch_id="main",parent_event_id=parent,story_seq=0,recorded_at=recorded_at,actor_type="human",actor_id="studio.outline_bootstrap",source_run_id=run_id,payload=payload,evidence_refs=[source])
            events.append(event); parent=event_id
        if not events: raise BootstrapInputError("compiled generation produced an empty bootstrap plan")
        return events

    @staticmethod
    def _preflight(events:list[dict[str,Any]])->None:
        temp=Path(tempfile.mkdtemp(prefix="outline-bootstrap-preflight-"))
        try:
            log=EventLog(temp/"book")
            log.append_many(events)
            ProjectionStore(temp/"book").rebuild(log)
        except (EventLogError,ProjectionError) as exc:
            raise BootstrapIntegrityError(f"bootstrap preflight failed: {exc}") from exc
        finally: shutil.rmtree(temp,ignore_errors=True)

    @staticmethod
    def _classify(existing:list[dict[str,Any]],planned:list[dict[str,Any]])->bool:
        if not existing: return False
        if existing[0]["event_id"]!=planned[0]["event_id"]:
            raise BootstrapHumanGateError("authority log already exists and was not initialized from this compiled generation")
        limit=min(len(existing),len(planned))
        for index in range(limit):
            if canonical_json_bytes(existing[index])!=canonical_json_bytes(planned[index]):
                raise BootstrapIntegrityError(f"existing bootstrap event differs from deterministic plan at index {index}")
        if len(existing)<len(planned):
            raise BootstrapIntegrityError("authority log contains only a partial bootstrap batch")
        return True
