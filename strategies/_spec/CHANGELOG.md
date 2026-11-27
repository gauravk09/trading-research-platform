# Schema changelog

Every change to `schema.json` bumps `schema_version` (in the schema and in every spec that adopts it)
and adds one line here, newest first. Runs store the `schema_version` they were built from.

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-27 | First version: `must_have` (`from_source`, `from_house`), `good_to_have` (incl. `external_evaluations`), `extras`; `id` is a slug equal to the folder name. |
