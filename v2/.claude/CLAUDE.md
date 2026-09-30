# Claude Code adapter

Read `../AGENTS.md` and canonical skills in `../.agents/skills/`. This file is a thin discovery adapter.
Run `python studio.py doctor --agent-layout --no-api-key` before production work. Never directly write
`ledger/events.jsonl`, `state/state.db`, snapshots, compiled authority, or committed chapters.
