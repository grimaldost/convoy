---
description: >-
  Drive convoy's `convoy_run` and `convoy_init` MCP tools to execute a governed multi-PR
  series — decompose work into dependency-ordered PR-sized tasks, run a coding agent through
  each under a per-phase budget, gate each result against a quality check, repair on a
  failing gate, integrate the green branches, and read back a structured per-spawn economy
  plus gate summary. Use when running a convoy series.toml, when scaffolding one with
  `convoy_init`, when a job needs several PR-sized steps executed and measured under budget
  behind a quality gate, or when someone asks to run a governed or measured multi-PR
  execution. Not for a single quick edit or one-shot task — that is a direct agent turn; not
  for interactive human-in-the-loop PR review — that is the normal Claude Code workflow; not
  for deciding what to build or writing the spec — convoy runs a series you already have.
---

# convoy

convoy runs a **governed, measurable multi-PR series**. You give it a series
(PR-sized tasks with dependencies, a base branch, per-phase budgets, and a
quality gate); it drives a coding agent to implement each PR in dependency order
under budget, gates the result against the series' checks, repairs on a blocking
failure, integrates the green branches, and records **per-spawn economy** (tokens,
turns, cost, duration) as an append-only, versioned trace. It is headless —
fire-and-walk-away, no human checkpoints.

The plugin exposes two MCP tools:

- **`convoy_run`** — run a series (or, with `dry_run`, pre-flight it for free).
- **`convoy_init`** — scaffold a runnable starter series to adapt or smoke-test.

A run **spends real model budget** and takes minutes to hours — it spawns a
subprocess `claude -p` per PR. Always `dry_run` first (free, no side effects),
then drop it for the real run.

## Arguments

### `convoy_run`

- `series_file` (required) — absolute path to the series.toml to run.
- `workspace` (required) — absolute path to the git repository to operate in (the
  scored tree). The series is staged on its base branch here; each PR's branch and
  the integration branch are created in this repo. It must be an existing git repo
  whose current/base branch matches the series' `[branches].base`.
- `dry_run` (default `false`) — when `true`, only pre-flight the series (structure,
  model resolution, paths, gate isolation) and return `{ok, outcome, problems}`. No
  git mutation, no agent spawn, no spend. Do this before every real run.
- `config_isolation` (default `true`) — run the scored agent under a credential-only
  `CLAUDE_CONFIG_DIR` so the operator's settings, hooks, plugins, and memory never
  leak into the run. Internally convoy makes a fresh temp config dir per run, copies
  **only** your Claude credential into it (so auth still works), and removes it when the
  run ends. Turn it off only to deliberately run under your full operator config dir
  unchanged.
- `reset` (default `false`) — opt-in workspace reset before staging: check out `base` and
  delete the `integration` branch and every PR branch the series names — so a completed or
  halted run can be re-run without a "branch already exists" failure. The reset touches
  branches only; it does **not** discard uncommitted changes or untracked files (see
  "Limits and re-runs"). Off by default: a leftover branch still fails loud exactly as
  without the flag. CLI equivalent: `convoy run --fresh`.

Traps the pre-flight catches (so `dry_run` reports them instead of a half-run):
`[paths]` that don't resolve to an existing prompts dir or that name missing prompt
files (note: absoluteness itself is not checked — a relative path resolves against the
engine's working directory, so use absolute paths); an `outputs` dir
**inside** the workspace (telemetry writes would dirty the git tree and abort a
checkout — keep it out-of-tree); a blocking independent check whose `asset` is
in-tree (isolation fails closed); and a governance block that resolves to neither a
`model` nor a known `tier`.

### `convoy_init`

- `directory` (required) — where to scaffold the starter series. Must not already
  contain the starter files; it refuses to overwrite rather than clobber.

## What comes back

Every tool returns a single JSON object.

**`convoy_run`, real run** — the run summary, aggregated from telemetry:

- `ok` (bool) — `true` only when `outcome` is `completed`.
- `outcome` — `completed` (every PR gated green and integrated), `blocked` (a blocking
  check stayed red after the fix loop), `infrastructure` (an auth / quota / retry / timeout
  halt — re-runnable), or `budget` (a spawn hit its budget cap; its partial work is not
  integrated).
- `integrated` (bool) — whether the **whole series'** work reached the integration branch
  (`true` only with outcome `completed`). After a mid-series halt this is `false` even
  though the PRs already gated green remain merged on the integration branch.
- `exit_code` — `0` completed · `1` blocked · `2` infrastructure · `3` usage · `4` budget.
- `run_id`, `series_id` — run identity.
- `economy` — `{ total_cost_usd, cost_estimated, input_tokens, output_tokens,
  num_turns, spawn_count }`. The token counts and `num_turns` are **summed across every
  spawn** in the run; `spawn_count` is how many spawns ran. `cost_estimated` is `true` if
  any spawn's cost was substituted from a token estimate (the provider reported `0.0`),
  making `total_cost_usd` approximate. Per-spawn `duration` is not summarized here — it is
  in the telemetry trace.
- `prs` — one entry per PR, in processing order: `{ pr_id, spawns, effective_model, gate,
  skipped, skip_reason }`. `gate` is `null` if the PR never gated, else `{ attempt,
  blocking_red, independent_red, failing_checks }` for the **latest** attempt
  (`failing_checks` lists the names of the blocking checks that were red). `attempt` is
  `0` for the initial gate and `1..N` after each fix re-gate; `blocking_red` and
  `independent_red` are booleans. A PR halted-past has `skipped: true` and a `skip_reason`.
  `spawns` is the **count** of agent spawns for that PR. `effective_model` is the model the
  PR's **implementation** spawn actually ran under, and is `null` if the PR never spawned
  (skipped). A PR's spawns normally share one model; on the rare divergence — a fix spawn
  served a different model than the implementation spawn — this reports the implementation
  spawn's, with the per-spawn breakdown in `telemetry_path`. The list is capped at 50 PRs;
  overflow is reported in `truncated`.
- `telemetry_path` — the append-only `spawns.jsonl` on disk. The **complete**
  per-line trace (every spawn, every gate attempt, every skip) lives here; read it
  for detail the summary caps or collapses — the per-spawn model and cost breakdown behind
  a PR's folded `effective_model`, for one. Each line is a JSON object tagged with
  `schema_version` and `event` (`run_start` / `spawn_complete` / `gate_complete` /
  `pr_skipped` / `run_complete`). A `spawn_complete` line carries `run_id`, `pr_id`, `role`
  (`implementation` / `fix`), `exit_code`, `input_tokens`, `output_tokens`, `num_turns`,
  `duration_s`, `cost_usd`, `effective_model`, `cost_estimated`; the full telemetry contract
  is in `docs/design/02-formats.md`.
- `truncated` — `{ any, prs }`: how many PRs the `prs` list dropped past its cap. If
  `any` is `true`, read `telemetry_path` for the full set.

**`convoy_run`, `dry_run: true`** — `{ ok, outcome, series_id, problems }`, where
`outcome` is `validated` (clean, `ok: true`) or `usage` (problems found, `ok:
false`), and `problems` is a list of `{ kind, where, message }` (empty when clean; `kind`
is one of `governance`, `dag`, `paths`, `prompt`, `isolation`, and `where` locates the
offending section or entry, e.g. `[[prs]] 'pr-2'`).

**`convoy_run`, could-not-start** — a real run returns this same `outcome: "usage"`
(`ok: false`) shape if it cannot start, never a raised exception. It carries `problems` (a
located `{ kind, where, message }` list, same as `dry_run`) for a structure or pre-flight
failure, or `error` (a message string) with an `error_kind` (`spec` | `governance` | `git`
| `busy` | `filesystem`) for an unreadable / invalid spec, a runtime git / filesystem
failure, or another run holding the workspace lock (`busy`). So
`usage` is the one `outcome` a real-run call can return **besides** the four engine outcomes
above.

**`convoy_init`** — `{ ok, created, series_file, workspace, next }`: the paths
written, and the `series_file` / `workspace` to hand straight to `convoy_run`.

## Authoring a series.toml

`convoy_init` writes a complete, labelled, runnable example — the fastest way to a
correct series is to scaffold one and adapt it. The authoritative field reference is
[docs/design/02-formats.md](../../docs/design/02-formats.md); the schema below is the
whole of it. All sections are required, and `[[checks]]` and `[[prs]]` each need at
least one entry.

| Section | Fields | Notes |
|---|---|---|
| `[series]` | `id`, `version` (strings) | series identity |
| `[branches]` | `base`, `integration` (strings) | the workspace is staged on `base`; the integrated result lands on `integration` |
| `[paths]` | `prompts`, `outputs` (dir paths) | use **absolute** paths; `outputs` must be **out-of-tree** (outside the workspace) |
| `[governance]` | `model` **or** `tier`, `effort`, `permission_mode`, `timeout_seconds` | one of `model`/`tier` required; `effort`, `permission_mode`, `timeout_seconds` all required (no defaults); see below |
| `[governance.budgets]` | `implementation`, `review`, `fix` (USD numbers) | all three required; each must be **> 0** (a `0` budget is rejected — it would disable the spend cap) |
| `[governance.tools]` | `implementation`, `review`, `fix` (arrays of tool names) | all three required; the per-role tool allow-list |
| `[review]` | `blocking` (bool, optional, default `false`), `max_fix_attempts` (int) | `max_fix_attempts` bounds the repair loop (`0` = a blocking red halts immediately); `blocking` is reserved and optional — see "What blocks a merge" below |
| `[[checks]]` | `name`, `run` (shell command), `blocking` (bool), `independent` (bool, default `false`), `asset` (optional path), `repair_hint` (optional string) | the gate; the same checks run after **every** PR (series-global) |
| `[[prs]]` | `id`, `branch`, `prompt` (file under `[paths].prompts`), `phase` (tag), `depends_on` (array of PR ids, default `[]`), `model` / `tier` / `effort` (optional, inherit `[governance]`) | the PR DAG |

- **`model` vs `tier`.** Set an explicit `model` (e.g. `claude-haiku-4-5`) or a `tier`
  that resolves to one: `weak` → `claude-haiku-4-5`, `mid` → `claude-sonnet-5`, `strong`
  → `claude-opus-4-8`, `frontier` → `claude-fable-5`. `model` wins if both are set. A
  `[[prs]]` table may set its own `model` / `tier` / `effort`, falling back to
  `[governance]` when absent; a PR that sets `model` or `tier` supplies both (the series
  pair is not consulted), and both spawns of a PR — implementation and fix — resolve the
  same value. A per-PR `budget` / `budgets` key is still rejected at load, because budgets
  are **per-role** (`implementation` / `review` / `fix`) and a per-PR scalar has no role
  to bind to.
- **`permission_mode`** ∈ `default`, `acceptEdits`, `plan`, `bypassPermissions`. convoy
  passes it through but never *forces* an auto-approve mode.
- **`effort`** is required (no convoy-side default) and is passed through to the spawn
  (e.g. `low`, `medium`, `high`).
- **Required vs optional.** Every field in the table is required except eight, which
  default: `[[checks]].independent` (`false`), `[[checks]].asset` (`''`, unused),
  `[[checks]].repair_hint` (`''`, no hint), `[[prs]].depends_on` (`[]`),
  `[[prs]].model` / `.tier` / `.effort` (unset, inherit `[governance]`), and
  `[review].blocking` (`false`, reserved).
  `[[checks]].name`/`run`/`blocking` are all required.
  `[series].version` is any string (the example uses `"1"`); PR `id`s must be unique (they
  are what `depends_on` references). The exhaustive per-field types and the full telemetry
  line schema live in
  [docs/design/02-formats.md](../../docs/design/02-formats.md), which ships with the plugin.
- **Calibrating `[governance.budgets]`.** The `fix` budget scales with the complexity of
  the repair, not with the implementation estimate — a legitimate fix (e.g. updating a
  contract or fingerprint test the change invalidates) can cost more than the
  implementation spawn did. An under-set `fix` cap halts the whole series (outcome
  `budget`; the truncated work is not integrated); the recovery is to raise the cap,
  restore a clean tree (a budget halt leaves the truncated spawn's work uncommitted —
  see "Limits and re-runs"), and re-run (`reset` / `--fresh`).
- **`[governance.tools]`** entries are host Claude Code tool names (e.g. `Read`, `Edit`,
  `Write`, `Bash`, `Grep`, `Glob`); convoy passes the per-role allow-list through to the
  spawn unchanged.
- **`timeout_seconds`** bounds each agent spawn and each gate check; a spawn that times
  out is classified as an `infrastructure` halt.
- **Checks** run as shell commands with the **workspace as their working directory**; a
  non-zero exit code is a red. The same `[[checks]]` run after every PR. A check may
  declare `repair_hint = "..."` — a one-line repair recipe (e.g. the project's
  regeneration command for a generated-artifact freshness check) appended verbatim to
  the fix spawn's brief when that check fails, so the repair does not depend on the
  agent inferring the recipe from the failure text.
- **An `independent` check** is one the implementing agent did not author and cannot
  reach — its `asset` (the oracle it runs) must live **out-of-tree**. Isolation is
  enforced fail-closed at gate time: a blocking independent check with an in-tree or
  missing `asset` fails closed (a synthetic red; the check does not run). `independent`
  changes only the repair path, never whether a red blocks the merge. `asset` is
  meaningful **only** for a blocking independent check (it is the file whose isolation is
  verified); it is ignored for any other check.
- **What blocks a merge.** The deterministic `[[checks]]` gate is the sole arbiter: a
  check with `blocking = true` that goes red blocks the merge and drives the bounded fix
  loop. `[review].blocking` is a reserved switch for an optional blocking LLM self-review
  that v1's headless driver does **not** run, so in v1 it has no effect on whether a PR
  merges (the scaffold leaves it `false`); the field that matters in `[review]` is
  `max_fix_attempts`.
- **The `review` role is reserved.** `[governance.budgets].review` and
  `[governance.tools].review` are required, but v1's headless driver spawns only
  `implementation` and `fix` — so the `review` budget and tool allow-list have no effect in
  v1 (reserved for the same optional blocking self-review lane as `[review].blocking`). Set
  them to any valid values; the scaffold uses small placeholders.
- **Two meanings of "phase".** The governance **role** (`implementation` / `review` /
  `fix`) that budgets and tools key on is unrelated to the free-form `[[prs]].phase`
  grouping tag. Execution order comes from `depends_on`, not from `phase`.

A minimal single-PR series:

```toml
[series]
id = "demo"
version = "1"
[branches]
base = "base"
integration = "integration"
[paths]
prompts = "/abs/demo/prompts"
outputs = "/abs/demo/outputs"
[governance]
model = "claude-haiku-4-5"
effort = "low"
permission_mode = "acceptEdits"
timeout_seconds = 1800
[governance.budgets]
implementation = 1.0
review = 0.5
fix = 0.5
[governance.tools]
implementation = ["Read", "Edit", "Write", "Bash"]
review = ["Read", "Grep", "Glob"]
fix = ["Read", "Edit", "Write", "Bash"]
[review]
blocking = false
max_fix_attempts = 1
[[checks]]
name = "suite"
run = "python -m pytest -q"
blocking = true
independent = false
[[prs]]
id = "pr-1"
branch = "pr-1"
prompt = "implement.md"
phase = "core"
depends_on = []
```

## Limits and re-runs

v1 is headless and sequential: PRs run one at a time in dependency order, and there is
no resume — a halted run does not check-point-and-continue. Start each run from a clean
`base` branch in the workspace (a leftover `integration` or PR branch from a prior run
can collide). The prompts named in `[[prs]].prompt` must exist under `[paths].prompts`
before the run; `dry_run` reports any that are missing.

To re-run cleanly, pass `reset: true` (CLI: `convoy run --fresh`): before staging, convoy
checks out `base` and deletes the `integration` branch and every PR branch the series
names — then runs as normal. The reset touches **branches only**: it does not discard
uncommitted changes or remove untracked files, and a `budget` or `infrastructure` halt
returns *before* the truncated spawn's work is committed, leaving exactly that kind of
debris behind. After such a halt, restore a clean tree by hand (discard modifications,
remove untracked leftovers) before re-running — a dirty tree can abort the reset's own
checkout. A re-run
starts the series from scratch and re-spends it in full (there is no partial credit for
a prior attempt). `outputs/spawns.jsonl` is
append-only **across** runs — each run's lines carry a unique `run_id` (a sortable
`%Y%m%dT%H%M%SZ` stamp plus a short random suffix, e.g. `20260705T140000Z-a1b2c3d4`, so
two runs in the same second stay distinct), so a reader selects the latest `run_id`; a `convoy_run` summary
already scopes to the run it just executed. Sharing one workspace between two concurrent
runs is not supported.

## Cost & latency

Cost is the sum of the nested `claude -p` spawns — one implementation spawn per PR,
plus up to `max_fix_attempts` fix spawns when a gate goes red. It scales with the
**model tier** (an Opus run costs far more than Haiku), effort, brief size, and PR
count. The gate checks themselves are local commands (near-free).

- **Cost (MEASURED):** roughly **$0.04 per spawn** at `model = claude-haiku-4-5`,
  `effort = low`, on small briefs (13 spawns totalled ~$0.54 in a dogfooding run). A
  clean single-implementation PR is about one spawn; budget a few spawns per PR if
  the fix loop engages. A stronger tier multiplies this by a lot.
- **Latency (ESTIMATE):** each spawn is a full headless agent run — tens of seconds
  to a few minutes at low effort / small tasks, longer at higher effort or larger
  tasks. v1 runs PRs **sequentially** in dependency order (no parallelism), so
  wall-clock is roughly the sum of the spawns plus the gate commands.
- **Long or autonomous runs:** `convoy_run` is synchronous — the tool call blocks for
  the entire series (minutes to hours) and cannot be polled. For a long run, the
  supported pattern is the CLI in a background shell: `convoy run <series.toml>` from
  the workspace directory (the CLI uses the current directory as the workspace) with
  output redirected, reading progress from the telemetry file — `outputs/spawns.jsonl`
  is appended line by line as the run proceeds. The CLI and the MCP tool drive the same
  engine, so the run and its telemetry are identical.
- **Seat probe (per real run):** before any git mutation, convoy runs one minimal,
  tool-less, budget-capped ($0.05) probe spawn per distinct model the run can spawn on
  — the `[governance]` model plus any per-PR override, usually 1-3 in total — so an
  expired seat, an exhausted usage limit, or a model the seat cannot access fails the
  run clean (a `kind: "seat"` pre-flight problem) instead of at that PR after branches
  were staged. It stops at the first dead model. `dry_run` never spawns, probe included.

Per-phase budgets are hard caps: a spawn cut off by its `--max-budget-usd` is treated
as truncated, untrustworthy work — the run halts `budget` (exit 4) rather than gating
a partial result. Set budgets with headroom.

## When not to use it

- **A single quick edit or one-shot task** — a direct agent turn does it without the
  DAG, gate, and telemetry overhead. convoy earns its keep across several PR-sized
  steps, not one.
- **Interactive, human-in-the-loop PR review** — v1 is headless and autonomous, with
  no checkpoints. If you want to review each step as it lands, that is the normal
  Claude Code workflow, not convoy.
- **You still need to decide what to build or write the spec** — convoy runs a series
  you already have (v1 does not decompose or author one). Author the series.toml +
  prompts first (start from `convoy_init`).
- **A latency-sensitive path** — anything a user is waiting on live. A run is minutes
  to hours.
- **No co-located authenticated `claude` seat** — the per-PR `claude -p` spawns can't
  run without one.
- **No git workspace or relative `[paths]`** — pre-flight does not verify either
  (a missing repo fails at staging; a relative path resolves against the engine's
  working directory). Set up the repo and absolute `[paths]` first.
- **You need PRs to run in parallel** — v1 is strictly sequential by dependency order.

## Adopting convoy in an existing project

An adopting repo commits nothing: no fixture, no config file, no convoy section anywhere
in the tree. A series.toml and its per-PR prompt files are authored on demand for the job
at hand, and since `[paths]` are absolute they can live entirely out-of-tree alongside
`outputs`. The scored agent inherits the workspace's own conventions — its AGENTS.md /
CLAUDE.md — through the spawned `claude -p`, which runs with the workspace as its working
directory; convoy injects nothing of its own (config isolation strips the *operator's*
config dir, never the workspace's files).

The boundaries are deliberate scope decisions, not gaps:

- **No prompt-injection assembly.** A PR's brief is the authored prompt file, passed to
  the spawn verbatim; convoy composes nothing around it (the fix brief's appended
  failing-checks section, above, is the one exception).
- **No consumer or stage hook mechanism.** There are no pre/post callbacks to register;
  the deterministic `[[checks]]` gate is the only project code a run executes around the
  spawns.
- **Telemetry is economy plus gate outcomes** — tokens, turns, cost, duration, verdicts.
  It is not a reflection journal; there is no qualitative self-report channel.

One calibration datum for the small end: a three-small-PR series has shipped 3/3
attempt-0 for ~$3.18 and ~8 minutes of agent time — the per-series overhead is small
enough that a series pays off even for small jobs.

## Setup (first run)

If the `convoy_run` / `convoy_init` tools aren't available yet, install the plugin —
**no clone needed** (`uv` must be installed):

1. **Install from GitHub** as a pinned plugin:
   `claude plugin marketplace add grimaldost/convoy`, then
   `claude plugin install convoy@convoy`. The plugin runs from its own cache clone;
   local edits never perturb it. It launches the server with
   `uv run --project ${CLAUDE_PLUGIN_ROOT} python -m convoy.interface.mcp`.
2. **Co-located `claude` seat** — `convoy_run` spawns `claude -p` per PR, so run on a
   machine with an authenticated Claude Code seat (`claude --version`).
3. **A series to run** — a git workspace plus a series.toml whose `[paths]` are
   absolute and whose `outputs` dir is out-of-tree. `convoy_init "/abs/dir"` writes a
   correct, runnable example (series.toml, a prompt, an out-of-tree oracle for a
   blocking independent check, and a git-initialized `workspace/` on the base branch).
4. **Verify with no spend:** call `convoy_run` with `dry_run: true` — a clean series
   returns `{ "ok": true, "outcome": "validated" }`.

## Example

Scaffold a starter series, then validate it for free before spending:

> Call `convoy_init` with directory "/abs/demo". Then call `convoy_run` with
> series_file "/abs/demo/series.toml", workspace "/abs/demo/workspace", and
> dry_run true.

When the dry run returns `outcome: "validated"`, drop `dry_run` for the real run and
read the result's `economy` and `prs` — and `telemetry_path` for the full per-spawn
trace.
