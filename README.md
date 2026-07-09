# convoy

[![CI](https://github.com/grimaldost/convoy/actions/workflows/ci.yml/badge.svg)](https://github.com/grimaldost/convoy/actions/workflows/ci.yml)

Governed, measurable multi-PR execution: decompose work into a series of
PR-sized tasks, drive a coding agent to implement each one, gate every result
against deterministic checks, integrate the green branches, and record what
each step cost.

- **Governed** — model, effort, permission mode, per-phase budgets and tool
  allow-lists are pinned once per series, so every spawn runs under the same
  audited rules.
- **Gated** — deterministic checks (lint, types, tests, your own oracles) are
  the sole merge arbiter; a blocking red triggers a bounded fix loop, never a
  silent merge.
- **Measurable** — an append-only telemetry ledger records per-spawn cost,
  tokens, turns, and per-check gate outcomes, so a run can be audited and
  reconstructed after the fact.

## How a run works

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

**Requirements:** git, [uv](https://docs.astral.sh/uv/), and a co-located
authenticated Claude Code seat (convoy spawns `claude -p` per PR; a real run
spends real money — `validate` and `dry_run` are free).

## Install

As a **Claude Code plugin** (MCP tools, for driving convoy from an agent):

```
claude plugin marketplace add grimaldost/convoy
claude plugin install convoy@convoy
```

As a **CLI**:

```
uv tool install git+https://github.com/grimaldost/convoy
```

(or clone and `uv sync` for development). Either CLI route installs the
`convoy` command, aliased `cvy`; the plugin route installs only the two MCP
tools.

## Quickstart (CLI)

```
convoy init demo          # scaffold a runnable starter series
cd demo/workspace
convoy validate ../series.toml   # free preflight: spec, DAG, paths, assets
convoy run ../series.toml        # the real thing: spawns one agent, gates, integrates
```

The starter series implements one trivial PR under a $1 budget with one
blocking check, so the first run costs cents. Afterwards, look at:

- `demo/outputs/spawns.jsonl` — the telemetry ledger (economy + gate events);
- the workspace's `integration` branch — the merged result.

`convoy run` uses the current directory as the scored workspace — run it from
the workspace, pointing at the series file.

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

The plugin exposes two tools so a coding agent can drive a series without
shelling out:

- **`convoy_init(directory)`** — scaffold the starter series and return the
  paths.
- **`convoy_run(series_file, workspace, dry_run=false, config_isolation=true,
  reset=false)`** — run a series and return a structured summary: outcome,
  exit code, per-spawn economy totals, and a per-PR gate view, with the full
  trace referenced by path. `dry_run=true` preflights for free; `reset=true`
  resets the workspace to base first (CLI: `--fresh`).

`convoy_run` blocks for the whole series (minutes to hours). For long or
autonomous runs, use the CLI in a background shell — same engine, and the
telemetry file is the progress feed. Every argument, the result envelope, cost
and latency, and when *not* to use convoy:
[skills/convoy/SKILL.md](skills/convoy/SKILL.md).

## CLI reference

| Verb | What | Notable flags |
|------|------|---------------|
| `convoy validate <series.toml>` | Free preflight (no git mutation, no spawn) | |
| `convoy run <series.toml>` | Run the series from the current workspace | `--fresh` (reset to base, delete prior series branches first), `--quiet`, `--no-config-isolation` |
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

Design docs: [docs/design/](docs/design/) (overview, gate, formats, serving).
Decision records: [docs/adr/](docs/adr/README.md). Invariants:
[docs/GUARDRAILS.md](docs/GUARDRAILS.md). Docs map:
[docs/README.md](docs/README.md).

## Development

```
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
