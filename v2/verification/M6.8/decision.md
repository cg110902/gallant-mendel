# M6.8 decision

- Decision: **PASS**
- Cases: **20/20 PASS**
- Held-lock contender failed exit 7 without changing authority bytes
- Same-parent race produced exactly one winner and one explicit exit-7 conflict
- Chapter commit maps append-window contention to RESOURCE_GUARD and publishes no chapter
- EventLog and projection end at the winning event; silent overwrite is false
- Scope excludes multi-process, distributed locks, fairness, and throughput claims
