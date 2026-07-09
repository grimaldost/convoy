# Contributing

convoy is developed largely by coding agents working under the playbook in
[AGENTS.md](AGENTS.md); humans follow the same rules. This file adds the
mechanics: setup, workflow, and the release discipline.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/):

```
uv sync
```

## Quality gates

All four must pass locally before opening a PR; CI runs the same set:

```
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check src
uv run pytest
```

The unit suite spends no money and spawns no real agent — if it suddenly takes
much longer than ~30 s, a real spawn has leaked past the `tests/conftest.py`
guard; treat the runtime jump as a failure.

## Workflow

Branch from `main` (`<type>/<short-slug>`, e.g. `fix/windows-locale-decode`)
and follow the process and git conventions in [AGENTS.md](AGENTS.md) — that is
the single statement of the PR discipline (one concern per PR, tests with
behavior changes, docs and CHANGELOG in the same change, the
**(consumer-affecting)** marker, ADR and backlog updates, conventional commit
subjects, no attribution trailers). The PR template carries the checklist; CI
runs the same gates as above.

## Release discipline

Pre-1.0, changes accumulate under `[Unreleased]` and are cut into tagged
releases. **A shipped change is not done until a tagged release serves it** —
the plugin marketplace serves tags, so anything sitting in `[Unreleased]` is
invisible to every installed consumer, and production keeps re-discovering
already-fixed defects.

Cadence: cut a release after each backlog build round (a batch of
`docs/backlog.md` rows landing). To cut:

1. Move `[Unreleased]` into a new `## [0.x.y] - <date>` section in
   `CHANGELOG.md`.
2. Bump `version` in `pyproject.toml` and `.claude-plugin/plugin.json`
   (`.claude-plugin/marketplace.json` carries no version field).
3. Tag `v0.x.y` and push the tag.

## The feedback loop

Dogfooding and consumer feedback reports land in `docs/feedback/` — deliberately
**local-only** (untracked; see the `.gitignore` there). Periodic triage passes
cluster the reports by cause, verify mechanisms against source, and promote what
clears the gate into the tracked [docs/backlog.md](docs/backlog.md) ledger. The
ledger is the canonical record: each row is written so a maintainer can build it
without the source reports. Decisions promoted along the way become ADRs or
guardrails, which are tracked.
