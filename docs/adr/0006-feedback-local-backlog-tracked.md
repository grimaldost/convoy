# ADR-0006 — Feedback reports are local; the backlog ledger is tracked

## Status

Accepted (2026-07-09).

## Context

convoy's improvement loop runs on dogfooding feedback: per-session reports land
in `docs/feedback/`, and periodic triage passes cluster them, verify mechanisms
against source, and promote what clears a gate. Until now the raw reports and
triage documents were committed, which put session-local reflection noise into
history, bloated PRs with material irrelevant to the change being made, and left
the *durable* state (what is promoted, what shipped) scattered across
generations of triage documents.

## Decision

- `docs/feedback/` contents are **untracked** (a `.gitignore` with `*` inside the
  directory); reports and triage passes are session artifacts that stay on the
  machine that produced them.
- The durable output of triage lives in the tracked `docs/backlog.md`: a
  status-tracked promotion ledger whose rows are self-sufficient to build from.
- Decisions promoted along the way are tracked as ADRs; invariants as guardrails.

## Consequences

- History carries decisions and the buildable backlog, not the reflection
  stream; feedback-only commits and PRs disappear.
- The evidence trail behind a ledger row does not travel with the repo — rows
  must be written to stand alone (file:line homes, the concrete change), which
  is the triage precision bar anyway.
- Reports produced before this decision remain in git history; they were removed
  from tracking, not rewritten away.
