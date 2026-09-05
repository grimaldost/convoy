# ADR-0010 — The artefact carries the lineup; the built-in table is a floor

- Status: accepted
- Date: 2026-09-05
- Supersedes nothing. Extends ADR-0005 (series-global governance) and ADR-0007
  (per-PR governance overrides) without reopening either.

## Context

`DEFAULT_TIER_MODELS` maps `weak`/`mid`/`strong`/`frontier` to model ids. Those ids
are owned somewhere else — by whatever routing policy an operator maintains — and
convoy has no way to reach it. The charter is why: this repository has to install and
run for a stranger who has never heard of that policy, so it carries a copy rather
than a reference (`docs/GUARDRAILS.md`, "The repo stays self-contained").

A copy is the right answer to that constraint. What was wrong is what the copy *did*.
It was the resolution path: a series that said `tier = "strong"` got whatever this
build happened to ship, and the run recorded no trace of that. Measured on
2026-09-05: the table named `claude-fable-5` after `claude-fable-5-1` had been current
for weeks, and nothing in convoy could have said so. Every artefact and every
telemetry line of such a run is identical to one that resolved from the file.

The obvious alternatives were considered and rejected before this one:

- **Import a package, or read a file the policy writes.** Both break the charter
  outright, and CONV-B14 had already settled it in writing: self-containment "is
  exactly why the freshness discipline has to be reproduced locally rather than
  inherited by reference."
- **Read the harness's installed-plugin registry at run time.** A private, versioned
  file of another tool, and a dependency wearing a generic path instead of a name.
- **Keep the copy and date it.** Necessary, not sufficient. A date measures
  maintenance, not drift: on 2026-09-05 both freshness tripwires upstream were green
  while the lineup was stale.

## Decision

**The lineup travels inside the run's own artefact.** `[governance.tier_models]` is
an optional table on the series file, resolved by whoever authored the run and written
into it. Resolution order, strongest first:

1. an explicit `model` (on the PR, else on `[governance]`);
2. a `tier_models` table injected by the caller — the operator and test seam;
3. `[governance.tier_models]`, the table this series carries;
4. `DEFAULT_TIER_MODELS`, the built-in **floor**.

Three consequences make it a decision rather than a feature.

**The floor announces itself.** Any tier resolved at step 4 raises an
`Advisory(kind='lineup')` naming the model and the table's `LINEUP_RECONCILED` date.
Advisory, not Problem: refusing to run would strand exactly the operator the floor
exists for. It rides `run_start` like every other advisory, so the fact is
reconstructible from the ledger alone.

**The floor's stamp is the upstream reconciliation date, never the commit date.**
Dating the edit would let a table copied from an already-stale source certify itself
fresh, and an age check would then be measuring the stamp rather than the lineup.

**An unknown key under `[governance]` is rejected.** Without that, a series carrying
`tier_models` would have loaded on an older convoy, had the key dropped, and run every
PR on the floor — the exact silent-wrong-run this ADR exists to prevent, reintroduced
by the fix for it. It shipped first, in its own release.

## Consequences

- A run is reproducible from its own file. Nothing about which model executed depends
  on which convoy build resolved it, unless the file declined to say — and then the
  run says so.
- `implementation_model_sources` gains a third element, the origin
  (`explicit` / `series-table` / `floor`). `where` says which section of the file
  chose the model; origin says whether the file chose it at all.
- `dump_series` is taught the field. It builds the governance table key by key, so an
  untaught field is dropped — and any read-modify-write would erase the lineup the
  artefact carried, silently.
- The floor stays, is still maintained, and is still walked by whoever owns the
  upstream data. It is not deprecated: a stranger's series with a bare `tier` is a
  supported, first-class case. It simply stops being the thing that quietly decides.
- ADR-0005's guarantee is untouched and, if anything, strengthened: governance is
  authoring-time and static, and now the lineup is too.
