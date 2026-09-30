---
name: write-beat
description: Produce candidate prose from one frozen ContextPack while preserving the authority boundary.
---

# Skill: write-beat

## Use when
A planned Run is `context_ready` and candidate prose is required.

## Must read
Only the supplied `runs/<run_id>/context-pack.json`, this Skill, and the active Run request.

## Allowed actions
Return candidate prose and writer notes through `python studio.py run start`; the harness publishes only under the Run.

## Forbidden actions
Never write `ledger/`, `state/`, `compiled/`, `chapters/`, snapshots, or another Run. Never call commit.

## Procedure
1. Confirm the ContextPack hash through the runtime harness.
2. Obey POV, time, location, intent, forbidden actions, and context budget.
3. Produce prose and optional notes as candidates, never as authority.
4. Request human review through the deterministic CLI.

## Exit evidence
Run artifacts bind the prose hash and ContextPack hash; authority bytes remain unchanged.
