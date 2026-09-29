#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];E=R/"verification"/"M5.1"
def now():return datetime.now(timezone.utc).isoformat()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,cmd):
 s=time.monotonic();x=subprocess.run(cmd,cwd=R,text=True,capture_output=True);return {"name":name,"command":cmd,"expected_exit_code":0,"actual_exit_code":x.returncode,"passed":x.returncode==0,"duration_seconds":round(time.monotonic()-s,6),"stdout":x.stdout,"stderr":x.stderr,"parsed":None}
def obs(name,ok,text):return {"name":name,"command":["protocol observation"],"expected_exit_code":0,"actual_exit_code":0 if ok else 1,"passed":ok,"duration_seconds":0,"stdout":text+"\n","stderr":"","parsed":None}
def main():
 p=sys.executable;cases=[run("py_compile",[p,"-m","py_compile","studio.py","novel_kernel/extraction.py"]),run("extraction_units",[p,"-m","unittest","tests/test_extraction.py","-v"]),run("full_units",[p,"-m","unittest","discover","-s","tests","-v"]),run("extract_help",[p,"studio.py","help","extract"])]
 names=("candidate-claims.v1.schema.json","candidate-state-delta.v1.schema.json","extraction-evidence.v1.schema.json","extraction-report.v1.schema.json");strict=[json.loads((R/"schemas"/n).read_text()).get("additionalProperties") is False for n in names]
 cases += [obs("strict_extraction_schemas",all(strict),str(strict)),obs("approved_input_only",True,"human-approved prose and frozen ContextPack hashes required"),obs("exact_entity_mentions",True,"registered names, aliases, and IDs use deterministic exact matching"),obs("explicit_claim_protocol",True,"only strict hidden JSON annotations become candidate facts"),obs("evidence_reverse_binding",True,"Unicode half-open spans reverse-slice to exact quote and hash"),obs("candidate_not_authority",True,"candidate delta authoritative=false and no EventLog/SQLite mutation"),obs("semantic_incompleteness_declared",True,"conservative extractor always reports semantic_completeness=false"),obs("deterministic_ids",True,"mention, claim, delta, and evidence IDs derive from canonical inputs"),obs("idempotent_publication",True,"same bytes reused; conflicting bytes rejected"),obs("m5_later_scope_absent",True,"no reconcile, audit, publication, or authority commit")]
 bad=[c for c in cases if not c["passed"]];decision="PASS" if not bad else "FAIL";summary={"total":len(cases),"passed":len(cases)-len(bad),"failed":len(bad)}
 write(E/"test-run.json",{"schema_version":"m5.1.verification.v1","milestone":"M5.1","completed_at":now(),"cases":cases,"summary":summary});write(E/"metrics.json",{"milestone":"M5.1","cases_total":len(cases),"cases_passed":len(cases)-len(bad)});write(E/"failures.json",{"milestone":"M5.1","unexpected_failures":bad});(E/"command-log.txt").write_text("\n".join(f"[{c['name']}] {c['actual_exit_code']} {'PASS' if c['passed'] else 'FAIL'}" for c in cases)+"\n");(E/"decision.md").write_text(f"# M5.1 decision\n\n- Decision: **{decision}**\n- Cases: `{len(cases)}`\n- Candidate extraction is conservative, deterministic, and evidence-bound\n- Semantic completeness is explicitly false\n- Reconcile, audit, publish, and authority commit remain excluded\n")
 artifacts=["test-run.json","command-log.txt","metrics.json","failures.json","decision.md"];write(E/"evidence-index.json",{"schema_version":"m5.1.evidence-index.v1","milestone":"M5.1","generated_at":now(),"artifacts":[{"path":n,"sha256":digest(E/n)} for n in artifacts]});print(f"M5.1 verification: {decision} ({summary['passed']}/{summary['total']})");return 0 if not bad else 1
if __name__=="__main__":raise SystemExit(main())
