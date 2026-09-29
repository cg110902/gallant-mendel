# Versioned schemas

M0 fixture manifests use deterministic standard-library validation. M1.3 adds Draft 2020-12
JSON Schema artifacts for `Object`, `Facet`, `Relation`, `Fact`, and `Evidence` v1.

Runtime validation remains standard-library-only in `novel_kernel.objects`; these schema files
are portable contracts for IDEs and future adapters. Unknown fields are rejected. Facet payload
changes require a new `facet_version`; validators must not silently loosen v1.

`event.schema.json` mirrors the strict Event Envelope implemented by `novel_kernel.events`.
Event-type payload semantics are frozen separately in the M1.4 projection decision because the
envelope stays stable while later milestones add handlers.

M3.1 adds `temporal-state.v1.schema.json`, the strict deterministic report for EventLog-lineage
recorded cutoffs, chapter as-of selection, and optional world-time filtering. M3.2 adds
`knowledge-diff.v1.schema.json` for stable truth/character/reader boundary sets and active edges.
M3.3 adds `obligation-state.v1.schema.json` for evidence-gated lifecycle and schedule reports.
M3.4 adds `intent-reality-diff.v1.schema.json` for deterministic reconcile classifications.
M3.5 adds `reader-tension.v1.schema.json` and `impact-report.v1.schema.json` for structural analytics.
These are read models, not new authority or persisted state formats.

M4.1 adds strict `production-task.v1`, `production-request.v1`, `run-status.v1`, and
`context-pack.v1` contracts. They freeze a deterministic production plan and derived context;
they do not authorize prose, model invocation, or EventLog mutation.

M4.2 extends `run-status.v1` and adds strict `writer-invocation.v1`, `writer-result.v1`,
and `writer-run-report.v1` contracts for context-only candidate Writer attempts. These artifacts
are non-authoritative; `draft_ready` does not mean audited, committed, or published.

M4.3 adds strict `human-checkpoint.v1` and `human-decision.v1` contracts, provider budget
metadata, and review states. An `extraction_ready` decision is only a gate for M5; it does not
perform extraction or authorize any authority mutation.

M5.1 adds strict `candidate-claims.v1`, `candidate-state-delta.v1`,
`extraction-evidence.v1`, and `extraction-report.v1` contracts. All extracted state remains
candidate-only, is exact-span evidence-bound, and explicitly declines semantic completeness.

M5.2 adds strict `candidate-reconcile.v1`. It compares candidate fact deltas with the frozen
ContextPack authority and intent contract, producing non-authoritative safe, review, or hard-block
classifications without running the full Auditor or mutating EventLog/SQLite.
