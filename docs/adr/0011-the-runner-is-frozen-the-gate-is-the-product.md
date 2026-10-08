# ADR-0011 — The runner is frozen; the gate is the product

## Status

**Accepted** (2026-10-08), on the owner's written decision of that date. It was proposed the
same day; the decision settled the two choices the proposal left open (whether to enforce the
freeze with a check, and whether rows that retire parts of the runner are excepted) and added
the Workflow recipe, the retirement precondition and the home of the private-names sweep.

It narrows [ADR-0009](0009-thin-governed-layer-position-deferred.md) and does not
supersede it; see the fourth item under Context.

## Context

**1. The gate's measured benefit is the per-PR gate, on one defect class.** CONV-B53 in
`docs/backlog.md` records the only comparison that composed convoy partially with an
orchestrator that is not convoy: "Measured, 2026-09-03 (iteration 1; 128 trials on the
0.11.0 standalone gate". Four arms (control, a ceremony placebo, the gate after each PR
with the envelope's `repair_brief` handed to a fix subagent, and the gate once after the
session with a bounded fix loop), at Haiku and Sonnet implementer tiers under a Sonnet
orchestrator, n = 16 per cell, held-out-clean as the primary endpoint. The backlog gives
each arm as a pair, Haiku then Sonnet:

| Arm | Held-out-clean, Haiku and Sonnet |
|---|---|
| gate after each PR | 16/16 and 14/16 |
| control (the project's own suite only) | 4/16 and 2/16 |
| placebo | 6/16 and 5/16 |
| gate once after the session | 12/16 and 9/16 |

It also gives the cost per trial as +20% to +25%, and the cost per correct trial as "a
third (Haiku) to a sixth (Sonnet) of control's". The caveats it states travel with the
numbers. The endpoint is one defect class, the type rule the briefs withheld, so the result
is the gate restoring a withheld rule through a repair brief consumed by a fresh subagent,
and not benefit on work independent of the rule it teaches. The placebo does not match the
repair actor or the brief's content. Four counted trials reached the task directory before
a harness repair and are retained with the sensitivity. The post-session form is not the
feature to sell. Iteration 2, which measures the 0.12.0 hook, needs a held-out group with a
second defect class before it can claim more. No arm drove a run with `convoy run`: the
orchestrator was external, so the runner was not measured. The row also records the session
that motivated it, which rejected the runner on its merits, discarded the gate with it, and
shipped 11 externally orchestrated PRs verified only by the agents that implemented them.
The doctrine the measurement supports is stated, with its limits, in
`docs/authoring-series.md` §Gate granularity (CONV-B69).

**2. The hook fires for agents the Workflow tool starts, with one caveat.** The dated
note [2026-10-08-subagentstop-under-workflow.md](../notes/2026-10-08-subagentstop-under-workflow.md)
records a probe: `SubagentStop` fired for agents the Workflow tool started, with and without
worktree isolation; a `[convoy-phase: <tag>]` marker in the `agent()` prompt reached the
judge; and the judge ran the gate. The caveat is
[CONV-B75](../backlog.md#conv-b75--a-worktree-isolated-subagent-is-judged-against-the-main-checkout-not-the-worktree-that-holds-its-changes)
(proposed, not built): a worktree-isolated agent is judged against the main checkout, not the
worktree that holds its changes, because gate discovery tries
`$CLAUDE_PROJECT_DIR/.convoy/gate.toml` before the walk up from the payload `cwd`. The note
observed this with an untracked spec and reads the committed case from the code. The probe's
agents wrote one file each and both gates were green; no red was observed. It was a probe,
not a run of a gate recipe: no Workflow script dispatched a series of agents and acted on
the judge's verdicts.

**3. The runner has not driven a wave since 2026-09-26.** This is a finding of a review on
2026-10-07. It is not recorded elsewhere in this repository: the latest run the backlog
draws on is the three-PR run of 2026-09-26, the only input of the 2026-10-06 triage
(`docs/backlog.md`, header), and nothing in `docs/backlog.md`, `CHANGELOG.md` or the README
says whether a later run happened. This record treats it as the owner's statement, not as a
fact the repository can confirm.

**4. ADR-0009 deferred the position and said the engine is not frozen.** ADR-0009 accepted
a deferral of the thin-governed-layer position on the cost of measuring it, kept the
position as a hypothesis, and ended its Decision with "Deferring the position does not
freeze the engine." It records a comparison priced at about $152 and calls buying it "a
purchase decision, not a scheduling one". The residue it wants measured bundles the gate
with the repair loop, branch-per-PR integration with resume, and the ledger. The gate is
the only one of those that fact 1 measures; the others are runner behaviour, and fact 3
says the runner has not been in use. This record does not adopt or reject the position and
does not touch the deferral. It narrows one sentence: for the runner, the engine is now
frozen. Everything else in ADR-0009 stands, including the quarantine of the 9/10 figure and
the rule that a successor which adopts or rejects the position records the reading it
names first.

A paid measurement of the runner against hand-run dispatch, proposed outside this
repository and priced at US$152, is the comparison ADR-0009 priced. This record declines it
for good. No reason is given beyond the decision itself.

## Decision

**The runner is frozen. The gate is the product.**

- **Frozen:** `convoy run` and `convoy_run`, the headless driver, the spawn adapter, the
  seat probe, detached runs, and the run telemetry. A new field, option, advisory, default
  or behaviour is not a fix and does not land there. Three kinds of change are excepted:
  - a security fix;
  - a fix for a defect that corrupts data or a workspace;
  - a backlog row that retires part of the runner.

  A floor model id the platform retires is a defect in a frozen part and takes a fix. The
  move of the built-in floor lineup to the 5.5 models (the `[Unreleased]` entry in
  `CHANGELOG.md` for CONV-B14) is that case.
- **Developed:** `convoy gate`, `convoy hook` with the trust check that guards what it
  executes, the gate spec, the trust list, and the gate-only file shape (a `[series]` id
  plus `[[checks]]`, accepted without a full series).
- **The gate recipe lives in a native Workflow**, a script for the harness's Workflow tool.
  `convoy gate`, armed by a `.convoy/gate.toml` whose hash is pinned on the trust list, is
  one possible judge in it.
- **The private-names sweep belongs in CI**, not in the gate recipe.
- **Declined for good:** the US$152 measurement described above.
- **Retirement has one precondition and no date.** The runner is retired only after an
  end-to-end run in which the judge fires for agents a Workflow recipe starts. That run is
  a precondition, not a trigger: it permits a retirement and does not schedule one. The
  2026-10-08 probe (fact 2) showed the hook firing for Workflow agents in a probe; it is not
  that run. Until a retirement, the frozen runner stays installed, documented and tested;
  the freeze limits what is added to it, not what it does.

## Consequences

- **The freeze is stated in text only.** No CI check enforces it; review does. Each waiting
  or excepted row below carries a one-line status pointing here.
- **Backlog rows that extend the runner wait for the next phase.** Open on the default
  branch on 2026-10-08, read from the Now, Next and Later sections of `docs/backlog.md` and
  its watch table:
  - run lifecycle and driver: CONV-B10, CONV-B16, CONV-B21, CONV-B26, CONV-B43, CONV-B44;
  - what a spawn is told or allowed: CONV-B12, CONV-B22, CONV-B23, CONV-B37;
  - seat probe: CONV-B41 (partly shipped; the rest waits);
  - the scaffold that writes a run series: CONV-B11; the series-file path detectors that
    CONV-B11 would retire: CONV-B24;
  - run telemetry: advisory counts, CONV-B20; the stream-vocabulary marker, CONV-B46, whose
    trigger is a change to the run stream and which gates CONV-B43(b);
  - watch rows that name the driver, the run telemetry, the reporter, the seat probe or the
    scaffold: T3a, T4b, T6a, T6b, T15c, T17, T18, T54b, T60b, T66b, T68a.

  T67a is no longer among them: it shipped as CONV-B73 in 0.17.0.
- **Rows that retire parts of the runner are excepted** and may land during the freeze:
  CONV-B30 (the reserved `[review]` lane), CONV-B33 (the per-model seat-probe fan-out and
  the `effective_model` folding), CONV-B34 (the credential-copy isolation), CONV-B35 (the
  hand-rolled stream parser), and the two measurements that gate them, CONV-B18 (for
  CONV-B33) and CONV-B19 (for CONV-B34).
- **Rows for the owner to classify.** CONV-B38, CONV-B39, CONV-B40, T54a, T64a and T64b
  touch the gate and the run loop or the series file both. CONV-B16 and CONV-B44 wait as
  listed, but may be defects that corrupt a workspace (telemetry left dangling after
  `run_start`; a branch deleted that corrected checks pass on) and so fall inside the
  exception. This record does not decide them.
- **Gate rows continue and are unaffected:** CONV-B53 (iteration 2), CONV-B60, CONV-B63,
  CONV-B68, CONV-B32, CONV-B75 once a fix is chosen, and the watch rows T61b and T62b.
- **The private-names sweep is not built here.** A CI sweep needs the list of names as a
  repository secret, which only the owner can set.
- **The front-door docs say which half is developed:** `AGENTS.md`, `README.md` and
  `skills/convoy/SKILL.md` each link here, and ADR-0009 carries a one-line pointer.
- **What reopens this decision is the next phase's design** of convoy as an envelope for
  different executors and models. That design decides which frozen parts it builds on, and
  it supersedes or closes this record. A retirement of the runner, after the end-to-end run
  named above, closes it too.

## Alternatives considered

1. **Retire the runner now.** Not chosen. Facts 1 and 3 show that the gate has the
   evidence and the runner has no recent use, but neither is a measurement that the runner
   is unneeded, the next phase may reuse the driver, the spawn adapter or the telemetry for
   other executors, and the end-to-end run in which the judge fires for Workflow agents has
   not happened. Removal is expensive to undo; a freeze is not.
2. **Keep both developed.** Not chosen. It spends maintenance on a surface the
   2026-10-07 review found idle, alongside a gate whose benefit is measured and whose firing
   under another orchestrator is observed.
3. **Buy the measurement first.** Not chosen: declined for good at US$152. ADR-0009 already
   records that a paid comparison at that price is a purchase decision and not a
   scheduling one.
4. **Enforce the freeze with a check**, for instance a test that fails when a change
   touches the frozen modules without a marker naming the exception. Not chosen: the owner
   chose text only.
5. **Run the private-names sweep in the gate recipe.** Not chosen: the owner placed it in
   CI.
