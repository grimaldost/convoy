# ADR-0007 — Per-PR governance overrides with a series fallback

## Status

Accepted (2026-07-14); supersedes ADR-0005.

## Context

Under series-global governance (ADR-0005) a whole series runs at one model tier.
A plan with heterogeneous PR complexity has two options and pays for both:

- Run every PR at the highest tier any one PR needs — overpaying for the trivial
  PRs.
- Split the plan into one series per tier, hand-chaining the base and integration
  branches across the split — paying the coordination cost the split imposes.

Production use hit both costs. Calibration evidence shows systematic
over-provisioning: a series pinned to a strong tier end-to-end, every PR passing on
the first attempt, where a mixed lineup would have run most PRs cheaper. Sibling
planning tools already model per-PR tiers that the format then rejects at load — the
emitted tier is discarded, not honoured.

## Decision

A `[[prs]]` table may set its own `model`, `tier`, and `effort`. Resolution rules:

- Absent → the PR inherits `[governance]`. A PR that sets none of the three resolves
  exactly as it does today.
- A PR that sets `model` **or** `tier` supplies **both**: its `(model, tier)` pair
  replaces the series pair, which is not consulted. This is deliberate — model
  resolution prefers an explicit `model` over a `tier`, so merging the two keys
  independently would let a series `model` shadow a per-PR `tier` and silently run the
  PR on the wrong model.
- `effort` layers independently of the model/tier pair.
- Both spawns of a PR — implementation and fix — resolve the same value, so a repair
  never runs on a different model than the work it repairs.
- `[governance]` must still resolve a model even when every PR overrides it: it is the
  fallback and the audit baseline, and the pre-flight resolves it too.
- `budget`/`budgets` remain forbidden on a `[[prs]]` table — carried forward from
  ADR-0005. Budgets are per-role (`implementation`/`review`/`fix`), so a per-PR scalar
  has no role to bind to; it is a different axis, not a narrower per-PR override.

## Consequences

- The audit story gains one lookup per overriding PR (its effective governance) but
  stays static and authoring-time: the value is in the spec, visible before the run,
  and unchanged by it.
- Per-spawn `effective_model` already attributes a mixed-tier run with no schema
  change — each telemetry line names the model that spawn ran on.
- The run-summary envelope's per-PR model dimension is a separate concern from this
  ADR's governance work, and landed alongside it via the sibling readback change:
  each `prs[]` entry now carries `effective_model` (the implementation spawn's model,
  `null` if it never spawned). See the CHANGELOG [Unreleased] "per-PR model is in the
  run summary" entry and `interface/mcp/server.py`.
- The pre-flight resolves every overriding PR's governance, so an unknown per-PR tier
  fails `convoy validate` and the run pre-flight rather than mid-run — after earlier
  PRs already spent money.
- A consumer that leaned on the parser rejecting these keys to hold every PR on one
  model must now pin that itself; the engine no longer enforces it.

## Alternatives considered

1. **One-tier-per-series as the documented contract.** Rejected: it does not remove
   the cost, it relocates it to the author — who must split the plan and hand-chain the
   branches — and production paid both that cost and the overpay cost.
2. **In-run automatic escalation.** Rejected, and explicitly *not* what this enables.
   The per-PR value is authoring-time: visible in the spec before the run and unchanged
   by it. Dynamic model escalation stays cut — it fired on the wrong signal — and this
   record does not reintroduce it.
3. **Per-PR budgets.** Out of scope: budgets are a per-role axis, so a per-PR scalar
   `budget` has no role to bind to. The keys stay rejected.
