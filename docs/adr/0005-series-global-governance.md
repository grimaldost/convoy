# ADR-0005 — Series-global governance (no per-PR overrides) in v1

## Status

Accepted for v1 (founding decision, recorded 2026-07-09). **Under review** — the
mixed-tier decision is open as backlog row T5a with three arcs of production
evidence against the restriction.

## Context

Governance — model tier, effort, permission mode, per-phase budgets, tool
allow-lists — could be pinned once per series or overridden per PR. Per-PR
overrides make every PR a special case: budget parity rules, spawn wiring, and
the audit story ("what governed this run?") all fork per PR.

## Decision

In v1, governance is series-global. The spec parser rejects per-PR governance
keys outright (`model`, `tier`, `effort`, `budget`, `budgets` are forbidden on a
`[[prs]]` table), so a series has exactly one governance block to read and audit.

## Consequences

- One place to audit; spawn wiring stays uniform; budget parity checks stay
  simple.
- A plan with heterogeneous PR complexity either runs at the highest tier it
  needs (overpaying for trivial PRs) or is split into one series per tier, with
  hand-chained base/integration branches. Production use hit both costs; sibling
  planning tools model per-PR tiers the format then rejects.
- Resolution pending (T5a): either an optional per-PR `model`/`tier` override
  falling back to the series value, or the one-tier-per-series pattern becomes
  the documented contract. Whichever lands supersedes or amends this record.
