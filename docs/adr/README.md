# Architecture Decision Records

Short records of decisions with lasting consequences. Fixed four-section
template, in order: **Status** (`Accepted` / `Proposed` / `Superseded by
ADR-NNNN` / `Deprecated`), **Context**, **Decision**, **Consequences**. Optional
named sections (e.g. *Alternatives considered*) come after the four. One file per
decision: `NNNN-short-slug.md`.

Write the ADR in the same PR as the change when possible. Records 0001–0005
were written retroactively (2026-07-09) for founding decisions already shipped;
0006 records the 2026-07-09 feedback-tracking decision.

| # | Title | Status |
|---|-------|--------|
| [0001](0001-functional-core-imperative-shell.md) | Functional core / imperative shell | Accepted |
| [0002](0002-deterministic-gate-is-the-sole-merge-arbiter.md) | The deterministic gate is the sole merge arbiter | Accepted |
| [0003](0003-append-only-versioned-telemetry.md) | Append-only, versioned telemetry with a consumer-affecting marker | Accepted |
| [0004](0004-credential-only-config-isolation.md) | Credential-only config isolation for scored spawns | Accepted |
| [0005](0005-series-global-governance.md) | Series-global governance (no per-PR overrides) in v1 | Superseded by [ADR-0007](0007-per-pr-governance-overrides.md) |
| [0006](0006-feedback-local-backlog-tracked.md) | Feedback reports are local; the backlog ledger is tracked | Accepted |
| [0007](0007-per-pr-governance-overrides.md) | Per-PR governance overrides with a series fallback | Accepted |
