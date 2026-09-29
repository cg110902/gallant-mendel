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
recorded cutoffs, chapter as-of selection, and optional world-time filtering. It is a read model,
not a new authority or persisted state format.
