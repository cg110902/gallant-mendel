"""M2.6 read-only first-chapter ContextPack prerequisite assessment."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .events import EventLog,EventLogError
from .outline import OutlineError
from .outline_compile import OutlineCompiler
from .outline_domain import OutlineDomainValidator
from .projection import ProjectionError,ProjectionStore

class ContextReadinessError(OutlineError): exit_code=3
class ContextReadinessIntegrityError(OutlineError): exit_code=6

@dataclass(frozen=True)
class ContextReadinessReport:
    ready: bool
    schema_version: str
    book_id: str
    compile_id: str
    chapter_id: str
    pov_id: str
    location_id: str
    arc_id: str
    required_event_count: int
    obligation_count: int
    authority_event_count: int
    authority_head: str
    projection_state_hash: str

class OutlineReadinessChecker:
    def __init__(self,validator:OutlineDomainValidator|None=None)->None:
        self.validator=validator or OutlineDomainValidator()
    def check(self,package_path:Path|str,*,expected_book_id:str|None=None)->ContextReadinessReport:
        report=self.validator.validate(package_path,expected_book_id=expected_book_id); root=Path(report.package_path); book=root.parent; current=book/"compiled"/"current.json"
        if not current.is_file(): raise ContextReadinessError("compiled/current.json is required")
        compile_id=OutlineCompiler._read_previous(current)
        try: pointer=json.loads(current.read_text()); generation=book/"compiled"/pointer["generation"]
        except (OSError,KeyError,json.JSONDecodeError) as exc: raise ContextReadinessIntegrityError(f"cannot resolve current generation: {exc}") from exc
        if pointer.get("source_package_hash")!=report.package_hash: raise ContextReadinessError("current generation does not match current Outline Package")
        docs={}
        try:
            for name in ("objects.json","timeline.json","intent-ledger.json","obligations.json"):
                docs[name]=json.loads((generation/name).read_text())
        except (OSError,json.JSONDecodeError) as exc: raise ContextReadinessIntegrityError(f"cannot read compiled prerequisite: {exc}") from exc
        chapters=sorted(docs["intent-ledger.json"].get("chapters",[]),key=lambda x:x.get("chapter_id",""))
        if not chapters: raise ContextReadinessError("intent ledger has no planned chapter")
        chapter_id=chapters[0]["chapter_id"]; objects={item["object_id"]:item for item in docs["objects.json"].get("objects",[])}
        chapter=objects.get(chapter_id)
        if chapter is None or chapter.get("object_type")!="chapter": raise ContextReadinessError(f"first chapter object is missing: {chapter_id}")
        data=chapter["data"]; pov=data.get("pov"); location=data.get("location"); arc=data.get("arc")
        for identifier,label,kind in ((pov,"POV","character"),(location,"location","place"),(arc,"arc","arc")):
            target=objects.get(identifier)
            if target is None or target.get("object_type")!=kind: raise ContextReadinessError(f"chapter {label} prerequisite is missing: {identifier}")
        chapter_times={item.get("chapter_id") for item in docs["timeline.json"].get("chapter_times",[])}
        if chapter_id not in chapter_times: raise ContextReadinessError(f"chapter timeline is missing: {chapter_id}")
        required=data.get("intent",{}).get("required_events",[]); event_ids={item.get("id") for item in docs["timeline.json"].get("events",[])}
        missing=sorted(set(required)-event_ids)
        if missing: raise ContextReadinessError(f"required timeline events are missing: {', '.join(missing)}")
        log=EventLog(book)
        if not log.log_path.is_file(): raise ContextReadinessError("authority event log has not been bootstrapped")
        try: events=log.read_events()
        except EventLogError as exc: raise ContextReadinessIntegrityError(f"authority log failed verification: {exc}") from exc
        markers=[event for event in events if event["event_type"]=="audit.completed" and event["payload"].get("audit_type")=="outline.bootstrap" and event["payload"].get("compile_id")==compile_id]
        if len(markers)!=1:
            raise ContextReadinessError("authority log does not contain exactly one current bootstrap audit marker")
        try:
            projection=ProjectionStore(book); projection_report=projection.verify(log); state=projection.export_state()
        except ProjectionError as exc: raise ContextReadinessIntegrityError(f"projection is not ready: {exc}") from exc
        projected_ids={item["object_id"] for item in state["objects"]}
        if pov not in projected_ids or location not in projected_ids: raise ContextReadinessError("POV or location is absent from projected authority")
        pov_facets={item["facet_type"] for item in state["facets"] if item["object_id"]==pov}
        required_facets={"location","status","capability"}; absent=sorted(required_facets-pov_facets)
        if absent: raise ContextReadinessError(f"POV is missing required facets: {', '.join(absent)}")
        obligations=docs["obligations.json"].get("obligations",[])
        return ContextReadinessReport(True,"outline.context-readiness.v1",report.book_id,compile_id,chapter_id,pov,location,arc,len(required),len(obligations),len(events),events[-1]["event_id"],projection_report.state_hash)
