# ADR-0004 — Credential-only config isolation for scored spawns

## Status

Accepted (founding decision, recorded 2026-07-09).

## Context

convoy spawns a coding agent (`claude -p`) per PR on the operator's machine. By
default such a spawn inherits the operator's full agent configuration — hooks,
memory, skills, custom instructions. A governed run is a *measurement* (cost,
turns, gate outcomes under pinned governance); operator-local config contaminates
the measurement and makes runs non-reproducible across machines.

## Decision

Scored spawns run under **config isolation** by default: a minimal,
credential-only configuration is materialized for the spawn, so the agent
authenticates as the operator's seat but inherits none of the operator's hooks,
memory, or skills. The scored agent still receives the *workspace's* own
conventions (its agent instruction files live in the repo being worked on).
Disabling isolation is an explicit per-run choice (`--no-config-isolation` /
`config_isolation=false` / `CONVOY_NO_CONFIG_ISOLATION`).

## Consequences

- Runs are comparable across operators and machines; the economy numbers measure
  the series and the model tier, not the operator's local setup.
- The workspace remains the single channel for project conventions — which is
  where a repo's own guardrails belong anyway.
- An operator who needs local tooling inside spawns opts out loudly, and the
  telemetry of such runs is understood to be non-comparable.
