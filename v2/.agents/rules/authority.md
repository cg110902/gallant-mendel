# Portable authority rule

Use `.agents/skills/` as the canonical skill source. All adapter commands must end at `python studio.py`.
Writers and IDE agents must not directly modify `ledger/events.jsonl`, `state/state.db`, `compiled/`,
`snapshots/*/manifest.json`, or `chapters/`. Authority changes only through deterministic reconcile/commit commands.
No API key, MCP server, IDE hook, or model provider is required for core validation and recovery.
