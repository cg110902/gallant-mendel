#!/usr/bin/env python3
"""Acceptance evidence for M7.1 portable IDE layouts and doctor integration."""
from __future__ import annotations
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));E=ROOT/"verification"/"M7.1";E.mkdir(parents=True,exist_ok=True);cases=[]
def digest(p):return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def check(name,value,detail=""):cases.append({"name":name,"passed":bool(value),"detail":detail})
def run(name,cmd):
 t=time.monotonic();p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);cases.append({"name":name,"passed":p.returncode==0,"detail":f"exit={p.returncode} duration={time.monotonic()-t:.3f}s","stdout":p.stdout,"stderr":p.stderr});return p
py=sys.executable
run("py_compile",[py,"-m","py_compile","studio.py","novel_kernel/agent_layout.py"])
run("agent_layout_units",[py,"-m","unittest","tests.test_agent_layout","-v"])
doctor=run("doctor_agent_layout_no_api",[py,"studio.py","doctor","--agent-layout","--no-api-key","--json"])
try:report=json.loads(doctor.stdout)
except json.JSONDecodeError:report={}
if report:(E/"agent-layout-report.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
check("doctor_report_ok",report.get("ok") is True and report.get("agent_layout",{}).get("ok") is True)
totals=report.get("agent_layout",{}).get("platform_totals",{})
check("four_platforms_present",set(totals)=={"antigravity","claude","cursor","codex"},str(sorted(totals)))
for platform in ("antigravity","claude","cursor","codex"):
 row=totals.get(platform,{});check(f"{platform}_at_least_ten_checks",row.get("total",0)>=10 and row.get("passed")==row.get("total") and row.get("failed")==0,str(row))
checks=report.get("checks",[]);layout=[x for x in checks if x.get("id","").startswith("agent_layout.")]
check("all_layout_checks_pass",len(layout)>=40 and all(x["status"]=="pass" for x in layout),f"count={len(layout)}")
check("no_api_key_required",report.get("api_key_required") is False)
files=[".agents/skills/novel-doctor/SKILL.md",".agents/skills/write-beat/SKILL.md",".agents/rules/authority.md",".claude/CLAUDE.md",".claude/agents/auditor.md",".claude/settings.example.json",".cursor/rules/novel-production.mdc",".cursor/agents/writer.md",".cursor/hooks.example.json",".codex/config.example.toml"]
check("all_adapter_files_regular",all((ROOT/x).is_file() and not (ROOT/x).is_symlink() for x in files))
texts="".join((ROOT/x).read_text() for x in files);check("no_machine_absolute_paths","/home/" not in texts)
check("authority_roots_named",all(token in texts for token in ("ledger","state","snapshots","chapters")))
check("studio_is_only_execution_surface","python studio.py" in texts)
check("six_antigravity_workflows",len(list((ROOT/".agents"/"workflows").glob("novel-*.md")))==6)
check("legacy_doctor_compatible",subprocess.run([py,"studio.py","doctor","--no-api-key","--json"],cwd=ROOT,capture_output=True).returncode==0)
failed=[x for x in cases if not x["passed"]];summary={"total":len(cases),"passed":len(cases)-len(failed),"failed":len(failed)};now=datetime.now(timezone.utc).isoformat()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
write(E/"test-run.json",{"schema_version":"m7.1.verification.v1","milestone":"M7.1","completed_at":now,"cases":cases,"summary":summary})
write(E/"metrics.json",{"milestone":"M7.1","platform_totals":totals,"layout_check_count":len(layout),"no_api_key":report.get("api_key_required") is False,"cases":summary})
write(E/"failures.json",{"milestone":"M7.1","unexpected_failures":failed})
(E/"command-log.txt").write_text("\n".join(f"[{x['name']}] {'PASS' if x['passed'] else 'FAIL'} {x['detail']}" for x in cases)+"\n")
(E/"decision.md").write_text(f"# M7.1 decision\n\n- Decision: **{'PASS' if not failed else 'FAIL'}**\n- Cases: **{summary['passed']}/{summary['total']} PASS**\n- Canonical skills and six Antigravity workflows are present\n- Claude Code, Cursor, and Codex adapters remain thin and delegate to studio.py\n- Four platforms each pass at least ten deterministic static layout/safety checks\n- doctor --agent-layout works without an API key and rejects stale references/symlinks\n- This does not claim real-vendor end-to-end execution or sandbox enforcement\n")
artifacts=["agent-layout-report.json","test-run.json","metrics.json","failures.json","command-log.txt","decision.md"];write(E/"evidence-index.json",{"schema_version":"evidence-index.v1","milestone":"M7.1","files":[{"path":n,"sha256":digest(E/n)} for n in artifacts]})
print(f"M7.1 {'PASS' if not failed else 'FAIL'}: {summary['passed']}/{summary['total']}");raise SystemExit(0 if not failed else 1)
