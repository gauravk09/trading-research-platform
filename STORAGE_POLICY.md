# Storage policy

`src/artifact_retention.py` is an evidence-only inventory. Its default dry run
measures configured storage areas and identifies untracked, policy-eligible
files for human review; it cannot delete, move, or compress anything.

Git-tracked files are always protected. Canonical inputs and trading/audit
records—including `data/parquet`, state, grader, paper-broker, rehearsal, and
MLflow outputs—are keep areas. The raw financial archive remains keep/review
required until a separate dedupe audit. A future cleanup decision must review a
report and use a separately approved, recoverable workflow.
