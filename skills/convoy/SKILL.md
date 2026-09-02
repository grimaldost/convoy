---
description: >-
  Two separable capabilities, dispatched separately. (1) Execute an already-settled plan of
  two or more PR-sized changes as a governed, measured series — a coding agent driven
  through each task in dependency order under a per-phase budget, each result gated
  deterministically, repaired on a red gate, the green branches integrated, and a per-spawn
  economy plus gate summary read back. The trigger is the plan, not convoy's own file: use
  when a spec, plan or PR manifest already names two or more PR-sized changes; when a wave
  is about to be implemented PR by PR and someone will want to price or audit it; when the
  work is hours nobody intends to sit through; when a series.toml exists, or wants
  scaffolding with `convoy_init`. (2) The deterministic gate STANDALONE — `convoy gate` /
  `convoy_gate` run a series' checks against a workspace once, no spawn, no orchestration:
  use whenever work is implemented outside convoy (direct agents, subagent dispatch, a
  hand-written branch) and its verification should not be the implementer's own
  self-report — judge and defendant must differ. Rejecting the runner does not mean
  rejecting the gate; evaluate the two separately before dispatching around convoy
  entirely. Not for a single quick edit or one-shot task with no verification stakes —
  that is a direct agent turn; not for human-in-the-loop PR review — that is the normal
  Claude Code workflow; not for writing the spec or deciding what to build — convoy
  executes a plan, never authors one.
---

# convoy

convoy runs a **governed, measurable multi-PR series**. You give it a series
(PR-sized tasks with dependencies, a base branch, per-phase budgets, and a
quality gate); it drives a coding agent to implement each PR in dependency order
under budget, gates the result against the series' checks, repairs on a blocking
failure, integrates the green branches, and records **per-spawn economy** (tokens,
turns, cost, duration) as an append-only, versioned trace. It is headless —
fire-and-walk-away, no human checkpoints.

The plugin exposes four MCP tools:

- **`convoy_run`** — run a series (or, with `dry_run`, pre-flight it for free; or,
  with `detach`, start it and get a handle back at once).
- **`convoy_gate`** — run the series' `[[checks]]` against a workspace once, no
  spawn and no git mutation: the deterministic gate standalone, for verifying work
  produced outside convoy (see "The gate without the run" below).
- **`convoy_init`** — scaffold a runnable starter series to adapt or smoke-test.
- **`convoy_status`** — ask a run how it is doing, including one still in progress
  and one this server never started. Reads the ledger only: no spend, no state, no
  touch on the workspace, so polling is cheap and safe.

A run **spends real model budget** and takes minutes to hours — it spawns a
subprocess `claude -p` per PR. Always `dry_run` first (free, no side effects),
then drop it for the real run. Because a real run is that long, do not hold a
blocking `convoy_run` open for it: pass `detach: true` and poll `convoy_status`
with the `run_id` it returns.

## Arguments

### `convoy_run`

- `series_file` (required) — absolute path to the series.toml to run.
- `workspace` (required) — absolute path to the git repository to operate in (the
  scored tree). The series is staged on its base branch here; each PR's branch and
  the integration branch are created in this repo. It must be an existing git repo
  whose current/base branch matches the series' `[branches].base`. **Do not write to
  this repository while the run is live**: convoy moves `HEAD` between branches for the
  duration, so a commit made from another session lands on whichever branch is checked
  out at that instant rather than the one you meant.
- `dry_run` (default `false`) — when `true`, only pre-flight the series (structure,
  model resolution, paths, gate isolation) and return `{ok, outcome, problems,
  advisories}`. No git mutation, no agent spawn, no spend. Do this before every real run.
- `config_isolation` (default `true`) — run the scored agent under a credential-only
  `CLAUDE_CONFIG_DIR` so the operator's settings, hooks, plugins, and memory never
  leak into the run. Internally convoy makes a fresh temp config dir per run, copies
  **only** your Claude credential into it (so auth still works), and removes it when the
  run ends. Turn it off only to deliberately run under your full operator config dir
  unchanged.
- `reset` (default `false`) — **DESTRUCTIVE**, opt-in workspace restore before staging:
  discard uncommitted changes to tracked files, delete untracked files and directories,
  check out `base`, and delete the `integration` branch and every PR branch the series
  names — so a completed or halted run can be re-run without a "branch already exists"
  failure. These are the same steps `convoy clean` performs, deliberately: a `budget` or
  `infrastructure` halt returns *before* the truncated spawn's work is committed, so it
  leaves exactly the debris branch deletion cannot clear, which then aborts the reset's own
  checkout. Off by default, and with it off nothing in the tree is touched — a leftover
  branch fails loud exactly as without the flag. Run `convoy clean --dry-run` first if you
  want to see what it will remove. CLI equivalent: `convoy run --fresh`.
- `resume` (default `false`) — **the cheap way to recover a halted run.** Continue the
  existing `integration` branch instead of creating one, skipping every PR whose work it
  already contains and re-attempting the rest. After a halt that branch holds every PR
  that gated green, so re-running without this pays a second time for work already on
  disk. Each skipped PR is recorded as `pr_skipped` with the reason `already integrated
  before this resume` — distinct from the halt reasons on purpose, since "done" and "never
  ran" are opposite outcomes. Mutually exclusive with `reset`, and resuming when no
  `integration` branch exists is a pre-flight problem rather than a silent full run (a
  first run takes neither flag). CLI equivalent: `convoy run --resume`.
- `detach` (default `false`) — **start the run and return at once** instead of blocking
  for the whole series. The result is a handle, not a result: `{ok: true, outcome:
  "started", state: "running", run_id, pid, telemetry_path, result_path, log_path,
  next}`. Follow it with `convoy_status` using that `run_id`. The run is a detached
  child process, so it survives this server exiting — though a host that confines its
  children to a kill-on-close job object still takes it down, which shows up as a run
  that stops advancing. Pre-flight still runs before the launch, so a malformed series
  is refused immediately rather than discovered by polling; the seat probe, the
  workspace lock and git are the child's to hit, and land in `result_path`. `dry_run`
  takes precedence: a pre-flight is free and instant, so there is nothing to detach.
  CLI equivalent: `convoy run` in a background shell.

### `convoy_gate`

- `series_file` (required) — absolute path to the file holding the `[[checks]]` to
  run: a full series.toml, or a minimal file carrying only `[series] id` and
  `[[checks]]`.
- `workspace` (required) — absolute path to the tree to gate — the checks run there.
  Nothing is written, no branch is created, no lock is taken; gating a tree another
  process is driving gates whatever that driver has checked out.
- `phases` (default `[]`) — optional phase tags. Empty runs the whole gate; tags run
  exactly the checks a PR carrying them would be gated on (the unscoped checks plus
  the ones scoped to a named tag). Tags selecting zero checks are refused as a usage
  error rather than answered green.

### `convoy_status`

- `series_file` (required) — absolute path to the series.toml whose run you want the
  state of. Its `[paths].outputs` is where the ledger lives, and that is all this reads.
- `run_id` (default `""`) — which run to report. Defaults to the most recent run in the
  ledger, which is usually what a poller means; pass an explicit id to follow one run in
  an outputs dir that accumulates several — including the id a `detach` launch returned.
- `workspace` (default `""`) — absolute path to the run's git repository. Optional, and
  read for exactly one thing: the run lock there names the process that owns the run,
  which is what tells `dead` apart from `running`. Nothing is written. Omit it and a run
  with no terminal record reads `running`, as before — so pass it whenever you want to
  know that a run has died.

Traps the pre-flight catches (so `dry_run` reports them instead of a half-run):
`[paths]` that don't resolve to an existing prompts dir or that name missing prompt
files (note: absoluteness itself is not checked — a relative path resolves against the
engine's working directory, so use absolute paths); an `outputs` dir
**inside** the workspace (telemetry writes would dirty the git tree and abort a
checkout — keep it out-of-tree); a blocking independent check whose `asset` is
in-tree (isolation fails closed); a `[[checks]].phases` tag that no PR declares (the
check would gate nothing); and a governance block that resolves to neither a
`model` nor a known `tier`.

The dry run also returns **`advisories`** — located `{kind, where, message}` remarks
that do **not** make the series invalid, so they never change `ok` or `outcome` (and on
the CLI, `convoy validate` prints them to stderr and still exits `0`). Today there are
three: a PR that no blocking check gates, which therefore integrates unverified; a check
declaring an `asset` on a lane that will never read it; and a blocking gate that is
path-scoped away from test files present in the workspace, so a green gate is a narrower
claim than the tree warrants. Read them; they are the things that are legal and probably
not what you meant.

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
  skipped, skip_reason, in_flight }`. `in_flight` names the role of a spawn that started and
  has not completed (`null` otherwise) — on a live run, what convoy is doing right now; on a
  killed run, the PR the money was going into. `gate` is `null` if the PR never gated, else `{ attempt,
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
  (`implementation` / `fix`), `exit_code`, `classification` (`ok` / `infrastructure` /
  `budget`), `input_tokens`, `output_tokens`, `num_turns`,
  `duration_s`, `cost_usd`, `effective_model`, `cost_estimated`; the full telemetry contract
  is in `docs/design/02-formats.md`.
- `halt` — `null` on a clean run; on any halt, `{ pr_id, phase, role, spend_usd, cap_usd }`
  saying where the run stopped. `role` is the spawn role that hit it (`implementation` /
  `fix`) or `gate` when the bounded fix loop was exhausted. `spend_usd` / `cap_usd` are
  populated **only** for `outcome: "budget"` — the spawn's cost against the ceiling it hit;
  they are `null` for `blocked` and `infrastructure`, where no ceiling caused the halt.
  Read this first on a non-`completed` run: it answers which PR and how close to which cap
  without opening the trace.
- `advisories` — always present, empty when there is nothing to say: what pre-flight
  remarked on without stopping the run (today, a PR no blocking check gates, which
  therefore integrated **unverified**). Read on a real run, not only on `dry_run` —
  they are recorded on the run's `run_start` telemetry line, so `convoy_status` reports
  them too. They never affect `ok` or `outcome`.
- `truncated` — `{ any, prs }`: how many PRs the `prs` list dropped past its cap. If
  `any` is `true`, read `telemetry_path` for the full set.

**`convoy_run`, `dry_run: true`** — `{ ok, outcome, series_id, problems, advisories }`,
where `outcome` is `validated` (clean, `ok: true`) or `usage` (problems found, `ok:
false`), and `problems` is a list of `{ kind, where, message }` (empty when clean; `kind`
is one of `governance`, `dag`, `paths`, `prompt`, `isolation`, `phases`, `resume`,
`run_id`, `seat`, and `where`
locates the offending section or entry, e.g. `[[prs]] 'pr-2'`). `advisories` is a list of
the same shape, always present and often empty; it is **non-blocking** and never affects
`ok` or `outcome` (`kind` is `gate` today). Two producers: a PR that phase scoping leaves
with no blocking check, and a check declaring an `asset` while not being both `blocking`
and `independent` — the isolation guard is that field's only consumer, so anywhere else it
is accepted and read by nothing.

**`convoy_run`, could-not-start** — a real run returns this same `outcome: "usage"`
(`ok: false`) shape if it cannot start, never a raised exception. It carries `problems` (a
located `{ kind, where, message }` list, same as `dry_run`) for a structure or pre-flight
failure, or `error` (a message string) with an `error_kind` (`spec` | `governance` | `git`
| `busy` | `filesystem`) for an unreadable / invalid spec, a runtime git / filesystem
failure, or another run holding the workspace lock (`busy`). So
`usage` is the one `outcome` a real-run call can return **besides** the four engine outcomes
above.

**`convoy_run`, `detach: true`** — `{ ok: true, outcome: "started", state: "running",
run_id, pid, telemetry_path, result_path, log_path, next }`. `ok` reports the *launch*
here, since the run has no verdict yet, and `outcome: "started"` is the one outcome only
this call returns. A failed launch is the ordinary `outcome: "usage"` shape above.

**`convoy_status`** — the same envelope `convoy_run` returns, plus a **`state`** to
branch on first: `running` (no `run_complete` line yet, so `outcome` / `integrated` /
`exit_code` are `null` and `economy` is a partial running total — the useful thing to
watch), `dead` (the same null terminal fields, plus the fact that the process which would
have filled them is gone, so the economy is final rather than partial; `message` says how
to recover), `finished` (the terminal fields are meaningful, `halt` included), or
`unknown` (nothing recorded under that id — not an error, just a run that has not written
its first line). A detached run that died before writing to the ledger reports `finished`
with its own could-not-start envelope, read from `result_path`.

`dead` needs the optional `workspace` argument: the run lock in that repo names the
process that owns the run, and that pid is the only thing separating a run still going
from one that was killed. Without it a run with no terminal record reads `running`, as it
always did. The claim is made only on positive evidence — a lock naming a process that no
longer exists — so asking from a tree that holds no lock never yields a false `dead`.

Once `convoy clean` has cleared that lock the run reads `finished` with a fifth `outcome`,
`abandoned`, carrying the infrastructure exit code — `clean` closes the killed run's ledger
entry on its way past, because a pid is reusable and the fact stops being establishable
after that. `integrated` is `false` and `halt` is `null`: the process that recorded it was
not there for the run.

**`convoy_init`** — `{ ok, created, series_file, workspace, next }`: the paths
written, and the `series_file` / `workspace` to hand straight to `convoy_run`.

**`convoy_gate`** — the gate envelope: `ok`, `outcome` (`completed` | `blocked` |
`usage`), `series_id`, `workspace` (resolved absolute), `phases`, `checks` (one
`{name, passed, blocking, independent, phases, exit_code, timed_out, detail}` per
selected check — the structured fields for branching, `detail` carrying the failure
tail a repair can be briefed with; capped at 50 with a `truncated` report), `blocking_red`,
`independent_red`, `repair_brief` (the failing-checks section ready to append to an
implementer's brief — the same text convoy briefs its own fix spawn with, `''` when the
gate is green), `counts` (`{total, selected, passed, failed}`), `advisories` (always
present, currently always empty), the CLI-equivalent `exit_code` (0 green — a
non-blocking red advises without blocking — 1 blocking red), and `convoy_version` (the
engine that produced the envelope). A refused invocation
returns the usage envelope instead: `{ok: false, outcome: "usage", error_kind, error,
exit_code: 3, series_id?}`. The CLI twin `convoy gate --json` prints these same
objects, usage paths included. `brief=true` (CLI `--brief`) returns only `{ok, outcome,
repair_brief, convoy_version}` — for reading the verdict inside a model turn with nothing
else in it. `series_file` is optional: omitted, the project spec is used —
`$CLAUDE_PROJECT_DIR/.convoy/gate.toml`, then `.convoy/gate.toml` in the workspace and its
parents — and a project spec loads with `CONVOY_ORACLES` defaulted to
`~/.convoy/oracles/<project dir name>`; none found is a usage result naming where it looked.

## The gate without the run

The deterministic gate is separable from the orchestration: `convoy_gate` (CLI:
`convoy gate`) runs a series' `[[checks]]` against a workspace **once**, with the same
runner, the same fail-closed independence guard, and the same verdict rules the run
applies after every PR — and nothing else. No agent spawns, no branch, no merge, no
telemetry, no spend beyond the check commands themselves.

Use it when the implementation is produced outside convoy but the verification should
not be self-reported: an externally orchestrated multiagent build, a hand-written
branch, a diff another tool produced. The implementer's own "done" is not a verdict —
judge and defendant must differ — and this tool is the judge without buying the whole
courtroom. The `[[checks]]` semantics are identical to a run's, so a series file
authored for `convoy_run` gates the same way standalone, and a minimal file carrying
only `[series] id` and `[[checks]]` is enough when no run is ever intended — a project
keeps that file at `.convoy/gate.toml`, where both surfaces find it without an argument.
`convoy
validate` accepts such a file too: it applies the refusals that stay decidable without a
run — the selection must contain a blocking check, and every blocking independent check
must back its isolation — and prints `ok (gate-only)`, which is how you learn a gate file
is sound before its check commands cost anything. A file carrying `[branches]`, `[paths]`,
`[review]` or `[[prs]]` is a full series and is validated as one, so a series that lost a
section is never answered with a gate's narrower yes.

**The per-project gate.** `convoy gate --init` (CLI) scaffolds `.convoy/gate.toml` from
the toolchain it finds in the workspace — Python: the uv lockfile check, ruff lint and
format, the type checker the pyproject names, pytest; Node: the `lint`, `typecheck` and
`test` scripts; else a placeholder check that stays red until you declare the checks —
as blocking, non-independent checks, plus a `.gitignore` for the hook log. That default
gate is the project's own suite: it catches regressions, and it is exactly what an
implementer can satisfy by self-report. The class of defect the gate exists for needs
an independent check — a held-out oracle the implementer cannot reach — which `--init
--independent <name>` scaffolds as a placeholder under `CONVOY_ORACLES` (default
`~/.convoy/oracles/<project dir name>/`), declared through `${CONVOY_ORACLES}` so the
spec stays portable; the placeholder is red until written. Write it before dispatching
any implementer: the judge is appointed before the defendant.

**The hook: the gate the orchestrator never has to think about.** Installing the plugin
registers a `PostToolUse` hook on `Agent` (and its older name `Task`) that runs
`convoy hook` after every subagent dispatch. The hook finds the project spec the way
`convoy gate` does — `$CLAUDE_PROJECT_DIR/.convoy/gate.toml`, then `.convoy/gate.toml`
from the event's `cwd` upward — and does nothing where none exists: the presence of
the spec is the per-project switch, so installing the plugin arms nothing until a
project opts in with `convoy gate --init`. Green: exit 0 and no output, nothing enters
the orchestrator's context. Blocking red: exit 2 with the repair brief on stderr, which
Claude Code shows to the orchestrator as feedback on the completed dispatch — the cue
to dispatch a fix subagent, whose return re-fires the hook, so the loop closes without
the orchestrator ever running or reading a gate itself. A gate that cannot run
(invalid spec, refused invocation, dead workspace) is exit 2 with a one-line reason,
never a silent green. Put `[convoy-phase: <tag>]` in a subagent's brief to scope the
gate to that tag's checks (the selection `convoy gate --phase <tag>` makes; a tag no
check declares is reported, not narrowed). A dispatch that did not complete — a
background one, a failed one — is recorded and not gated. Every firing appends one
JSON line to `.convoy/hook.log` (verdict, phases, counts, the subagent's id and dated
model, the gate's wall-clock, `convoy_version`), so an experiment counts firings from
the log. Exit codes are the hook protocol's (0 silent, 2 feedback), not convoy's. The
hook's timeout is 1800 s; each check is bounded by the spec's `timeout_seconds`. Hooks
do not run under `claude --bare`, and convoy's own spawns run under config isolation,
so the hook never fires inside a governed run. A project without the plugin wires the
same command in its `.claude/settings.json`.

The envelope is written to be acted on, not just read: on a red gate `repair_brief`
carries the failing-checks section — each blocking red's name, `detail` and declared
`repair_hint` — in the exact form convoy appends to its own fix spawn's brief, so an
external orchestrator repairs against the same words rather than reassembling them from
the per-check fields. `convoy_version` names the engine that judged, which is what makes
a stored verdict still interpretable once the shape grows.

Some rules differ from a run, all deliberate, with one thread: a gate-only caller
asked a question, and an invocation that cannot produce a meaningful answer is refused
(`outcome: "usage"`) rather than answered. Four refusals: a phase tag no check
declares (a typo must not silently narrow the gate to the unscoped checks and go
green); a selection with no blocking check (nothing in it can say no, so `completed`
would assure nothing — inside a series the same condition is the author's declared
choice and pre-flight merely advises); an empty selection; and a blocking independent
check whose isolation is not backed (the run reports that identical defect at
pre-flight — calling it a red would point a repair loop keyed on `independent_red` at
a spec misconfiguration no repair can fix).

And no workspace lock is taken. Convoy itself writes nothing to the tree — but the
check commands run in it and routinely do (caches, build output), so never gate a
workspace a `convoy_run` is actively driving: beyond gating whatever that driver has
checked out at that instant, the run's commit step stages the whole tree and can
commit a concurrent gate's artifacts into a scored branch.

When to compose which way — gate-only over external orchestration versus a series of
one PR with the engine owning the spawn — is doctrine, not schema:
[docs/authoring-series.md](../../docs/authoring-series.md).

## Authoring a series.toml

`convoy_init` writes a complete, labelled, runnable example — the fastest way to a
correct series is to scaffold one and adapt it. The authoritative field reference is
[docs/design/02-formats.md](../../docs/design/02-formats.md); the schema below is the
whole of it. All sections are required, and `[[checks]]` and `[[prs]]` each need at
least one entry.

| Section | Fields | Notes |
|---|---|---|
| `[series]` | `id`, `version` (strings), and optionally `spec_path` + `spec_sha256` | series identity, plus the spec pin |
| `[branches]` | `base`, `integration` (strings) | the workspace is staged on `base`; the integrated result lands on `integration` |
| `[paths]` | `prompts`, `outputs` (dir paths) | use **absolute** paths; `outputs` must be **out-of-tree** (outside the workspace) |
| `[governance]` | `model` **or** `tier`, `effort`, `permission_mode`, `timeout_seconds` | one of `model`/`tier` required; `effort`, `permission_mode`, `timeout_seconds` all required (no defaults); see below |
| `[governance.budgets]` | `implementation`, `review`, `fix` (USD numbers) | all three required; each must be **> 0** (a `0` budget is rejected — it would disable the spend cap) |
| `[governance.tools]` | `implementation`, `review`, `fix` (arrays of tool names) | all three required; the per-role tool allow-list |
| `[review]` | `blocking` (bool, optional, default `false`), `max_fix_attempts` (int) | `max_fix_attempts` bounds the repair loop (`0` = a blocking red halts immediately); `blocking` is reserved and optional — see "What blocks a merge" below |
| `[[checks]]` | `name`, `run` (shell command), `blocking` (bool), `independent` (bool, default `false`), `asset` (optional path), `repair_hint` (optional string), `phases` (optional array of phase tags) | the gate; a check runs after **every** PR unless `phases` scopes it — see "Scoping checks by phase" |
| `[[prs]]` | `id`, `branch`, `prompt` (file under `[paths].prompts`), `phase` (tag), `depends_on` (array of PR ids, default `[]`), `model` / `tier` / `effort` (optional, inherit `[governance]`) | the PR DAG |

- **`model` vs `tier`.** Set an explicit `model` (e.g. `claude-haiku-4-5`) or a `tier`
  that resolves to one: `weak` → `claude-haiku-4-5`, `mid` → `claude-sonnet-5`, `strong`
  → `claude-opus-5`, `frontier` → `claude-fable-5`. `model` wins if both are set. A
  `[[prs]]` table may set its own `model` / `tier` / `effort`, falling back to
  `[governance]` when absent; a PR that sets `model` or `tier` supplies both (the series
  pair is not consulted), and both spawns of a PR — implementation and fix — resolve the
  same value. A per-PR `budget` / `budgets` key is still rejected at load, because budgets
  are **per-role** (`implementation` / `review` / `fix`) and a per-PR scalar has no role
  to bind to.
- **`spec_path` / `spec_sha256`** (optional, set together) — the **spec pin**: the
  repo-relative path of the spec this series was decomposed from, and the SHA-256 of its
  contents at that moment. Pre-flight resolves the path against the workspace and compares
  the hash, and refuses the run if it does not match, so no paid run executes against a spec
  that has moved since decomposition. A matching pin is recorded on the `run_start` telemetry
  line, which is what makes "which version of which spec produced this run" answerable
  afterwards. The path must be relative — a series directory travels by copy, so an absolute
  path is wrong on arrival, and it is rejected at load. Omit both for a series with no spec
  behind it; nothing changes.
- **`permission_mode`** ∈ `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`,
  `plan`, plus the legacy `default`. convoy passes it through but never *forces* an
  auto-approve mode.
- **`effort`** ∈ `low`, `medium`, `high`, `xhigh`, `max`. Required (no convoy-side default),
  passed through to the spawn, and rejected at load if it is not one of those — the agent
  CLI only *warns* on a level it does not know and then runs at its own default, so an
  unchecked typo would leave the series file and the ledger both naming a level nothing ran
  at. The resolved value is recorded on each `spawn_complete` line.
- **Required vs optional.** Every field in the table is required except nine, which
  default: `[[checks]].independent` (`false`), `[[checks]].asset` (`''`, unused),
  `[[checks]].repair_hint` (`''`, no hint), `[[checks]].phases` (`[]`, gates every PR),
  `[[prs]].depends_on` (`[]`), `[[prs]].model` / `.tier` / `.effort` (unset, inherit
  `[governance]`), and `[review].blocking` (`false`, reserved).
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
  verified); it is ignored for any other check. `run` and `asset` expand `${NAME}` from
  the environment at load (only the braced form; an unset name refuses the spec), so a
  check can name its oracle as `${CONVOY_ORACLES}/probe.py` and keep the spec portable —
  `CONVOY_ORACLES` is the conventional out-of-tree home for a project's held-out oracles.
  **When it is worth setting.** An independent check adds correctness only when the
  implementing agent cannot see the acceptance criteria it is judged against. If your
  prompts hand the agent the tests, it runs them and self-corrects, and the independent
  lane becomes a backstop against a spawn that skips them rather than a quality lever.
  Measured strongest at weak model tiers and null at the default tier — see
  `docs/design/01-gate.md`.
- **Scoping checks by phase.** By default every check runs after every PR, which makes
  an *incremental* series impossible: if PR1 lands a core slice and PR4 completes it,
  the full suite is red until PR4, so PR1 cannot pass its own gate. Give a check
  `phases` to scope it to the PRs carrying those `[[prs]].phase` tags:

  ```toml
  [[checks]]
  name = "core-suite"
  run = "python -m pytest tests/core -q"
  blocking = true
  phases = ["core"]        # gates only PRs whose phase is "core"

  [[checks]]
  name = "full-suite"
  run = "python -m pytest -q"
  blocking = true
  phases = ["extras"]      # the whole suite is only expected to pass by the last phase
  ```

  Omit `phases` and the check gates everything, exactly as before. Scoping changes
  which checks run, never what a red means — a blocking red still blocks, and a fix
  re-gate reuses that PR's own checks. Two things to know: a `phases` tag that no PR
  declares is a **pre-flight error** (a typo would silently make the check gate
  nothing), and a PR that ends up with no blocking check is **allowed but advised** —
  `convoy validate` prints an advisory naming it and still exits `0`, because that PR
  integrates unverified.
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

v1 is headless and sequential: PRs run one at a time in dependency order. Start each run
from a clean `base` branch in the workspace (a leftover `integration` or PR branch from a
prior run can collide). The prompts named in `[[prs]].prompt` must exist under
`[paths].prompts` before the run; `dry_run` reports any that are missing.

After a halt there are two ways forward, and they are not interchangeable.

**`resume: true` (CLI: `convoy run --resume`) is the cheap one.** It continues the existing
`integration` branch and skips every PR whose work that branch already contains, so the PRs
that gated green are not paid for twice. A PR branch that exists but never merged is a
partial or gate-failed attempt: it is **deleted** and re-attempted from the current
integration state rather than built on. Resuming when no `integration` branch exists is a
pre-flight problem, not a silent full run.

**A stop at a PR boundary plus an edited series file is how a gate is repaired mid-run.**
`resume` re-reads the series file, so `[[checks]]` added, widened, or re-`phases`-scoped
between two PRs govern every PR the resumed run still has to execute, while the PRs already
integrated are skipped rather than re-gated under the new rules. That is a supported
pattern, not an accident of implementation: stop the driver at a boundary, fix the gate that
turned out to be too narrow, resume. In one production night it let five added checks and
one widened check govern the remaining PRs of a seven-PR series without re-paying for the
four already integrated. The converse holds too, and is the reason it is not free: a check
added mid-series never ran against the PRs that landed before it.

**`reset: true` (CLI: `convoy run --fresh`) starts over, and is DESTRUCTIVE.** Before
staging, convoy discards uncommitted changes to tracked files, deletes untracked files and
directories, checks out `base`, and deletes the `integration` branch and every PR branch the
series names — then runs as normal, re-spending the whole series with no partial credit for a
prior attempt. Those are the same steps **`convoy clean <series.toml>`** performs, and they
are here because a `budget` or `infrastructure` halt returns *before* the truncated spawn's
work is committed: branch deletion alone cannot clear that debris, and the debris aborts the
reset's own checkout. So one destructive path, one mental model. `convoy clean` remains the
verb for restoring a workspace **without** starting a run (it takes no lock, pays for no seat
probe, and closes the killed run's ledger entry); run `convoy clean --dry-run` first to see
exactly what either will remove. Deleting a halted PR's branch by hand is not necessary;
`--resume` already does it.

`outputs/spawns.jsonl` is
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
- **Long or autonomous runs:** `convoy_run` blocks for the entire series (minutes to
  hours) unless you pass `detach: true`, which is what to do. Detached, it returns a
  handle at once and you poll `convoy_status` with the returned `run_id`. The other
  supported pattern is the CLI in a background shell: `convoy run <series.toml>` from the
  workspace directory (the CLI uses the current directory as the workspace) with output
  redirected — `convoy status <series.toml>` reports on that run too, since it reads only
  the ledger. `outputs/spawns.jsonl` is appended line by line as the run proceeds. The CLI
  and the MCP tool drive the same engine, so the run and its telemetry are identical.
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

An adopting repo commits nothing for the runner: no fixture, no config file, no convoy
section anywhere in the tree. (The standalone gate is the one opt-in: a project that
wants it commits `.convoy/gate.toml`, scaffolded by `convoy gate --init`, and keeps its
held-out oracles out-of-tree under `CONVOY_ORACLES`.) A series.toml and its per-PR
prompt files are authored on demand for the job
at hand, and since `[paths]` are absolute they can live entirely out-of-tree alongside
`outputs`. The scored agent inherits the workspace's own conventions — its AGENTS.md /
CLAUDE.md — through the spawned `claude -p`, which runs with the workspace as its working
directory; convoy injects nothing of its own (config isolation strips the *operator's*
config dir, never the workspace's files).

The boundaries are deliberate scope decisions, not gaps:

- **No prompt-injection assembly.** A PR's brief is the authored prompt file, passed to
  the spawn verbatim; convoy composes nothing around it (the fix brief's appended
  failing-checks section, above, is the one exception).
- **No consumer or stage hook mechanism inside a run.** There are no pre/post callbacks
  to register in a series; the deterministic `[[checks]]` gate is the only project code
  a run executes around the spawns. (The plugin's `PostToolUse` hook is that same gate
  on the *orchestrator's* side — it runs after a subagent dispatch in the operator's
  session, never inside a scored spawn, which config isolation keeps hook-free.)
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
