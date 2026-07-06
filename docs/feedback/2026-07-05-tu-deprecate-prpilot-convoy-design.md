# convoy feedback — adopting convoy (design-only) while retiring pr-pilot in treasuryutils

- **Date:** 2026-07-05
- **Tool/version:** convoy 0.1.1
- **Context:** Design/authoring only — **no engine run**. In the treasuryutils repo I deprecated the
  standalone pr-pilot CLI orchestrator and adopted convoy. To decide *whether the consuming project
  needs any committed artifact for convoy*, I read convoy's `skills/convoy/SKILL.md`, `README.md`, and
  `docs/design/02-formats.md`; rewrote a `/plan-series` contributor command to drive
  `convoy_init` + series authoring; and wrote treasuryutils' ADR-0101 recording the migration. The
  MCP tools (`convoy_run`/`convoy_init`) were available but not invoked.
- **Outcome:** convoy's docs were sufficient to fully determine its artifact model and author correct
  adoption guidance without running it — with one real gap: the top adopter question ("what must an
  existing project commit to use convoy?") had to be inferred across three docs.

## What worked

- **The docs let me answer the adoption question without an engine run.** `SKILL.md` "Setup (first
  run)" + "When not to use it", `README.md`, and the `02-formats.md` `series.toml` schema together made
  it unambiguous that convoy is used by (a) having the plugin installed and (b) scaffolding a series on
  demand — enough to confidently author a `/plan-series` flow and an ADR.
- **The self-contained / series-scoped framing made the contrast with a fixture-based orchestrator
  legible.** convoy's "no references to any other tool" stance plus `convoy_init`'s scaffold model
  (`series.toml` + `prompts/` + out-of-tree oracle + git-initialized `workspace/`, `outputs` out-of-tree)
  cleanly explained why convoy needs no in-repo extension dir — the exact opposite of pr-pilot's tracked
  `.pr-pilot/` injections+hooks.
- **`02-formats.md` was precise where it mattered.** The `[[checks]]` `independent`+`asset`
  fail-closed-at-gate semantics, the phase-level-only `model`/`tier`/`effort` rule, and the required-all-
  three governance budgets/tools let me write accurate command guidance rather than hand-waving.

## Friction

- **[MED]** The single most important *adopter* question — **"what does an existing project need to
  commit to adopt convoy?"** — has no single explicit answer. I concluded "nothing: series are
  authored/scaffolded on demand with outputs out-of-tree, and project conventions reach the scored agent
  via the workspace's own `AGENTS.md`/`CLAUDE.md` through the in-workspace `claude -p` spawn" by
  triangulating README + SKILL "Setup" + `02-formats.md` `[paths]`. A team migrating from a
  fixture-based orchestrator asks this first, and the docs make them assemble the answer.
- **[LOW]** convoy's **deliberate non-features are unstated**. Coming from pr-pilot (prompt-injection
  assembly + consumer stage-hooks + reflection-journal harvesting), I had to *infer* that convoy has no
  injection surface and no consumer-hook mechanism, and that its telemetry is economy/gate — not
  reflection journals. A short "convoy deliberately does not do X" list would remove the inference.

## Misses

- None. Design-only session with no engine run — there is no executed behavior to attribute a missed
  defect to a phase.

## Vacuous gates

- None observed (no engine run).

## Proposed promotions / changes

1. **[MED]** Add an **"Adopting convoy in an existing project"** section to `SKILL.md` (and/or
   `README.md`): state explicitly that a consuming repo needs **no committed fixture** (no `.convoy/`
   analogue), that a series + its prompts are authored/scaffolded on demand with `outputs` out-of-tree,
   and that the scored agent gets project conventions from the workspace's own `AGENTS.md`/`CLAUDE.md`
   via the `claude -p` spawn — **not** from any convoy-side injection. This was the primary question a
   real migration had to answer and it was only inferable across three docs.
2. **[LOW]** Document convoy's **deliberate non-features** (no prompt-injection assembly, no
   consumer-hook / stage-transition mechanism, telemetry is economy+gate not reflection journals) so
   migrators from injection/hook-based orchestrators know up front what will not port. In this migration
   the dropped capability was pr-pilot's reflection-journal harvesting; naming convoy's non-goals would
   have made that a lookup instead of an inference.
