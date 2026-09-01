<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/convoy-hero-dark.svg">
  <img alt="convoy" src="assets/convoy-hero-light.svg" width="100%">
</picture>

[![ci](https://img.shields.io/github/actions/workflow/status/grimaldost/convoy/ci.yml?style=flat-square&labelColor=2A3238&label=ci)](https://github.com/grimaldost/convoy/actions/workflows/ci.yml)
[![version](https://img.shields.io/github/v/tag/grimaldost/convoy?style=flat-square&labelColor=2A3238&color=7F4400&label=version)](CHANGELOG.md)
[![python](https://img.shields.io/badge/python-3.14%2B-7F4400?style=flat-square&labelColor=2A3238)](pyproject.toml)
[![license](https://img.shields.io/badge/license-Apache--2.0-7F4400?style=flat-square&labelColor=2A3238)](LICENSE)

**convoy** decomposes work into a series of PR-sized tasks, drives a coding
agent to implement each one, gates every result against deterministic checks,
integrates the green branches, and records what each step cost.

## Quick start

Requirements: git, [uv](https://docs.astral.sh/uv/), and a co-located
authenticated Claude Code seat — convoy spawns `claude -p` per PR, so a real
run spends real money (`validate` and `dry_run` are free).

```sh
uv tool install git+https://github.com/grimaldost/convoy

convoy init demo                 # scaffold a runnable starter series
cd demo/workspace
convoy validate ../series.toml   # free preflight: spec, DAG, paths, assets
convoy run ../series.toml        # the real thing: spawns one agent, gates, integrates
```

The starter series implements one trivial PR under a $1 budget with one
blocking check, so the first run costs cents. Afterwards, look at
`demo/outputs/spawns.jsonl` — the telemetry ledger (economy + gate events) —
and the workspace's `integration` branch, the merged result.

`convoy run` and `convoy validate` use the current directory as the scored
workspace — run them from the workspace, pointing at the series file — or name
it explicitly with `--workspace <dir>` (`-w`) to drive a tree your shell is not
sitting in.

To drive convoy from an agent instead, install it as a **Claude Code plugin**:

```sh
claude plugin marketplace add grimaldost/convoy
claude plugin install convoy@convoy
```

Either CLI route installs the `convoy` command, aliased `cvy` (clone and
`uv sync` for development); the plugin route installs only the MCP tools.

## How it works

**Governed** — model, effort, permission mode, per-phase budgets and tool
allow-lists are pinned once per series, so every spawn runs under the same
audited rules.

**Gated** — deterministic checks (lint, types, tests, your own oracles) are
the sole merge arbiter; a blocking red triggers a bounded fix loop, never a
silent merge.

**Measurable** — an append-only telemetry ledger records per-spawn cost,
tokens, turns, and per-check gate outcomes, so a run can be audited and
reconstructed after the fact.

A run, step by step:

1. **Preflight.** The series file, DAG, paths, and check assets are validated
   (free); a real run then probes that the agent seat is authenticated — a
   cents-bounded, unmetered micro-spawn — before anything is staged.
2. **Stage.** The workspace checks out the `base` branch and creates the
   `integration` branch.
3. **Per PR, in dependency order:** create the PR branch, spawn a coding agent
   (`claude -p`) with that PR's prompt under the series governance, commit the
   result, and run the gate.
4. **Gate red (blocking check failed):** a fix spawn is briefed with the
   failing checks' output (and each check's declared `repair_hint`, if any),
   then the gate re-runs — up to `max_fix_attempts` times.
5. **Gate green:** the PR branch is merged onto the integration branch, and
   the next PR starts from it.
6. **Halt (budget / infrastructure / blocked):** the run stops loud, skips the
   remaining PRs with an explicit reason, and reports the outcome; green PRs
   already integrated stay on the integration branch.

Everything the run did — spawns, costs, gate verdicts, skips, outcome — is in
`outputs/spawns.jsonl`.

## The series file

`convoy init` emits a correct, copyable exemplar. Trimmed:

```toml
prs = [
    { id = "pr-1", branch = "pr-1", prompt = "implement.md", phase = "core", depends_on = [] },
]

[series]
id = "starter"
version = "1"

[branches]
base = "base"
integration = "integration"

[paths]
prompts = ".../prompts"    # per-PR prompt files (authored by you)
outputs = ".../outputs"    # telemetry lands here, out-of-tree

[governance]               # pinned once, applies to every spawn
effort = "low"
permission_mode = "acceptEdits"
timeout_seconds = 1800
model = "claude-haiku-4-5"

[governance.budgets]       # USD caps per phase
implementation = 1.0
review = 0.5
fix = 0.5

[governance.tools]         # allow-lists per phase
implementation = ["Read", "Edit", "Write", "Bash"]
review = ["Read", "Grep", "Glob"]
fix = ["Read", "Edit", "Write", "Bash"]

[review]
blocking = false           # reserved; deterministic checks are the merge arbiter
max_fix_attempts = 1

[[checks]]
name = "greeting"
run = "python .../oracles/greeting_check.py"
blocking = true
independent = true         # oracle must live out-of-tree; verified fail-closed at gate time
asset = ".../oracles/greeting_check.py"
```

PRs form a DAG via `depends_on`; checks can be `independent` (their `asset`
must live outside the scored workspace — convoy verifies that fail-closed
before the check runs) and may declare a `repair_hint` briefed to fix spawns.
The full schema, budget-calibration guidance, and authoring reference live in
[skills/convoy/SKILL.md](skills/convoy/SKILL.md); the formal format and
versioning discipline in
[docs/design/02-formats.md](docs/design/02-formats.md).

## Agent surface (MCP tools)

The plugin exposes four tools so a coding agent can drive a series — or run the
gate standalone — without shelling out:

- **`convoy_init(directory)`** — scaffold the starter series and return the
  paths.
- **`convoy_gate(series_file, workspace, phases=[])`** — run the series'
  `[[checks]]` against a workspace once and return the gate envelope: per-check
  verdicts with failure details, `blocking_red` / `independent_red`, and the
  CLI-equivalent exit code. The gate standalone, for verifying work produced
  outside convoy; no spawn, no git mutation, no telemetry. Accepts a full
  series.toml or a minimal `[series] id` + `[[checks]]` file.
- **`convoy_run(series_file, workspace, dry_run=false, config_isolation=true,
  reset=false, resume=false, detach=false)`** — run a series and return a
  structured summary: outcome, exit code, per-spawn economy totals, and a per-PR
  gate view, with the full trace referenced by path. `dry_run=true` preflights for
  free; `reset=true` resets the workspace to base first (CLI: `--fresh`);
  `resume=true` continues a halted run's integration branch (CLI: `--resume`).
- **`convoy_status(series_file, run_id='')`** — report a run's state and economy so
  far from the ledger alone, including a run still in progress and one this server
  never started. Spends nothing and never touches the workspace.

`convoy_run` blocks for the whole series (minutes to hours). For a long or
autonomous run, either pass `detach=true` — which starts the run as a child that
outlives the server and returns the `run_id` to poll — or use the CLI in a
background shell, same engine. Either way, follow it with `convoy status` /
`convoy_status`. Every argument, the result envelope, cost and latency, and when
*not* to use convoy: [skills/convoy/SKILL.md](skills/convoy/SKILL.md).

## CLI reference

| Verb | What | Notable flags |
|------|------|---------------|
| `convoy validate <series.toml>` | Free preflight (no git mutation, no spawn) | `--workspace <dir>` / `-w` (default: cwd) |
| `convoy gate <series.toml>` | Run the series' `[[checks]]` against the workspace once — the gate standalone, for verifying work produced outside convoy. No spawn, no branch, no merge; the same fail-closed independence guard and verdict rules as a run. Accepts a full series.toml or a minimal `[series] id` + `[[checks]]` file. Exit 0 green / 1 blocking red / 3 usage | `--workspace <dir>` / `-w` (default: cwd), `--phase <tag>` (repeatable; run what a PR carrying the tag would be gated on — zero selected checks is refused, not answered green), `--json` (print the gate envelope to stdout as one JSON object) |
| `convoy run <series.toml>` | Run the series against the workspace | `--workspace <dir>` / `-w` (default: cwd), `--json` (print the run summary to stdout as one JSON object), `--resume` (continue the integration branch, skipping PRs already merged into it), `--fresh` (reset to base, delete prior series branches first), `--run-id <id>` (pin the run id instead of minting one), `--quiet`, `--no-config-isolation` |
| `convoy clean <series.toml>` | **Destructive** recovery after a halted or killed run: discard uncommitted changes, delete untracked files, return to base, delete the series' branches, remove a stale run lock | `--dry-run` / `-n` (print the plan, change nothing), `--workspace <dir>` / `-w` |
| `convoy status <series.toml>` | Report a run's state and economy so far — including one still in progress. Reads the ledger only; spends nothing | `--run-id` (default: the latest run), `--json` |
| `convoy init <dir>` | Scaffold the starter series | |

Scored spawns run under **credential-only config isolation** by default: the
operator's hooks, memory, and skills don't leak into the run (the workspace's
own agent instructions still apply — they live in the repo). Opt out with
`--no-config-isolation` or `CONVOY_NO_CONFIG_ISOLATION=1`. Exit codes and the
telemetry protocol are documented in
[docs/design/02-formats.md](docs/design/02-formats.md).

## Adopting convoy in an existing project

An adopting repo commits **nothing**: no fixture, no config. A series and its
prompt files are authored on demand and can live out-of-tree alongside
`outputs`; the scored agent inherits the project's conventions from the
workspace's own agent instruction files through the spawned `claude -p`, not
from any convoy-side injection. Deliberate non-features: no prompt-injection
assembly, no consumer hooks, and telemetry is economy + gate outcomes — not
reflection journals. See the adoption section in
[skills/convoy/SKILL.md](skills/convoy/SKILL.md).

## Architecture

Functional core / imperative shell: `src/convoy/core/` is pure (spec, DAG,
gate verdict, governance, telemetry model, pricing) and imports nothing from
`src/convoy/interface/`, where the spawn, gate-runner, and reporter seams are
`typing.Protocol` ports alongside concrete git and telemetry-writer adapters,
plus the CLI and the MCP server — both thin surfaces over one shared run
service.

## Documentation

- [docs/README.md](docs/README.md) — docs map and reading order.
- [docs/design/](docs/design/) — design docs: overview, gate, formats, serving.
- [docs/adr/](docs/adr/README.md) — decision records.
- [docs/GUARDRAILS.md](docs/GUARDRAILS.md) — non-negotiable invariants.
- [skills/convoy/SKILL.md](skills/convoy/SKILL.md) — driving convoy from an
  agent: tools, series.toml schema, result envelope.
- [assets/README.md](assets/README.md) — brand assets and usage.

## Development

```sh
uv sync
uv run ruff check src tests && uv run ruff format --check src tests
uv run ty check src
uv run pytest
```

Workflow, release discipline, and the feedback→backlog loop:
[CONTRIBUTING.md](CONTRIBUTING.md). Agent playbook: [AGENTS.md](AGENTS.md).
Improvement ledger: [docs/backlog.md](docs/backlog.md). History:
[CHANGELOG.md](CHANGELOG.md).

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
