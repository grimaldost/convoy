# convoy — design overview

> Draft, 2026-07-03 (rev. after a blind four-reviewer panel). The founding design
> for convoy, a general-purpose tool that governs a decomposed sequence of pull
> requests to completion. Self-contained: convoy defines its own formats and
> interfaces, for general use, and references no other tool.

## 1. What convoy is

You give convoy a **series** — a set of PR-sized tasks with dependencies, a base
branch, per-phase budgets, and a quality gate. convoy drives a coding agent to
implement each PR, checks the result against the gate, repairs on failure,
integrates the branches, and records **per-spawn economy** (tokens, turns, cost,
duration) as a versioned, machine-readable trace.

Its centerpiece is not any single clever check — it is **governed, measurable
multi-PR execution**: a run is deterministic, every agent spawn is
economy-accounted, a failed matrix halts cleanly on infrastructure failure
(full auto-resume is a v2 goal — v1 keeps the checkpoint seam), and the whole
thing is legible enough for any external observer to score. That measurement
discipline is convoy's most defensible asset and the thing everything else
stands on.

Two **drivers** are planned over one **core**:

- a **headless engine** — a subprocess you fire and walk away from (`convoy run
  series.toml`); it runs the whole series and leaves an integrated working tree
  plus a telemetry file. **This is v1.**
- an **in-session driver** — the same discipline run inside an interactive agent
  session, human in the loop. **Deferred to v2** (see §6).

convoy does not make a model smarter. It targets one failure the gate can
actually catch — **merging a silent defect** — and two the *execution loop*
catches: **stopping early** and **drifting across a multi-step series**. Only the
first is a gate property; the design keeps the three claims attached to the
components that earn them.

## 2. Design principles

Ordered by how well the evidence supports them — the measurement discipline is
firm; the oracle-independence idea is a **bounded hypothesis**, deliberately not
the spine.

- **Measurable by construction.** Per-spawn economy telemetry, a versioned
  schema, append-only. Any run can be scored and compared blind. This is the
  asset that has the clearest justification and the most evidence behind it.
- **Reproducible / comparable runs.** Governance pins model, effort, permission
  mode, budgets, and tools; it never silently auto-approves and never lets a
  per-PR override smuggle in a stronger model. These are general good practices
  for any reproducible agent run, not tied to any particular consumer.
- **Functional core, imperative shell.** The decisions (DAG order, gate verdict,
  config resolution) are pure and unit-tested; the effects (spawning agents,
  running gate commands, git, filesystem checks) live in thin adapters behind
  `Protocol` ports.
- **Cut what a capable model already does.** With tests present, a strong model
  self-verifies within a session; a blocking LLM self-review adds ~nothing at
  that capability. So LLM self-review is off by default — the deterministic gate
  is the backstop, not a second opinion from the same model.
- **Oracle independence is a bounded, opt-in gate property — not the product.**
  A gate that runs the implementer's own tests can pass the implementer's own
  defective code, so an *independent* check (one the implementer did not author)
  is worth offering. But the evidence for it is narrow — one task family, a weak
  model, a confounded magnitude, and **null at the strong/default tier** — and
  "independence" enforced by asset isolation is best-effort, not a guarantee (see
  [01-gate.md](01-gate.md)). convoy therefore offers it as one optional lane with
  honest framing, and does not architect the whole product around it. Its
  promotion to a headline feature is gated on a proper interleaved replication
  that does not yet exist.

> On the evaluation this rests on: the design does not treat "a controlled
> evaluation showed X" as a settled premise. Each claim above is either a general
> engineering principle or a **stated hypothesis** the MVE will measure. Where a
> prior study informed a choice, it is cited as motivation, not proof.

## 3. Architecture map

```
                 authoring (v2)  ── emits ──▶  series.toml + prompts
                                                     │
                                                     ▼
   ┌─────────────────────────── core (pure, no I/O) ───────────────────────────┐
   │  spec (C1)   gate.decide (C2)   governance (C4)   telemetry model (C3)     │
   │  dag  (C1)                                                                 │
   └───────────────▲───────────────────────────▲──────────────────────────────┘
                   │  Protocol ports            │  (independence check is shell,
   ┌───────────────┴──────────── imperative shell (adapters) ──────────────────┐
   │  AgentSpawn (C5)   GateRunner (C2)   Git   TelemetryWriter (C3)   FsProbe  │
   │     └─ headless: subprocess `claude -p`  (v1)                              │
   └───────────────▲────────────────────────────────────────────────────────── ┘
                   │
        headless driver (C6, v1)          in-session driver (C7, v2)
```

| # | component | layer | v1? | purpose |
|---|-----------|-------|-----|---------|
| C1 | spec + dag | core | ✔ | series data model, validation, TOML round-trip, dependency ordering |
| C2 | gate | core verdict + shell runner + fs probe | ✔ | run the checks; block on a red; optional independent lane |
| C3 | telemetry | core model + shell writer | ✔ | per-spawn economy, versioned, append-only — convoy's own format |
| C4 | governance | core | ✔ | resolve + pin model/effort/permission/budget/tools; enforce parity |
| C5 | agent-spawn port | shell (Protocol) | ✔ | "run an agent against a brief → result + economy"; headless impl |
| C6 | headless driver | shell | ✔ | the `run series.toml` engine; the MVE lands here |
| C7 | in-session driver | shell/skill | v2 | same core via harness subagents, human in the loop |
| C8 | authoring | core lib + CLI | v2 | score complexity → decompose → emit series + prompts |

## 4. Repo layout (application layout, src)

```
convoy/
  pyproject.toml            # dist: convoy-engine · import: convoy · scripts: convoy, cvy
  src/convoy/
    core/                   # pure — no I/O, fully unit-testable
      spec.py               # C1 series model + validation + TOML round-trip
      dag.py                # C1 phase/depends_on ordering
      gate.py               # C2 verdict logic (pure) — receives check + independence
      governance.py         # C4 config resolution + parity enforcement
      telemetry.py          # C3 event schema + economy materialization (pure)
    interface/              # imperative shell — adapters behind ports
      cli.py                # typer app: run, validate, init
      spawn.py              # C5 AgentSpawn Protocol + headless impl
      gate_runner.py        # C2 shell: executes check commands
      fs_probe.py           # C2 shell: independence/isolation checks (filesystem)
      git.py                # stage / branch / integrate
      telemetry_writer.py   # C3 append-only JSONL writer
      drivers/
        headless.py         # C6
  tests/                    # top-level only — never inside src/
```

`core/` imports nothing from `interface/`. All I/O — including the independence
/ isolation check (a filesystem probe) — is shell; the pure `gate.decide`
receives independence *as data*, never computes it. **Tooling:** Python 3.14 /
uv / ruff / ty, single-quote code, `typer` CLI, `pydantic-settings`, `structlog`
(right-sized), `pytest` + `hypothesis` + snapshot tests, PEP 735 groups. Dist
`convoy-engine`; import and CLI `convoy` (+ `cvy` alias).

## 5. Component designs (summaries; C2 has its own doc)

- **C1 spec + dag** — convoy's own series schema (general-purpose, self-documenting,
  versioned): `[series]`, `[branches]`, `[paths]` (absolute), `[governance]`
  (per-phase model/effort/permission/budget/tools), `[[checks]]` (the gate — each
  a `name` / `run` / `blocking`, plus an optional `independent = true` marker),
  `[[prs]]` (id, branch, prompt, phase, depends_on). Plain TOML value types so a
  machine-regenerated spec round-trips. `dag` orders PRs by phase + `depends_on`
  and detects cycles. Pure; property-tested.
- **C2 gate** — [01-gate.md](01-gate.md). A set of `[[checks]]`; a blocking red
  blocks the merge, **full stop** (a red is a red). An optional `independent`
  marker records provenance for telemetry and to decide *auto-fix vs. surface* —
  it never downgrades a red's merge-blocking. Fail-**loud** when a blocking check
  is red; never a green exit over a red.
- **C3 telemetry** — convoy's own append-only JSON-lines format: one
  `spawn_complete` event per agent spawn, carrying `run_id`, `pr_id`, `role`
  (implementation/review/fix), `exit_code`, `input_tokens`, `output_tokens`,
  `num_turns`, `duration_s`, `cost_usd`, `effective_model`, and a top-level
  `schema_version`. **Per-spawn granularity is a hard requirement** — a
  run-total-only file cannot be economy-joined by any observer. The schema is a
  versioned public contract: fields are added, never renamed or repurposed.
- **C4 governance** — a pure function resolving raw config into pinned per-phase
  governance, enforcing the reproducibility rules: overridable
  model/effort/permission/budget/tools; **never** forces an auto-approve
  permission mode; **per-PR model/effort overrides stripped** (measure the
  strategy, not a silently stronger model). Model/effort is a **phase-level**
  value — there is no per-PR runtime model field, so authoring-time and runtime
  cannot disagree about which model runs a PR. The fix loop reuses the pinned
  per-phase model; it never re-introduces a per-PR or stronger model.
- **C5 agent-spawn port** — one `Protocol`:
  `spawn(brief, model, effort, permission, budget, tools) -> SpawnResult`
  returning the agent's result plus its economy. v1 ships the **headless** impl
  (subprocess `claude -p` under an isolated `CLAUDE_CONFIG_DIR`). This impl is
  **reimplemented from scratch** but to a set of named, non-optional invariants
  (see §6 note): credential-only config isolation, env-strip of billing/routing
  vars, **whole-process-tree kill** on timeout on both Windows (`taskkill /F /T`)
  and POSIX (`killpg`) — using `Popen` not a naive `run`, whose timeout orphans
  the CLI's tool grandchildren into the scored tree — partial-stream economy
  recovery, and transient/auth/usage failure classification. A **fake** impl
  drives all tests without a real agent.
- **C6 headless driver** — the run loop: stage on base → order the DAG → per PR
  spawn implementation → run the gate → on a red, run the bounded fix loop →
  integrate onto the integration branch → leave the integrated tree checked out
  + write telemetry. Classifies infrastructure failure (auth/quota/retry) apart
  from task failure so a matrix halts cleanly and resumes. **The two drivers do
  not share one loop** — C6 owns its loop; the shared core is the pure leaves
  (`spec`, `dag`, `gate.decide`, `governance`, `telemetry` model) plus the step
  primitives (spawn-one, gate-one, integrate-one). C7 (v2) will own its own loop
  with human checkpoints, calling the same primitives. `convoy run` narrates
  progress to **stderr** via an injectable reporter (silenced with `--quiet`),
  keeping **stdout** machine-clean; alongside `run`, the CLI also offers `convoy
  validate` (structure + pre-flight, no run) and `convoy init` (scaffold a runnable
  starter series).
- **C7 in-session driver (v2)** — a Claude Code *skill* (a playbook the main
  agent follows) that calls the same core library and the `convoy gate` CLI, with
  human checkpoints. It is a skill, not a second `AgentSpawn` implementation —
  the harness agent decides when to spawn; convoy contributes the core + gate.
  Before building it, verify the harness actually exposes per-spawn economy; if
  not, its telemetry rows are marked `economy: estimated` so an observer can
  exclude them.
- **C8 authoring (v2)** — score complexity against a rubric (as code) → choose
  the cheapest sufficient model/effort per **phase** → decompose into a series →
  emit `series.toml` + prompts.

## 6. Build order — vertical slice → MVE → thicken

v1 is the **headless engine that proves governed, measured execution on
hand-written series**. Everything that assumes the differentiator, or adds a
second surface, is v2.

1. **Core foundation:** `spec` (minimal) + `telemetry` (schema + writer) +
   `AgentSpawn` Protocol + a fake spawn.
2. **Gate (minimal):** `[[checks]]` run, a blocking red blocks, fail-loud.
3. **MVE:** the headless driver running a hand-written series — one PR, one
   implementation spawn, one gate, per-spawn telemetry, correct exit code. The
   first end-to-end proof and the de-risking milestone.
4. **Thicken v1:** full governance parity → the `depends_on` DAG → bounded fix
   loop → the optional `independent` lane (best-effort isolation + honest
   reporting).
5. **v2:** in-session driver (C7), authoring (C8), and — only if a proper
   interleaved replication justifies it — deeper independent-lane machinery.

> **Spawn-core note:** the C5 headless impl is written from scratch but to the
> invariants listed in §5. These invariants are non-optional (tree-kill protects
> the scored tree; isolation protects billing/routing). They are treated as a
> specification to meet, learned from proven prior art, not as robustness to
> defer.

## 7. Testing strategy

- **Core** — pure unit tests; `hypothesis` property tests for spec round-trip,
  DAG ordering (a valid order respects every `depends_on`), and governance parity
  (no resolution yields an auto-approve permission or a per-PR model override).
- **Gate** — mutation testing as a **wiring / regression** check: seed known
  defect classes into a fixture and assert each check catches what it should,
  with an explicit per-check baseline (which seeded class it MUST catch and, for
  an independent check, which the suite MUST miss) so the test discriminates
  instead of ceilinging out. This validates the plumbing, not the thesis —
  thesis validation is an external, blind, interleaved replication, not convoy's
  own fixture.
- **Drivers** — the fake `AgentSpawn` makes the headless loop fully deterministic.
- **Dogfood** — convoy's CI gate includes at least one independent check over
  convoy itself.

## 8. Cut / deferred

- **In-session driver (C7) and authoring (C8)** — v2. v1 is headless-only.
- **The provenance × lane matrix** — cut. One boolean `independent` per check,
  not a 2×4 taxonomy; lane labels, if any, are free-form telemetry tags.
- **Escape telemetry ("the gate improves over time")** — an untested research
  direction, not a v1 mechanism: the walk-away flow has no downstream escape
  signal to feed it. Behind a flag at most.
- **Dynamic model escalation** — cut (it fired on the wrong signal).
- **Blocking LLM self-review** — off by default; a governance knob.
- **Parallelism, per-PR model routing, hung-spawn watchdog** — deferred (tree-kill
  on timeout, which protects the scored tree, is **not** the watchdog and is in
  v1).

## 9. Open decisions (fresh eyes wanted; none blocks the MVE)

1. **Independence contract — asset vs. input.** Isolating the check's *asset*
   (out-of-tree, non-writable) does not stop it reading in-tree inputs or
   importing the implementer's module. Decide what convoy guarantees and name it
   honestly ("workspace isolation of oracle assets", best-effort), rather than
   implying enforced epistemic independence. Covered in [01-gate.md](01-gate.md).
2. **Independence asset home** — an out-of-tree absolute path is unportable and
   doesn't commit/travel. Prefer a committable convention (e.g. an `oracles/`
   dir mounted read-only and excluded from the implementer's write allow-list),
   enforcing "implementer can't reach it" by permission, not by absolute path.
3. **Low-independence merge semantics** — a series with only implementer checks
   must still fail loud on a blocking red (never a green exit over a red). The
   `independent` marker changes *auto-fix vs. surface*, never *may-we-merge*.
   *Recommend:* a red always blocks; independence only gates the repair path.
4. **One-command on-ramp** — first value should not require authoring an
   independent check. *Recommend:* a small library of ready-made, generic
   independent checks (by defect class) a user opts into by name — real
   independence at command one, and the concrete authoring exemplar.

These are the decisions I'd most want challenged next. None blocks the vertical
slice.
