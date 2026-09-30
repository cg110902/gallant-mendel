"""M7.4 honest vendor-runtime attestation bundle validation.

This module validates operator-supplied evidence; it never claims to launch an IDE.
"""
from __future__ import annotations
import json,re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from .storage import atomic_write_json,sha256_file,sha256_json

CHECK_IDS=("workflow.novel-status","workflow.novel-init","workflow.novel-context","workflow.novel-write","workflow.novel-review","workflow.novel-commit","terminal.doctor","terminal.compatibility-matrix","terminal.branch-create","terminal.rollback","terminal.export-repeat")
SHA_RE=re.compile(r"^sha256:[0-9a-f]{64}$")
class AttestationError(Exception):exit_code=1
@dataclass(frozen=True)
class AttestationReport:
 ok:bool;schema_version:str;status:str;vendor:str;vendor_runtime_executed:bool;check_count:int;passed:int;bundle_hash:str;output_path:str

def template()->dict[str,Any]:
 base={"schema_version":"ide-live-attestation-input.v1","vendor":"antigravity","ide_version":"REPLACE_ME","os":"REPLACE_ME","executed_at":"REPLACE_ME","operator":"REPLACE_ME","operator_attestation":"I personally executed these checks in the named vendor IDE runtime.","checks":[{"id":x,"status":"pending","evidence":[]} for x in CHECK_IDS]}
 return {**base,"template_hash":sha256_json(base)}

def write_template(output:Path|str)->str:
 p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);atomic_write_json(p,template());return str(p)

def _load(path:Path)->dict[str,Any]:
 try:value=json.loads(path.read_text())
 except (OSError,json.JSONDecodeError) as exc:raise AttestationError(f"cannot read attestation input: {exc}") from exc
 if not isinstance(value,dict):raise AttestationError("attestation input must be an object")
 return value

def finalize(input_path:Path|str,output:Path|str)->AttestationReport:
 source=Path(input_path);doc=_load(source);required={"schema_version","vendor","ide_version","os","executed_at","operator","operator_attestation","checks"}
 if not required<=doc.keys() or doc.get("schema_version")!="ide-live-attestation-input.v1":raise AttestationError("invalid live attestation input contract")
 if doc.get("vendor")!="antigravity":raise AttestationError("this acceptance kit is scoped to Antigravity")
 for field in ("ide_version","os","operator"):
  if not isinstance(doc.get(field),str) or not doc[field].strip() or doc[field]=="REPLACE_ME":raise AttestationError(f"{field} must be completed")
 try:stamp=datetime.fromisoformat(str(doc["executed_at"]).replace("Z","+00:00"))
 except ValueError as exc:raise AttestationError("executed_at must be ISO-8601") from exc
 if stamp.tzinfo is None:raise AttestationError("executed_at must include a timezone")
 expected="I personally executed these checks in the named vendor IDE runtime."
 if doc.get("operator_attestation")!=expected:raise AttestationError("operator attestation statement is missing")
 checks=doc.get("checks");by_id={x.get("id"):x for x in checks if isinstance(x,dict)} if isinstance(checks,list) else {}
 if set(by_id)!=set(CHECK_IDS) or len(checks)!=len(CHECK_IDS):raise AttestationError("exactly the frozen eleven checks are required")
 normalized=[]
 for check_id in CHECK_IDS:
  row=by_id[check_id]
  if row.get("status")!="pass":raise AttestationError(f"check is not pass: {check_id}")
  evidence=row.get("evidence")
  if not isinstance(evidence,list) or not evidence:raise AttestationError(f"check lacks evidence: {check_id}")
  bound=[]
  for item in evidence:
   if not isinstance(item,dict) or set(item)!={"path","sha256"} or not SHA_RE.fullmatch(str(item.get("sha256",""))):raise AttestationError(f"invalid evidence binding: {check_id}")
   rel=Path(str(item["path"]));raw_target=source.parent/rel;target=raw_target.resolve();root=source.parent.resolve()
   if rel.is_absolute() or target==root or root not in target.parents or raw_target.is_symlink() or not target.is_file():raise AttestationError(f"unsafe or missing evidence path: {item['path']}")
   actual=sha256_file(target)
   if actual!=item["sha256"]:raise AttestationError(f"evidence hash mismatch: {item['path']}")
   bound.append({"path":rel.as_posix(),"sha256":actual})
  normalized.append({"id":check_id,"status":"pass","evidence":bound})
 base={"schema_version":"ide-live-attestation.v1","status":"accepted","vendor":"antigravity","ide_version":doc["ide_version"],"os":doc["os"],"executed_at":doc["executed_at"],"operator":doc["operator"],"operator_attestation":expected,"vendor_runtime_executed":True,"live_attestation_required":False,"surrogate_report_unchanged":True,"checks":normalized,"check_count":len(normalized),"passed":len(normalized),"input_hash":sha256_file(source)};bundle_hash=sha256_json(base);result={**base,"bundle_hash":bundle_hash};out=Path(output);out.parent.mkdir(parents=True,exist_ok=True);atomic_write_json(out,result)
 return AttestationReport(True,"ide-live-attestation.v1","accepted","antigravity",True,len(normalized),len(normalized),bundle_hash,str(out))
