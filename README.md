# convoy

Governed, measurable multi-PR execution: decompose work into a series of
PR-sized tasks, drive a coding agent to implement each under budget, gate the
result against a quality check, integrate the branches, and record per-spawn
economy.

Self-contained and general-purpose. Status: **v1 (headless MVE)** — see
[docs/design/](docs/design/) and
[docs/plans/v1-build-plan.md](docs/plans/v1-build-plan.md).

## Use it from an agent (Claude Code plugin)

convoy ships as a Claude Code plugin exposing two MCP tools — `convoy_run` and
`convoy_init` — so a coding agent can run a governed series without shelling out.
Install from GitHub (no clone; `uv` must be installed):

```
claude plugin marketplace add grimaldost/convoy
claude plugin install convoy@convoy
```

- **`convoy_init(directory)`** — scaffold a runnable starter series.
- **`convoy_run(series_file, workspace, dry_run=false, config_isolation=true)`** —
  run a series (implement → gate → repair → integrate) and return a structured
  economy + gate summary. `dry_run=true` pre-flights it for free.

`convoy_run` spawns a subprocess `claude -p` per PR, so run co-located with an
authenticated Claude Code seat. Depth — every argument, the result envelope, cost and
latency, and when not to reach for it — is in
[skills/convoy/SKILL.md](skills/convoy/SKILL.md).

## Use it from the shell (CLI)

Installed as `convoy` (alias `cvy`): `convoy init <dir>` scaffolds a starter series,
`convoy validate <series.toml>` pre-flights it, and `convoy run <series.toml>` runs it
from the current git workspace.
