from __future__ import annotations
import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.events import EventLog,build_event
from novel_kernel.reconcile import IntentRealityQuery
from novel_kernel.temporal import TemporalQueryIntegrityError
ROOT=Path(__file__).resolve().parents[1]
def eid(n):return f"event_{n:032x}"
def ev(n,kind,payload,parent,seq=1):return build_event(event_id=eid(n),event_type=kind,book_id="book_reconcile",branch_id="main",parent_event_id=parent,story_seq=seq,recorded_at=f"2026-09-29T04:{n:02d}:00+00:00",actor_type="reconciler",actor_id="studio.reconcile-test",source_run_id="run_reconcile_tests",payload=payload)
def intent():return {"intent":{"scope_id":"ch_001","scope_type":"chapter","required_actions":["a1","a2"],"required_changes":["c1"],"required_reveals":["r1"],"required_obligations":["ob1"],"forbidden_changes":["bad"],"source_refs":["outline:ch1"]},"evidence":[]}
def reality(source=eid(2),approval=eid(3)):
 return {"reality":{"scope_id":"ch_001","observed_actions":["a1","ax"],"observed_changes":["c1","cx","bad"],"observed_reveals":[],"observed_obligations":["ob1"],"observed_entities":["char_hero"],"contradictions":["timeline_conflict"],"approved_missing":{"a2":approval},"approved_extras":{"ax":approval},"source_event_id":source,"source_refs":["chapter:ch_001"]},"evidence":[]}
def tree(root):
 vals=[(str(p.relative_to(root)),hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(x for x in root.rglob("*") if x.is_file())];return hashlib.sha256(json.dumps(vals).encode()).hexdigest()
class ReconcileTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_reconcile";log=EventLog(self.book)
  vals=[ev(1,"intent.registered",intent(),None,0),ev(2,"chapter.committed",{"chapter_id":"ch_001"},eid(1),1),ev(3,"audit.completed",{"decision":"approve"},eid(2),1),ev(4,"reality.observed",reality(),eid(3),1)]
  for x in vals:log.append(x)
  self.query=IntentRealityQuery()
 def tearDown(self):self.temp.cleanup()
 def test_all_seven_classifications_are_deterministic(self):
  r=self.query.query(self.book,scope_id="ch_001",as_of="head")
  self.assertEqual(r.counts,{"intent_fulfilled":3,"intent_missing":1,"intent_changed_with_approval":1,"emergent_valid":1,"emergent_unregistered":1,"contradiction":1,"hard_violation":1});self.assertTrue(r.has_hard_violation)
 def test_before_reality_required_items_are_missing(self):
  r=self.query.query(self.book,scope_id="ch_001",as_of=eid(3));self.assertIsNone(r.reality);self.assertEqual(r.counts["intent_missing"],5)
 def test_future_reality_does_not_leak_to_chapter_zero(self):
  r=self.query.query(self.book,scope_id="ch_001",as_of=eid(1));self.assertIsNone(r.reality)
 def test_invalid_approval_reference_is_integrity_error(self):
  book=Path(self.temp.name)/"bad";log=EventLog(book)
  for x in list(EventLog(self.book).read_lineage("main"))[:3]:log.append(x)
  log.append(ev(4,"reality.observed",reality(approval=eid(2)),eid(3),1))
  with self.assertRaisesRegex(TemporalQueryIntegrityError,"approval must reference"):self.query.query(book,scope_id="ch_001",as_of="head")
 def test_reality_source_must_match_committed_chapter(self):
  book=Path(self.temp.name)/"source";log=EventLog(book);log.append(ev(1,"intent.registered",intent(),None,0));log.append(ev(2,"chapter.committed",{"chapter_id":"ch_002"},eid(1),1));log.append(ev(3,"audit.completed",{},eid(2),1));log.append(ev(4,"reality.observed",reality(),eid(3),1))
  with self.assertRaisesRegex(TemporalQueryIntegrityError,"does not match scope"):self.query.query(book,scope_id="ch_001",as_of="head")
 def test_duplicate_reality_is_integrity_error(self):
  EventLog(self.book).append(ev(5,"reality.observed",reality(),eid(4),2))
  with self.assertRaisesRegex(TemporalQueryIntegrityError,"duplicate reality"):self.query.query(self.book,scope_id="ch_001",as_of="head")
 def test_read_only_and_stable_hash(self):
  before=tree(self.book);a=self.query.query(self.book,scope_id="ch_001",as_of="head");b=self.query.query(self.book,scope_id="ch_001",as_of="head");self.assertEqual(before,tree(self.book));self.assertEqual(a.diff_hash,b.diff_hash)
 def test_cli_json_and_unknown_scope(self):
  cmd=[sys.executable,str(ROOT/"studio.py"),"reconcile","diff","--path",str(self.book),"--scope","ch_001","--as-of","head","--json"];r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)["schema_version"],"intent-reality-diff.v1")
  cmd[cmd.index("ch_001")]="ch_missing";bad=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);self.assertEqual(bad.returncode,1)
if __name__=="__main__":unittest.main()
