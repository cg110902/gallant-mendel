from __future__ import annotations
import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from novel_kernel.events import EventLog,build_event
from novel_kernel.obligations import ObligationStateQuery
from novel_kernel.temporal import TemporalQueryIntegrityError
ROOT=Path(__file__).resolve().parents[1]
def eid(n):return f"event_{n:032x}"
def event(n,kind,payload,parent,seq,branch="main"):
 return build_event(event_id=eid(n),event_type=kind,book_id="book_obligations",branch_id=branch,parent_event_id=parent,story_seq=seq,recorded_at=f"2026-09-29T03:{n:02d}:00+00:00",actor_type="reconciler",actor_id="studio.obligation-test",source_run_id="run_obligation_tests",payload=payload)
def obligation(allowed=None,minimum=2,latest=4):
 return {"obligation_id":"ob_secret","kind":"mystery","owner_id":"thread_secret","created_at_story_seq":0,"expected_window":{"earliest":2,"latest":latest},"weight":0.8,"status":"open","last_touched_seq":None,"payoff_event_id":None,"allowed_resolution":allowed or ["fulfilled","subverted","deferred","retired"],"reader_visibility":"concealed","evidence_requirement":{"min_clues":minimum,"payoff_requires":["reveal_secret"]},"source_refs":["outline:obligations#secret"]}
def touch(n,parent,source,seq=2):return event(n,"obligation.touched",{"obligation_id":"ob_secret","touch_kind":"clue","source_event_id":source,"source_refs":["chapter:clue"],"evidence":[]},parent,seq)
def tree(root):
 vals=[(str(p.relative_to(root)),hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(x for x in root.rglob("*") if x.is_file())]
 return hashlib.sha256(json.dumps(vals).encode()).hexdigest()
class ObligationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.book=Path(self.temp.name)/"book_obligations";log=EventLog(self.book)
  values=[event(1,"obligation.created",{"obligation":obligation(),"evidence":[]},None,0),event(2,"chapter.committed",{"chapter_id":"ch_001"},eid(1),1),touch(3,eid(2),eid(2),1),event(4,"scene.committed",{"scene_id":"scene_002"},eid(3),2),touch(5,eid(4),eid(4),2),event(6,"chapter.committed",{"chapter_id":"ch_003"},eid(5),3),event(7,"obligation.fulfilled",{"obligation_id":"ob_secret","payoff_event_id":eid(6),"satisfied_requirements":["reveal_secret"],"source_refs":["chapter:payoff"],"evidence":[]},eid(6),3)]
  for x in values:log.append(x)
  self.query=ObligationStateQuery()
 def tearDown(self):self.temp.cleanup()
 def test_as_of_lifecycle_and_no_future_leak(self):
  created=self.query.query(self.book,as_of=eid(1)).obligations[0];self.assertEqual((created["status"],created["schedule_state"]),("open","scheduled"))
  touched=self.query.query(self.book,as_of="ch_002").obligations[0];self.assertEqual((touched["status"],touched["clue_count"],touched["schedule_state"]),("touched",2,"due"))
  head=self.query.query(self.book,as_of="head");self.assertEqual(head.obligations[0]["status"],"fulfilled");self.assertEqual(head.terminal_count,1)
 def test_status_filters(self):
  self.assertEqual(len(self.query.query(self.book,as_of="ch_002",status="active").obligations),1)
  self.assertEqual(len(self.query.query(self.book,as_of="ch_002",status="due").obligations),1)
  self.assertEqual(len(self.query.query(self.book,as_of="head",status="fulfilled").obligations),1)
  self.assertEqual(len(self.query.query(self.book,as_of="head",status="active").obligations),0)
 def test_insufficient_clues_block_payoff(self):
  book=Path(self.temp.name)/"insufficient";log=EventLog(book)
  vals=list(EventLog(self.book).read_lineage("main"))[:4]
  for x in vals:log.append(x)
  payoff=event(5,"obligation.fulfilled",{"obligation_id":"ob_secret","payoff_event_id":eid(4),"satisfied_requirements":["reveal_secret"],"source_refs":["scene:payoff"],"evidence":[]},eid(4),2);log.append(payoff)
  with self.assertRaisesRegex(TemporalQueryIntegrityError,"insufficient clue"):self.query.query(book,as_of="head")
 def test_missing_payoff_requirement_is_blocked(self):
  book=Path(self.temp.name)/"requirements";log=EventLog(book)
  for x in list(EventLog(self.book).read_lineage("main"))[:6]:log.append(x)
  bad=event(7,"obligation.fulfilled",{"obligation_id":"ob_secret","payoff_event_id":eid(6),"satisfied_requirements":[],"source_refs":["chapter:payoff"],"evidence":[]},eid(6),3);log.append(bad)
  with self.assertRaisesRegex(TemporalQueryIntegrityError,"requirements are not satisfied"):self.query.query(book,as_of="head")
 def test_defer_moves_window_later_and_can_become_overdue(self):
  book=Path(self.temp.name)/"defer";log=EventLog(book);log.append(event(1,"obligation.created",{"obligation":obligation(),"evidence":[]},None,0));log.append(event(2,"chapter.committed",{"chapter_id":"ch_001"},eid(1),1));log.append(event(3,"obligation.deferred",{"obligation_id":"ob_secret","new_expected_window":{"earliest":5,"latest":7},"reason":"arc expanded","source_event_id":eid(2),"source_refs":["chapter:decision"],"evidence":[]},eid(2),1));log.append(event(4,"audit.completed",{"result":"advance"},eid(3),8))
  report=self.query.query(book,as_of="head");self.assertEqual(report.obligations[0]["status"],"deferred");self.assertEqual(report.overdue_count,1)
 def test_subverted_and_retired_are_expressible(self):
  sub=Path(self.temp.name)/"subverted";log=EventLog(sub)
  for x in list(EventLog(self.book).read_lineage("main"))[:6]:log.append(x)
  log.append(event(7,"obligation.subverted",{"obligation_id":"ob_secret","payoff_event_id":eid(6),"satisfied_requirements":["reveal_secret"],"source_refs":["chapter:subvert"],"evidence":[]},eid(6),3));self.assertEqual(self.query.query(sub,as_of="head").obligations[0]["status"],"subverted")
  retired=Path(self.temp.name)/"retired";log=EventLog(retired);log.append(event(1,"obligation.created",{"obligation":obligation(),"evidence":[]},None,0));log.append(event(2,"audit.completed",{"decision":"retire"},eid(1),1));log.append(event(3,"obligation.retired",{"obligation_id":"ob_secret","reason":"approved scope change","source_event_id":eid(2),"source_refs":["audit:2"],"evidence":[]},eid(2),1));self.assertEqual(self.query.query(retired,as_of="head").obligations[0]["status"],"retired")
 def test_terminal_transition_is_blocked(self):
  EventLog(self.book).append(event(8,"obligation.touched",{"obligation_id":"ob_secret","touch_kind":"reminder","source_event_id":eid(6),"source_refs":["chapter:late"],"evidence":[]},eid(7),4))
  with self.assertRaisesRegex(TemporalQueryIntegrityError,"terminal obligation"):self.query.query(self.book,as_of="head")
 def test_query_is_read_only_and_deterministic(self):
  before=tree(self.book);a=self.query.query(self.book,as_of="ch_002");b=self.query.query(self.book,as_of="ch_002");self.assertEqual(before,tree(self.book));self.assertEqual(a.obligation_hash,b.obligation_hash)
 def test_cli_json_and_invalid_filter(self):
  cmd=[sys.executable,str(ROOT/"studio.py"),"obligation","list","--path",str(self.book),"--as-of","ch_002","--json"]
  good=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);self.assertEqual(good.returncode,0,good.stderr);self.assertEqual(json.loads(good.stdout)["schema_version"],"obligation-state.v1")
  bad=subprocess.run(cmd[:-2]+["--status","nonsense","--json"],cwd=ROOT,text=True,capture_output=True);self.assertEqual(bad.returncode,1)
if __name__=="__main__":unittest.main()
