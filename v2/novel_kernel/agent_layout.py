"""M7.1 deterministic validation of portable skills and thin IDE adapters."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LayoutCheck:
    platform: str
    check_id: str
    passed: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"platform": self.platform, "check_id": self.check_id, "status": "pass" if self.passed else "fail", "message": self.message}


@dataclass(frozen=True)
class AgentLayoutReport:
    ok: bool
    checks: tuple[LayoutCheck, ...]
    platform_totals: dict[str, dict[str, int]]


def _regular(root: Path, relative: str) -> tuple[bool, str]:
    path = root / relative
    ok = path.is_file() and not path.is_symlink()
    return ok, f"{relative} is a regular non-symlink file" if ok else f"missing, non-file, or symlink: {relative}"


def _text(root: Path, relative: str) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def validate_agent_layout(root: Path | str) -> AgentLayoutReport:
    base = Path(root)
    rows: list[LayoutCheck] = []

    def add(platform: str, check_id: str, passed: bool, message: str) -> None:
        rows.append(LayoutCheck(platform, check_id, bool(passed), message))

    def file(platform: str, check_id: str, relative: str) -> str:
        ok, message = _regular(base, relative)
        add(platform, check_id, ok, message)
        return _text(base, relative) if ok else ""

    doctor = file("antigravity", "canonical_doctor_skill", ".agents/skills/novel-doctor/SKILL.md")
    writer = file("antigravity", "canonical_writer_skill", ".agents/skills/write-beat/SKILL.md")
    rule = file("antigravity", "authority_rule", ".agents/rules/authority.md")
    workflows = [f".agents/workflows/novel-{name}.md" for name in ("doctor", "plan", "write", "audit", "commit", "resume")]
    add("antigravity", "workflow_set", all(_regular(base, path)[0] for path in workflows), "six /novel-* thin workflows exist")
    add("antigravity", "skill_frontmatter", doctor.startswith("---\n") and "name: novel-doctor" in doctor and writer.startswith("---\n") and "name: write-beat" in writer, "canonical skills have discovery frontmatter")
    add("antigravity", "studio_delegation", all("python studio.py" in _text(base, path) for path in workflows), "all workflows delegate to studio.py")
    add("antigravity", "authority_denied", all(token in rule for token in ("ledger/events.jsonl", "state/state.db", "chapters/")), "authority rule names protected roots")
    add("antigravity", "candidate_boundary", "candidate" in writer.lower() and "Never write" in writer, "writer skill preserves candidate boundary")
    add("antigravity", "no_api_key_core", "No API key" in rule, "core remains no-API-key capable")
    add("antigravity", "portable_paths", "/home/" not in doctor + writer + rule + "".join(_text(base, p) for p in workflows), "canonical adapter uses no machine-specific absolute path")

    claude = file("claude", "adapter_instructions", ".claude/CLAUDE.md")
    auditor = file("claude", "auditor_agent", ".claude/agents/auditor.md")
    settings_text = file("claude", "settings_example", ".claude/settings.example.json")
    try:
        settings = json.loads(settings_text); settings_ok = isinstance(settings, dict)
    except json.JSONDecodeError:
        settings = {}; settings_ok = False
    add("claude", "settings_json", settings_ok, "settings example parses as JSON")
    add("claude", "canonical_reference", "../.agents/skills/" in claude, "adapter references canonical skills")
    add("claude", "agents_reference", "../AGENTS.md" in claude, "adapter references shared AGENTS.md")
    add("claude", "studio_hook", "python studio.py doctor --agent-layout" in settings_text, "hook delegates to doctor")
    add("claude", "protected_roots", all(root in settings_text for root in ("ledger/**", "state/**", "snapshots/**", "chapters/**")), "settings deny four authority roots")
    add("claude", "auditor_read_only", "Do not edit" in auditor and "EventLog" in auditor, "auditor adapter is authority read-only")
    add("claude", "thin_adapter", len(claude.splitlines()) <= 20 and len(auditor.splitlines()) <= 20, "adapter files remain thin")
    add("claude", "portable_paths", "/home/" not in claude + auditor + settings_text, "adapter uses no machine-specific absolute path")

    cursor_rule = file("cursor", "scoped_rule", ".cursor/rules/novel-production.mdc")
    cursor_writer = file("cursor", "writer_agent", ".cursor/agents/writer.md")
    hooks_text = file("cursor", "hooks_example", ".cursor/hooks.example.json")
    try:
        hooks = json.loads(hooks_text); hooks_ok = isinstance(hooks, dict)
    except json.JSONDecodeError:
        hooks = {}; hooks_ok = False
    add("cursor", "hooks_json", hooks_ok, "hooks example parses as JSON")
    add("cursor", "canonical_reference", ".agents/skills/" in cursor_rule and ".agents/skills/write-beat/SKILL.md" in cursor_writer, "Cursor references canonical skills")
    add("cursor", "agents_reference", "AGENTS.md" in cursor_rule, "Cursor references shared AGENTS.md")
    add("cursor", "studio_delegation", "python studio.py" in cursor_rule and "python studio.py" in cursor_writer and "python studio.py doctor" in hooks_text, "rules, agent, and hook delegate to studio.py")
    add("cursor", "protected_roots", all(root in hooks_text for root in ("ledger/**", "state/**", "snapshots/**", "chapters/**")), "hooks list four protected roots")
    add("cursor", "context_pack_only", "frozen ContextPack" in cursor_writer and "Do not scan" in cursor_writer, "writer receives bounded context")
    add("cursor", "thin_adapter", len(cursor_rule.splitlines()) <= 20 and len(cursor_writer.splitlines()) <= 20, "adapter files remain thin")
    add("cursor", "portable_paths", "/home/" not in cursor_rule + cursor_writer + hooks_text, "adapter uses no machine-specific absolute path")

    codex = file("codex", "config_example", ".codex/config.example.toml")
    add("codex", "approval_policy", 'approval_policy = "on-request"' in codex, "approval is explicit")
    add("codex", "workspace_sandbox", 'sandbox_mode = "workspace-write"' in codex, "workspace sandbox is declared")
    add("codex", "canonical_reference", ".agents/skills" in codex, "config references canonical skills")
    add("codex", "agents_reference", "AGENTS.md" in codex, "config references shared AGENTS.md")
    add("codex", "studio_delegation", "python studio.py" in codex, "config delegates to studio.py")
    add("codex", "ledger_denied", "ledger" in codex and "Never directly write" in codex, "ledger direct writes denied")
    add("codex", "state_denied", "state" in codex and "Never directly write" in codex, "state direct writes denied")
    add("codex", "chapter_denied", "chapters" in codex and "Never directly write" in codex, "chapter direct writes denied")
    add("codex", "thin_adapter", len(codex.splitlines()) <= 10, "config remains thin")
    add("codex", "portable_paths", "/home/" not in codex, "adapter uses no machine-specific absolute path")

    totals: dict[str, dict[str, int]] = {}
    for platform in ("antigravity", "claude", "cursor", "codex"):
        selected = [row for row in rows if row.platform == platform]
        totals[platform] = {"total": len(selected), "passed": sum(row.passed for row in selected), "failed": sum(not row.passed for row in selected)}
    return AgentLayoutReport(all(row.passed for row in rows), tuple(rows), totals)
