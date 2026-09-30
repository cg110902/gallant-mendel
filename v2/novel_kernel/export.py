"""M7.3 deterministic, authority-read-only Markdown/JSON/EPUB export."""
from __future__ import annotations
import html,json,zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from .events import EventLog,EventLogError
from .storage import atomic_write_bytes,atomic_write_json,canonical_json_bytes,sha256_bytes,sha256_file,sha256_json

class ExportError(Exception):
 exit_code=1

@dataclass(frozen=True)
class ExportReport:
 ok:bool;schema_version:str;book_id:str;branch_id:str;export_id:str;chapter_count:int;formats:tuple[str,...];files:tuple[dict[str,str],...];manifest_path:str;manifest_hash:str;authority_head:str

def _zip_entry(name:str,data:bytes,compress:int=zipfile.ZIP_DEFLATED)->tuple[zipfile.ZipInfo,bytes]:
 info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=compress;info.external_attr=0o100644<<16;return info,data

def _epub(book_id:str,chapters:list[dict[str,Any]])->bytes:
 entries=[];entries.append(_zip_entry("mimetype",b"application/epub+zip",zipfile.ZIP_STORED));entries.append(_zip_entry("META-INF/container.xml",b'<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'))
 items=[];spine=[];links=[]
 for i,ch in enumerate(chapters,1):
  name=f"chapter-{i:04d}.xhtml";title=html.escape(ch["chapter_id"]);body=html.escape(ch["content"])
  x=f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head><body><h1>{title}</h1><pre>{body}</pre></body></html>'.encode();entries.append(_zip_entry("OEBPS/"+name,x));items.append(f'<item id="c{i}" href="{name}" media-type="application/xhtml+xml"/>');spine.append(f'<itemref idref="c{i}"/>');links.append(f'<li><a href="{name}">{title}</a></li>')
 nav=('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Contents</title></head><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>'+''.join(links)+'</ol></nav></body></html>').encode();entries.append(_zip_entry("OEBPS/nav.xhtml",nav));opf=(f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">{html.escape(book_id)}</dc:identifier><dc:title>{html.escape(book_id)}</dc:title><dc:language>zh</dc:language></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>').encode();entries.append(_zip_entry("OEBPS/content.opf",opf))
 out=BytesIO()
 with zipfile.ZipFile(out,"w") as z:
  for info,data in entries:z.writestr(info,data)
 return out.getvalue()

class ExportService:
 def export(self,book_root:Path|str,*,branch_id:str="main",formats:tuple[str,...]=("markdown","json","epub"))->ExportReport:
  allowed={"markdown","json","epub"};formats=tuple(sorted(set(formats)))
  if not formats or not set(formats)<=allowed:raise ExportError("formats must be markdown, json, and/or epub")
  book=Path(book_root)
  try:lineage=list(EventLog(book).read_lineage(branch_id))
  except EventLogError as exc:raise ExportError(str(exc)) from exc
  committed={}
  for event in lineage:
   if event["event_type"]=="chapter.committed":committed[event["payload"]["chapter_id"]]=event
  chapters=[]
  for chapter_id,event in sorted(committed.items()):
   path=book/"chapters"/f"{chapter_id}.md"
   if not path.is_file() or path.is_symlink():raise ExportError(f"committed chapter must be a regular non-symlink file: {chapter_id}")
   raw=path.read_bytes()
   if sha256_bytes(raw)!=event["payload"]["prose_hash"]:raise ExportError(f"committed chapter hash mismatch: {chapter_id}")
   try:content=raw.decode("utf-8")
   except UnicodeDecodeError as exc:raise ExportError(f"chapter is not UTF-8: {chapter_id}") from exc
   chapters.append({"chapter_id":chapter_id,"content":content,"prose_hash":event["payload"]["prose_hash"],"commit_event_id":event["event_id"]})
  if not chapters:raise ExportError("no committed chapters on selected branch")
  head=lineage[-1]["event_id"];identity={"book_id":lineage[0]["book_id"],"branch_id":branch_id,"authority_head":head,"chapters":[{k:v for k,v in x.items() if k!="content"} for x in chapters]};export_id="export_"+sha256_json(identity).removeprefix("sha256:")[:24];exports=book/"exports"
  if exports.is_symlink():raise ExportError("exports root must not be a symlink")
  exports.mkdir(parents=True,exist_ok=True);directory=exports/export_id
  if directory.is_symlink():raise ExportError("export generation must not be a symlink")
  directory.mkdir(exist_ok=True);files=[]
  payloads={"markdown":("book.md",("\n\n".join(f'# {x["chapter_id"]}\n\n{x["content"]}' for x in chapters)+"\n").encode()),"json":("book.json",canonical_json_bytes({**identity,"schema_version":"novel-export.v1","chapters":chapters})+b"\n"),"epub":("book.epub",_epub(identity["book_id"],chapters))}
  for fmt in formats:
   name,data=payloads[fmt];path=directory/name
   if path.exists() and path.read_bytes()!=data:raise ExportError(f"immutable export conflict: {path}")
   if not path.exists():atomic_write_bytes(path,data)
   files.append({"format":fmt,"path":f"exports/{export_id}/{name}","sha256":sha256_file(path)})
  base={"schema_version":"export-manifest.v1","book_id":identity["book_id"],"branch_id":branch_id,"export_id":export_id,"chapter_count":len(chapters),"formats":list(formats),"files":files,"authority_head":head};manifest_hash=sha256_json(base);manifest={**base,"manifest_hash":manifest_hash};manifest_path=directory/"manifest.json"
  if manifest_path.exists() and json.loads(manifest_path.read_text())!=manifest:raise ExportError("immutable export manifest conflict")
  if not manifest_path.exists():atomic_write_json(manifest_path,manifest)
  return ExportReport(True,"export-manifest.v1",identity["book_id"],branch_id,export_id,len(chapters),formats,tuple(files),str(manifest_path),manifest_hash,head)
