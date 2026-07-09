# ADR-0002 — The deterministic gate is the sole merge arbiter

## Status

Accepted (founding decision, recorded 2026-07-09).

## Context

After an agent implements a PR, something must decide whether the branch merges
onto the integration branch. That decision could come from deterministic checks
(lint, types, tests), from an LLM review, or from a mix. An LLM verdict is
non-reproducible and can be wrong in both directions; a merge decision that
depends on one cannot be audited after the fact.

## Decision

Only the deterministic `[[checks]]` gate decides a merge. Every check is a shell
command with an exit code; blocking checks red-block the merge and trigger the
bounded fix loop. The `[review]` table exists in the schema but is **reserved**:
`[review].blocking` is optional (default `false`) and the v1 headless driver runs
no LLM self-review.

## Consequences

- A gate verdict is reproducible: re-running the checks on the same tree yields
  the same answer, and the per-check pass/fail booleans in telemetry are an audit
  trail.
- Quality beyond what checks encode (design taste, spec compliance) is the spec
  author's job to encode as checks — or is out of scope for the engine.
- The reserved `[review]` table keeps the schema forward-compatible if a blocking
  self-review is ever added; making it inert-but-required was a footgun and was
  loosened in 0.1.1.
