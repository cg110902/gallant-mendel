---
name: novel-doctor
description: Validate the portable Novel Production OS environment and thin IDE adapter layout without requiring an API key.
---

# Skill: novel-doctor

## Use when
Opening the project in a new IDE, after adapter changes, or before production work.

## Must read
`AGENTS.md`, `directory-contract.md`, and `exit-codes.md`.

## Procedure
1. Run `python studio.py doctor --agent-layout --no-api-key --json` from this directory.
2. Stop on any nonzero exit code; do not repair authority files.
3. Report failed check IDs and preserve machine-readable output.

## Forbidden actions
Never edit `ledger/events.jsonl`, `state/state.db`, snapshot manifests, or committed chapters.

## Exit evidence
A zero exit and JSON report with all `agent_layout.*` checks passing.
