# Exit-code contract

| Code | Symbol | Meaning | First milestone used |
|---:|---|---|---|
| 0 | `SUCCESS` | Command completed successfully | M0 |
| 1 | `INPUT_OR_CONFIG_ERROR` | Invalid argument, path, layout, or configuration | M0 |
| 2 | `SCHEMA_FORMAT_ERROR` | Invalid JSON, schema, or structural format | M0 |
| 3 | `HARD_VIOLATION` | A hard story invariant or readiness prerequisite was violated | M2.6 |
| 4 | `HUMAN_GATE` | Human approval or conflict resolution is required | M2.5 |
| 5 | `ENVIRONMENT_ERROR` | Unsupported Python, permission, dependency, or environment | M0 |
| 6 | `REPLAY_PROJECTION_ERROR` | Event/model replay, temporal query, projection, bootstrap, or compiled integrity failed | M1 / M2.4 / M2.5 / M3.1 |
| 7 | `RESOURCE_GUARD` | Resource, budget, or concurrency guard was triggered | M2.4 |

Normal results go to stdout. Human-actionable errors go to stderr. JSON mode keeps the
machine-readable report on stdout. User-facing failures must not expose a traceback.
