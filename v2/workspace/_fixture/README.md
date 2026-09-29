# Verification fixtures

- `valid/` — valid deterministic manifest
- `broken_missing_manifest/` — directory intentionally lacks `manifest.json`
- `broken_invalid_json/` — malformed JSON
- `broken_missing_field/` — valid JSON missing a required field
- `broken_readonly_probe/` — source fixture for a temporary chmod-based permission probe

Verification never mutates these fixtures. Permission checks are copied or created under
`verification/M0/tmp/`; unsupported chmod semantics are recorded as `SKIP`, never `PASS`.

## M2.1 Outline fixtures

`outline/valid-json/` is the complete zero-dependency Outline Package v1 baseline. The
`broken-*` packages independently cover missing manifest, malformed JSON, invalid manifest,
unknown root entries, and duplicate JSON/YAML variants. Runtime-only symlink and YAML-adapter
cases are created under `verification/M2.1/tmp/` and removed after verification.

## M2.2 semantic fixture

`outline/valid-semantic/` adds 12 declarations, 22 explicit references, three story-time
windows, and one timeline ordering edge. It also contains complete M2.3 fields for nine domain
record types, one turning point, and one beat. M2.4 compiles copies of this package into
content-addressed generations under verification temp directories. Error packages are copied and
mutated under the corresponding `verification/M2.x/tmp/`; fixtures and the demo package are never
modified by validation or verification. M2.5 creates approved copies in verification temp space,
then proves deterministic bootstrap, human-gate rejection, and projection recovery.
