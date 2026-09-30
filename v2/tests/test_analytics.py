from __future__ import annotations
import subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.analytics import ImpactQuery,ReaderTensionQuery
from novel_kernel.events import EventLog
from tests.test_knowledge import eid,event,fact,grant
from tests.test_projection import ten_event_sequence
ROOT=Path(__file__).resolve().parents[1]
class AnalyticsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_knowledge";log=EventLog(self.book);obj={"object_id":"char_hero","type":"character","canonical_name":"Hero","aliases":[],"status":"active","created_event":eid(1),"supersedes":None}
  vals=[event(1,"object.created",{"object":obj,"evidence":[]},None,0),event(2,"fact.asserted",fact(2,"fact_shared"),eid(1),0),event(3,"fact.asserted",fact(3,"fact_hidden"),eid(2),0),event(4,"chapter.committed",{"chapter_id":"ch_001"},eid(3),1),event(5,"knowledge.granted",grant("_reader","fact_shared","confirmed",eid(4)),eid(4),1),event(6,"knowledge.granted",grant("char_hero","fact_shared","confirmed",eid(4)),eid(5),2)]
  for x in vals:log.append(x)
 def tearDown(self):self.temp.cleanup()
 def test_tension_window_counts_and_delta(self):
  r=ReaderTensionQuery().query(self.book,holder_id="char_hero",as_of="ch_002",window=2);self.assertEqual(r.sample_count,2);self.assertEqual(r.samples[0]["reader_only"],1);self.assertEqual(r.samples[1]["shared"],1);self.assertEqual(r.delta["shared"],1)
 def test_tension_is_deterministic(self):
  q=ReaderTensionQuery();self.assertEqual(q.query(self.book,holder_id="char_hero",as_of="ch_002",window=2).tension_hash,q.query(self.book,holder_id="char_hero",as_of="ch_002",window=2).tension_hash)
 def test_tension_rejects_nonchapter_and_window(self):
  for selector,window in (("head",2),("ch_002",0)):
   with self.assertRaises(Exception):ReaderTensionQuery().query(self.book,holder_id="char_hero",as_of=selector,window=window)
 def test_impact_bfs_structural_radius(self):
  book=Path(self.temp.name)/"impact";log=EventLog(book)
  for x in ten_event_sequence():log.append(x)
  r=ImpactQuery().query(book,object_id="char_lin_yun",as_of=eid(6),depth=3);self.assertGreaterEqual(r.type_counts["fact"],1);self.assertGreaterEqual(r.type_counts["relation"],1);self.assertTrue(any(x["node_type"]=="facet" for x in r.direct_nodes))
 def test_impact_depth_guard_and_unknown_object(self):
  with self.assertRaises(Exception):ImpactQuery().query(self.book,object_id="missing",as_of="head",depth=3)
  with self.assertRaises(Exception):ImpactQuery().query(self.book,object_id="char_hero",as_of="head",depth=9)
 def test_cli_reports(self):
  a=subprocess.run([sys.executable,str(ROOT/"studio.py"),"reader","tension","--path",str(self.book),"--holder","char_hero","--as-of","ch_002","--window","2","--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(a.returncode,0,a.stderr)
  b=subprocess.run([sys.executable,str(ROOT/"studio.py"),"impact","analyze","--path",str(self.book),"--object","char_hero","--as-of","head","--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(b.returncode,0,b.stderr)
if __name__=="__main__":unittest.main()
