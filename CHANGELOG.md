# Changelog

All notable changes to convoy are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project is pre-1.0,
so changes accumulate under **Unreleased** and are cut into tagged releases.

## [Unreleased]

## [0.1.0] - 2026-07-04

First tagged release. Bundles the v1 headless engine with an agent-facing serving
layer, so a coding agent can discover and drive a governed multi-PR series through
MCP tools rather than shelling out to the CLI.

### Added — agent serving

- **`convoy_run` + `convoy_init` MCP tools and a Claude Code plugin.** A local stdio
  MCP server (`interface/mcp/`, launched by `python -m convoy.interface.mcp`) exposes
  two tools mirroring the `convoy run` / `convoy init` CLI verbs:
  - `convoy_run(series_file, workspace, dry_run=false, config_isolation=true)` runs a
    series through the headless engine and returns a structured summary — outcome,
    exit code, per-spawn economy totals, and a per-PR gate view — with the complete
    per-line trace referenced by path (`telemetry_path`), never inlined. `dry_run`
    pre-flights the series for free (no git mutation, no spawn, no spend).
  - `convoy_init(directory)` scaffolds a runnable starter series and names the paths
    to hand to `convoy_run`.
  The repository is itself the plugin marketplace (`.claude-plugin/plugin.json` +
  `marketplace.json`): install with `claude plugin marketplace add grimaldost/convoy`
  then `claude plugin install convoy@convoy`. A reference skill lives at
  `skills/convoy/SKILL.md`, documenting every tool argument, the result envelope,
  cost/latency, when not to use it, setup, and the full series.toml schema (so an agent
  can author and tune a series, not only run one). The agent-facing surface was gated by a
  two-probe blind test — fresh agents given only the tool schemas + skill — which drove the
  series.toml schema and several result-envelope clarifications into the docs.
- **`run_series_headless()`** (`interface/run_service.py`): the request-level
  operation extracted from the `convoy run` CLI — pre-flight, output-dir creation,
  credential-only config isolation, and engine wiring — callable off any event loop.
  It raises `PreflightError` / `GovernanceError` / `GitError` / `OSError` rather than
  exiting, so the CLI and the MCP tool run one tested path and each maps failures to
  its own surface (an exit code, or a structured result).

### Changed

- `convoy run` now delegates to `run_series_headless`; behavior and exit codes are
  unchanged (the CLI test suite passes with only its monkeypatch targets moved to the
  shared service).
- `mcp>=1.28.1` is now a runtime dependency (the stdio server SDK).

### Baseline — v1 headless engine

The engine this release serves: a headless driver that stages on a base branch,
walks a `depends_on` DAG of PRs, spawns a coding agent to implement each under pinned
per-phase governance (model/effort/permission/budget/tools), gates the result against
`[[checks]]` with an optional independent lane, runs a bounded fix loop on a blocking
red, integrates green branches, and writes append-only per-spawn economy telemetry
(versioned `schema_version = 1`). Credential-only config isolation, whole-process-tree
kill on timeout, and budget-classified halts protect the scored tree and the operator
environment. Design: `docs/design/00-overview.md`, `01-gate.md`, `02-formats.md`.
