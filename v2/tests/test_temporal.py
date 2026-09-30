from __future__ import annotations
import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.events import EventLog,build_event
from novel_kernel.temporal import TemporalQueryInputError,TemporalQueryInvariantError,TemporalStateQuery

ROOT=Path(__file__).resolve().parents[1]
def eid(n:int)->str:return f"event_{n:032x}"
def obj(n:int)->dict:return {"object_id":"char_hero","type":"character","canonical_name":"Hero","aliases":[],"status":"active","created_event":eid(n),"supersedes":None}
def make(n:int,kind:str,payload:dict,parent:str|None,seq:int)->dict:
 return build_event(event_id=eid(n),event_type=kind,book_id="book_temporal",branch_id="main",parent_event_id=parent,story_seq=seq,recorded_at=f"2026-09-29T00:{n:02d}:00+00:00",actor_type="reconciler",actor_id="studio.test",source_run_id="run_temporal_tests",payload=payload)
def fact(n:int,fid:str,start:str,end:str|None)->dict:
 return {"fact":{"fact_id":fid,"subject_id":"char_hero","predicate":"has_state","value":fid,"valid_from":start,"valid_to":end,"recorded_event":eid(n),"confidence":"confirmed","status":"asserted","evidence_refs":[f"evidence_{n:03d}"]},"evidence":[]}
def tree_hash(root:Path)->str:
 values=[]
 for path in sorted(p for p in root.rglob("*") if p.is_file()):values.append((str(path.relative_to(root)),hashlib.sha256(path.read_bytes()).hexdigest()))
 return hashlib.sha256(json.dumps(values).encode()).hexdigest()

class TemporalQueryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_temporal";log=EventLog(self.book)
  events=[
   make(1,"object.created",{"object":obj(1),"evidence":[]},None,0),
   make(2,"fact.asserted",fact(2,"fact_past","story:0001","story:0003"),eid(1),1),
   make(3,"fact.asserted",fact(3,"fact_future_recorded","story:0002",None),eid(2),2),
   make(4,"fact.asserted",fact(4,"fact_unknown","unknown",None),eid(3),3),
   make(5,"object.renamed",{"object_id":"char_hero","canonical_name":"Renamed","aliases":["Hero"]},eid(4),4),
  ]
  for event in events:log.append(event)
  self.query=TemporalStateQuery()
 def tearDown(self):self.temp.cleanup()
 def test_event_cutoff_prevents_future_recorded_assertion_leak(self):
  report=self.query.query(self.book,as_of=eid(2))
  self.assertEqual([x["fact_id"] for x in report.facts],["fact_past"])
  self.assertEqual(report.objects[0]["canonical_name"],"Hero")
 def test_chapter_cutoff_is_longest_prefix_and_head_folds_rename(self):
  chapter=self.query.query(self.book,as_of="ch_002")
  self.assertEqual(chapter.cutoff["event_id"],eid(3));self.assertEqual(len(chapter.facts),2)
  self.assertEqual(self.query.query(self.book,as_of="head").objects[0]["canonical_name"],"Renamed")
 def test_valid_window_is_half_open_and_unknown_does_not_match(self):
  inside=self.query.query(self.book,as_of="head",valid_at="story:0002")
  self.assertEqual([x["fact_id"] for x in inside.facts],["fact_future_recorded","fact_past"])
  end=self.query.query(self.book,as_of="head",valid_at="story:0003")
  self.assertEqual([x["fact_id"] for x in end.facts],["fact_future_recorded"])
  self.assertEqual(len(self.query.query(self.book,as_of="head").facts),3)
 def test_query_is_byte_read_only_and_hash_deterministic(self):
  before=tree_hash(self.book);first=self.query.query(self.book,as_of="head");second=self.query.query(self.book,as_of="head")
  self.assertEqual(before,tree_hash(self.book));self.assertEqual(first.state_hash,second.state_hash)
 def test_invalid_selectors_are_input_errors(self):
  for selector in ("ch_0","ch_-1","event_ffffffffffffffffffffffffffffffff","later"):
   with self.subTest(selector=selector),self.assertRaises(TemporalQueryInputError):self.query.query(self.book,as_of=selector)
 def test_nonmonotonic_story_sequence_only_blocks_chapter_query(self):
  other=Path(self.temp.name)/"nonmono";log=EventLog(other)
  first=make(1,"object.created",{"object":obj(1),"evidence":[]},None,2);second=make(2,"audit.completed",{"result":"ok"},eid(1),1)
  log.append(first);log.append(second)
  self.assertEqual(self.query.query(other,as_of="head").cutoff["event_id"],eid(2))
  with self.assertRaises(TemporalQueryInvariantError):self.query.query(other,as_of="ch_002")
 def test_complete_domain_fold_matches_recorded_and_valid_state(self):
  from tests.test_projection import ten_event_sequence
  book=Path(self.temp.name)/"complete";log=EventLog(book)
  for event in ten_event_sequence():log.append(event)
  head=self.query.query(book,as_of="head")
  self.assertEqual(head.objects[0]["canonical_name"],"凌云舟")
  self.assertEqual(head.facts[0]["status"],"disputed")
  self.assertEqual([x["facet_type"] for x in head.facets],["location"])
  self.assertEqual(head.relations[0]["valid_to"],"story:0009")
  self.assertEqual(len(self.query.query(book,as_of="head",valid_at="story:0009").relations),0)
 def test_cli_json_and_exit_codes(self):
  good=subprocess.run([sys.executable,str(ROOT/"studio.py"),"state","query","--path",str(self.book),"--as-of","ch_002","--json"],cwd=ROOT,text=True,capture_output=True)
  self.assertEqual(good.returncode,0,good.stderr);self.assertEqual(json.loads(good.stdout)["schema_version"],"temporal-state.v1")
  bad=subprocess.run([sys.executable,str(ROOT/"studio.py"),"state","query","--path",str(self.book),"--as-of","ch_0","--json"],cwd=ROOT,text=True,capture_output=True)
  self.assertEqual(bad.returncode,1);self.assertEqual(json.loads(bad.stdout)["exit_code"],1)

if __name__=="__main__":unittest.main()
