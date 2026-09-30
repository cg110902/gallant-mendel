"""M3.5 deterministic knowledge-set tension and structural impact analytics."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .knowledge import KnowledgeBoundaryQuery
from .storage import sha256_json
from .temporal import CHAPTER_RE,TemporalQueryInputError,TemporalStateQuery
@dataclass(frozen=True)
class ReaderTensionReport:
 ok:bool;schema_version:str;book_id:str;branch_id:str;holder_id:str;as_of:str;window:int
 samples:tuple[dict[str,Any],...];sample_count:int;totals:dict[str,int];latest:dict[str,int];delta:dict[str,int];tension_hash:str
@dataclass(frozen=True)
class ImpactReport:
 ok:bool;schema_version:str;book_id:str;branch_id:str;as_of:str;object_id:str;depth:int
 direct_nodes:tuple[dict[str,Any],...];transitive_nodes:tuple[dict[str,Any],...];type_counts:dict[str,int];impact_hash:str
class ReaderTensionQuery:
 def query(self,book_root:Path|str,*,holder_id:str,as_of:str,window:int,branch_id:str="main"):
  m=CHAPTER_RE.fullmatch(as_of) if isinstance(as_of,str) else None
  if m is None or int(m.group(1))<=0:raise TemporalQueryInputError("reader tension --as-of must be ch_<positive-number>")
  if isinstance(window,bool) or not isinstance(window,int) or window<=0:raise TemporalQueryInputError("--window must be a positive integer")
  end=int(m.group(1));start=max(1,end-window+1);samples=[];query=KnowledgeBoundaryQuery();keys=("reader_only","holder_only","shared","hidden_truth")
  for chapter in range(start,end+1):
   selector=f"ch_{chapter:03d}"
   try:r=query.query(book_root,holder_id=holder_id,as_of=selector,branch_id=branch_id)
   except TemporalQueryInputError as exc:
    if "no authority state exists" in str(exc):continue
    raise
   samples.append({"chapter":selector,**{key:len(getattr(r,key)) for key in keys},"knowledge_hash":r.knowledge_hash})
  if not samples:raise TemporalQueryInputError("window contains no queryable authority chapter")
  totals={key:sum(item[key] for item in samples) for key in keys};latest={key:samples[-1][key] for key in keys};delta={key:samples[-1][key]-samples[0][key] for key in keys}
  base={"schema_version":"reader-tension.v1","book_id":r.book_id,"branch_id":branch_id,"holder_id":holder_id,"as_of":as_of,"window":window,"samples":tuple(samples),"sample_count":len(samples),"totals":totals,"latest":latest,"delta":delta}
  return ReaderTensionReport(ok=True,**base,tension_hash=sha256_json(base))
class ImpactQuery:
 def query(self,book_root:Path|str,*,object_id:str,as_of:str,depth:int=3,branch_id:str="main"):
  if not isinstance(object_id,str) or not object_id:raise TemporalQueryInputError("--object is required")
  if isinstance(depth,bool) or not isinstance(depth,int) or not 1<=depth<=8:raise TemporalQueryInputError("--depth must be within 1..8")
  state=TemporalStateQuery().query(book_root,as_of=as_of,branch_id=branch_id)
  objects={x["object_id"] for x in state.objects}
  if object_id not in objects:raise TemporalQueryInputError(f"object is not active at cutoff: {object_id}")
  graph:dict[str,set[str]]={}
  def edge(a,b):graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
  for item in state.facets:edge("object:"+item["object_id"],f"facet:{item['object_id']}:{item['facet_type']}")
  facts={x["fact_id"] for x in state.facts}
  for item in state.facts:edge("object:"+item["subject_id"],"fact:"+item["fact_id"])
  for item in state.relations:
   rel="relation:"+item["relation_id"];edge(rel,"object:"+item["subject_id"])
   target=("fact:" if item["object_id"] in facts else "object:")+item["object_id"];edge(rel,target)
  root="object:"+object_id;distance={root:0};queue=deque([root])
  while queue:
   node=queue.popleft()
   if distance[node]>=depth:continue
   for nxt in sorted(graph.get(node,set())):
    if nxt not in distance:distance[nxt]=distance[node]+1;queue.append(nxt)
  nodes=[]
  for node,d in distance.items():
   if node==root:continue
   kind,identifier=node.split(":",1);nodes.append({"node_id":node,"node_type":kind,"identifier":identifier,"distance":d})
  nodes.sort(key=lambda x:(x["distance"],x["node_type"],x["identifier"]));direct=tuple(x for x in nodes if x["distance"]==1);transitive=tuple(x for x in nodes if x["distance"]>1)
  counts={kind:sum(x["node_type"]==kind for x in nodes) for kind in ("object","facet","fact","relation")}
  base={"schema_version":"impact-report.v1","book_id":state.book_id,"branch_id":branch_id,"as_of":as_of,"object_id":object_id,"depth":depth,"direct_nodes":direct,"transitive_nodes":transitive,"type_counts":counts}
  return ImpactReport(ok=True,**base,impact_hash=sha256_json(base))
