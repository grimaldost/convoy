# convoy — agent playbook

convoy is a governed, measurable multi-PR execution engine. This file is the
canonical playbook for any coding agent (or human) modifying this repository.
`CLAUDE.md` and any other per-tool entry files redirect here so there is exactly
one source of truth.

**Audience routing.** If you are *using* convoy to run a series, read
[skills/convoy/SKILL.md](skills/convoy/SKILL.md) instead — it documents the tools,
the series.toml schema, and the result envelope. This file is for *changing*
convoy.

## Read order

1. This file.
2. [docs/GUARDRAILS.md](docs/GUARDRAILS.md) — the non-negotiable invariants and
   what enforces each one.
3. [docs/design/00-overview.md](docs/design/00-overview.md) — architecture and
   concepts (then 01-gate, 02-formats, 03-serving as the task needs).
4. [docs/backlog.md](docs/backlog.md) — the improvement ledger; if your task ships
   a row, update its status in the same change.

Conflict policy: if guidance conflicts, `GUARDRAILS.md` wins. If docs and code
diverge, code wins — and the divergence is a bug to fix in the same change.

## Commands

```
uv sync                                                               # install deps
uv run ruff check src tests && uv run ruff format --check src tests   # lint + format
uv run ty check src                                                   # type check
uv run pytest                                                         # tests
```

All four must pass before a PR is ready; CI runs the same set.

## Architecture

Functional core / imperative shell:

- `src/convoy/core/` — pure, no I/O: spec parsing, DAG, gate verdict, governance,
  telemetry model, pricing, preflight rules.
- `src/convoy/interface/` — everything that touches the world: the spawn,
  gate-runner, and reporter seams behind `typing.Protocol` ports, concrete git
  and telemetry-writer adapters, the CLI and MCP surfaces over one shared run
  service, and the driver that wires them.

`core/` imports nothing from `interface/` (enforced —
see [docs/GUARDRAILS.md](docs/GUARDRAILS.md)). New seams get a `Protocol`, not a
concrete dependency. Type everything; `ty` must pass.

## Style

- Python 3.14; single quotes for code, double quotes for docstrings
  (ruff-enforced).
- Tests live in top-level `tests/`, never in `src/`; roughly one test module per
  source module.
- Plain, understated prose in docs, comments, and names — no rhetorical flourish.
- The project is self-contained and general-purpose: **no references to any other
  tool or project** in code or docs.

## Process

- Small diffs, one concern per PR — split if the goal has "and" in it.
- Behavior changes carry tests; every bugfix leaves a regression test that fails
  without the fix.
- Docs are part of the change, not an afterthought: a PR that changes behavior
  updates the docs that describe it in the same PR.
- `CHANGELOG.md` (Keep a Changelog, pre-1.0 `[Unreleased]`) gets an entry for any
  notable change. An addition to a public protocol a consumer keys on — a new exit
  code, telemetry `outcome`/`error_kind` value, event, field, or series.toml key —
  is marked **(consumer-affecting)** even when additive. See
  [docs/design/02-formats.md](docs/design/02-formats.md).
- Decisions with lasting consequences get an ADR in
  [docs/adr/](docs/adr/README.md) — short, four sections, in the same PR as the
  change when possible.

## Git conventions

- Conventional commit subjects (`feat:`, `fix:`, `docs:`, `test:`, `chore:`),
  imperative mood, body explains the why.
- No AI/tool attribution trailers or lines in commits, PR bodies, or docs.
- Branch names: `<type>/<short-slug>` (e.g. `fix/windows-locale-decode`).

## Feedback loop

Dogfooding feedback reports land in `docs/feedback/` (local-only, untracked);
periodic triage passes promote clusters into the tracked
[docs/backlog.md](docs/backlog.md). Build from the ledger — each row names its
change and home precisely enough to build without the source reports. A shipped
row is *done* only when a tagged release serves it (see
[CONTRIBUTING.md](CONTRIBUTING.md) for the release discipline).
