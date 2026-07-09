# ADR-0003 — Append-only, versioned telemetry with a consumer-affecting marker

## Status

Accepted (founding decision; marker convention added 2026-07-05; recorded
2026-07-09).

## Context

convoy's value proposition is *measurable* execution: per-spawn economy (tokens,
turns, cost), gate outcomes, and run state must be reconstructable after the
fact — across process restarts, and by consumers convoy does not control. A
mutable or unversioned record cannot support that; neither can a protocol that
grows silently.

## Decision

- Telemetry is a JSONL ledger (`spawns.jsonl`): one event per line, only ever
  appended, stamped with `schema_version` and `run_id`.
- The event vocabulary, exit codes, and result envelopes are documented in
  `docs/design/02-formats.md` as a public protocol.
- Any addition a consumer keys on — a new process exit code, telemetry
  `outcome`/`error_kind` value, event, field, or series.toml key — is marked
  **(consumer-affecting)** in `CHANGELOG.md`, even though additive.

## Consequences

- The MCP result envelope is rebuilt from the on-disk ledger filtered by
  `run_id`, so any consumer can do the same reconstruction from the file alone.
- Additive evolution is cheap but visible: a tool driving convoy as an engine
  learns to sync from the CHANGELOG instead of silently mis-handling a new value.
- Fields are contracts: `input_tokens` deliberately folds cache reads/creation
  for cost attribution and must not be renamed or split.
