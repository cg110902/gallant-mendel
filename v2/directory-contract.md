# Directory contract

`v2/` is the only engineering root. Commands are executed from this directory.

## M0 repository layout

- `studio.py` — deterministic CLI entry point
- `novel_kernel/` — standard-library-only deterministic core
- `schemas/` — versioned machine schemas (reserved in M0)
- `scripts/` — black-box verification and maintenance commands
- `tests/` — `unittest` test suite
- `workspace/_fixture/` — test inputs, never a production book
- `verification/<milestone>/` — external acceptance evidence
- `施工状态/` — implementation hand-off status, not business authority

## M0 initialized workspace layout

`studio.py init --path <target>` creates only:

```text
<target>/
├── manifest.json
├── outline/
├── state/
├── ledger/
├── production/
├── chapters/
├── runs/
├── audits/
├── snapshots/
├── branches/
└── exports/
```

M0 must not create `events.jsonl`, `state.db`, prose, or production-agent artifacts.
Existing targets are rejected unless `--force` is explicit. Force mode preserves unknown
user files and refreshes only the M0-owned manifest and required empty directories.

## M2.4 compiled layout

A successful `outline compile` publishes derived, content-addressed artifacts below the book:

```text
<book>/compiled/current.json
<book>/compiled/generations/<compile-id-hex>/
```

Consumers resolve only through `current.json`. Generation directories are immutable and
contain seven logical artifacts plus `artifact-index.json`; old generations may remain for
audit. Compiled data is derived and does not replace `ledger/events.jsonl` authority.

## M2.5 authority bootstrap

Only `outline bootstrap` may promote an approved current generation into initial authority.
It appends one deterministic batch to `ledger/events.jsonl` and rebuilds `state/state.db`.
Repeated execution verifies and reuses the same batch; a different generation cannot silently
reinitialize a non-empty book. `outline readiness` is strictly read-only and only reports whether
current compiled, authority, projection, timeline, intent, and first-chapter inputs are closed.

## M3.1 temporal state query

`state query` reads and verifies an existing branch lineage directly from `ledger/events.jsonl`.
It folds Object/Facet/Fact/Relation history in memory for recorded event/head, chapter as-of, and
optional world-time filtering. It creates no database, snapshot, cache, or query artifact. The
strict report contract is `schemas/temporal-state.v1.schema.json`; acceptance evidence belongs in
`verification/M3.1/`.

## M3.2 knowledge boundary query

`knowledge diff` folds `knowledge.granted` and `knowledge.retracted` on the same verified lineage.
Character and reader edges remain separate from Fact truth. Reader grants require an earlier
`chapter.committed` authority event. The command writes no projection or cache; its strict report
is `schemas/knowledge-diff.v1.schema.json`, with evidence in `verification/M3.2/`.

## M3.3 Future Obligation query

`obligation list` folds canonical obligation lifecycle events from the verified EventLog lineage.
It reports active/terminal and scheduled/due/overdue state without creating a projection or cache.
The report schema is `schemas/obligation-state.v1.schema.json`; acceptance evidence belongs in
`verification/M3.3/`.

## M3.4 Intent/Reality reconciliation

`reconcile diff` folds bootstrap intent and committed-chapter Reality observations directly from
the verified lineage. It is read-only; schema is `schemas/intent-reality-diff.v1.schema.json` and
evidence belongs in `verification/M3.4/`.

All paths are handled with `pathlib`. Runtime book data belongs below `workspace/<book_id>/`;
no second event log, database, or CLI entry point may be created at repository root.
