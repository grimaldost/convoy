# ADR-0008 — Phase-scoped checks, and a non-blocking advisory channel

## Status

Accepted (2026-07-25). Narrows the series-global gate scope stated in
[02-formats.md](../design/02-formats.md); does not touch the merge contract of
[ADR-0002](0002-deterministic-gate-is-the-sole-merge-arbiter.md).

## Context

The gate ran the whole `[[checks]]` tuple after **every** PR. For a series whose
PR1 lands a core slice and PR2–PR4 extend it, the full-suite gate is red until the
last PR, so PR1 cannot pass its own gate. An incremental series is therefore
unrunnable, and an author has two options:

- Collapse the plan into one fat PR — discarding the decomposition convoy exists to
  execute.
- Require every PR to be full-suite green — which is the same constraint by another
  name, and forces speculative stubs into early PRs.

Both defeat `depends_on`. A dependency DAG whose only workable shape is one node is
not a DAG, so the engine's headline feature had no incremental use case. This was
found empirically: a measurement campaign that intended to exercise decomposition
had to fall back to one-PR series, leaving the feature untested.

The join key already existed. `[[prs]].phase` has been parsed and serialized since
v1 and read by nothing — a declared-but-inert field.

## Decision

**A check may declare the phases it gates.** `[[checks]].phases` is a list of
`[[prs]].phase` tags; `core.gate.checks_for` selects a PR's checks.

- **Empty means every PR.** The default is the previous series-global behaviour, so a
  series that sets `phases` nowhere is bit-for-bit unchanged.
- **Scoping narrows which checks run, never what a red means.** Whatever is selected
  is judged under the existing rules — a blocking red still blocks, `independent_red`
  still routes the repair. ADR-0002 is untouched.
- **A PR's checks resolve once and the fix re-gate reuses them**, so a repair is judged
  by exactly the checks that failed it.
- **A phase tag no PR declares is a pre-flight Problem.** A typo would silently reduce
  a check to gating nothing, and a check that never runs is worse than a missing one
  because the series still looks gated.
- **A PR that no blocking check gates is allowed, and reported.** It integrates
  unverified. That is a legitimate authoring choice (a docs-only PR), so it does not
  block — but it is silent and expensive to discover afterwards.

The last point needs somewhere to put a non-fatal remark, and pre-flight had no such
place: every `Problem` is fatal, and both surfaces treat a non-empty list as failure.
So this ADR also introduces **`Advisory`**, a located non-blocking remark, and
`PreflightReport` carrying `problems` and `advisories` side by side. Only `problems`
decides runnability. `Advisory` is a distinct type rather than a severity field on
`Problem`, so no surface can turn advice into a failure — or lose a failure among
advice — by accident.

## Consequences

- **Two consumer-affecting additions**: the `phases` series.toml key, and an
  `advisories` list in the `convoy_run(dry_run=true)` envelope. Both are additive. An
  older engine rejects a series that sets `phases`; a consumer reading the dry-run
  envelope sees a new key that never affects `ok` or `outcome`.
- **`convoy validate` can now print to stderr and still exit 0.** A caller that treated
  *any* stderr output as failure must key on the exit code instead. This is the one
  behavioural break for an existing consumer.
- **`[[prs]].phase` stops being inert.** It was a free-form grouping tag with no
  engine meaning; it is now load-bearing, and a phase rename changes which checks run.
  The two meanings of "phase" in the format — the governance *role*
  (`implementation`/`review`/`fix`) and this DAG grouping tag — remain unrelated, and
  the distinction matters more now that one of them does something.
- **The advisory channel has one producer today** (the ungated-PR remark) and is built
  to carry more; a pre-flight remark that should not stop a run now has a home instead
  of being dropped or over-promoted to a Problem.
- **Gate scope becomes a thing an author can get wrong in a new way** — scoping too
  narrowly silently reduces coverage. The unknown-tag Problem catches the typo case;
  the ungated-PR Advisory catches the coverage case. Neither catches a check scoped to
  the wrong existing phase, which stays an authoring concern.

## Alternatives considered

1. **Per-PR scoping (`prs = ["pr-1"]`) instead of per-phase.** Rejected: it couples
   the gate to PR ids, so adding a PR means editing every check that should cover it.
   Phases already group PRs and the tag already exists. Per-PR remains addable later as
   a narrower axis if a real need appears; per-phase does not preclude it.
2. **Make an ungated PR a pre-flight Problem.** Rejected: it is a legitimate authoring
   choice, and refusing to run a valid series to protect the author from their own
   decomposition is the kind of paternalism that makes a tool unusable for the case its
   author actually has. The advisory makes the consequence visible without taking the
   decision.
3. **A severity field on `Problem` instead of a separate `Advisory` type.** Rejected:
   every existing call site treats a `Problem` as fatal, so a severity field makes
   correctness depend on every present and future site remembering to filter. A
   distinct type makes the mistake unrepresentable.
4. **A terminal/final check phase (run once after the last PR integrates).** Deferred,
   not rejected — a whole-series invariant that cannot hold mid-series is a real need,
   but it needs a new position in the run loop rather than a selection rule, so it is a
   distinct mechanism. Tracked as backlog row T19b.
