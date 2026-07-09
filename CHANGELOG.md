# Changelog

All notable changes to convoy are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project is pre-1.0,
so changes accumulate under **Unreleased** and are cut into tagged releases.

An addition to a public protocol a consumer keys on — a new process exit code, a new
telemetry `outcome` / `error_kind` value, event, or field, or a new series.toml key — is
marked
**(consumer-affecting)** even though it is additive, so a tool driving convoy as an
engine knows to sync rather than silently mis-handle the new value. See the versioning
discipline in [docs/design/02-formats.md](docs/design/02-formats.md).

## [Unreleased]

### Added

- **Contributor and agent governance.** `AGENTS.md` is the canonical playbook for
  working on the repo (`CLAUDE.md` now redirects to it); `docs/GUARDRAILS.md`
  states the non-negotiable invariants, each naming its mechanical enforcer — with
  a new architecture test (`tests/test_architecture.py`) enforcing the
  core→interface import boundary; `CONTRIBUTING.md` adds setup, workflow, and the
  release discipline (a change is done only when a tagged release serves it);
  `docs/adr/` records the five founding decisions plus the feedback-tracking
  decision (ADR-0006); `docs/README.md` maps the docs; a PR template carries the
  checklist.
- **`docs/design/03-serving.md`** — design doc for the serving layer (run service,
  MCP stdio server and tools, result envelope, config isolation, plugin packaging,
  subprocess hygiene, CLI↔MCP parity), which postdated the founding docs.
- **`docs/backlog.md`** — the tracked improvement ledger fed by feedback triage.
  Raw feedback reports and triage passes are now local-only
  (`docs/feedback/.gitignore`); decisions and the buildable backlog are what
  history carries (ADR-0006).

- **Seat and infra halts are diagnosable and preflighted.** *(consumer-affecting: adds an
  `output_tail` field to `spawn_complete` lines and a `seat` pre-flight problem `kind` a
  caller may branch on.)* Two production runs halted on an expired seat with telemetry
  showing only `exit_code: 1, $0` — the operator had to re-run the spawn by hand to see
  `Not logged in`. Two changes close that:
  - `spawn_complete` lines now carry **`output_tail`** — the last 2 KB of the spawn's
    combined stdout+stderr, populated only on a non-`ok` classification (`''` on ok
    lines) — so the halt reason is on the telemetry line itself (`core/telemetry.py`,
    `interface/drivers/headless.py::_record_spawn`).
  - A real run now starts with a **seat probe**: one minimal, tool-less, budget-capped
    ($0.05, unmetered) spawn through the same credential-only config and resolved model
    the scored run will use, before the `--fresh` reset or any branch is staged. An
    `infrastructure` classification (expired seat, usage limit) or a CLI that cannot
    start raises a located `kind: "seat"` pre-flight problem and the run stops with zero
    side effects (`interface/seat_probe.py`, wired in `interface/run_service.py`;
    `dry_run` never spawns, probe included).
- **Optional per-check `repair_hint` in `[[checks]]` — the repo's own repair recipe,
  briefed to the fix spawn.** *(consumer-affecting: a new optional series.toml key an
  author may rely on — an older engine parses a series that sets it but silently ignores
  the hint.)* A check may declare a command or one-line instruction (e.g. its generated-
  artifact regeneration script); when THAT check goes red, the fix brief carries the hint
  verbatim under the failing check's line, so whether the repair lands no longer depends
  on the fix agent inferring the recipe from the failure text (`core/spec.py`,
  `interface/drivers/headless.py::_fix_brief`, `docs/design/02-formats.md`,
  `skills/convoy/SKILL.md`).
- **`convoy run --fresh` / `convoy_run(reset=true)` — opt-in workspace reset for a clean
  re-run.** Before staging, it checks out the base branch, deletes the integration branch and
  every PR branch the series names, and lets the run recreate them — so a completed or halted
  run can be re-run without the manual git surgery a leftover branch otherwise forces. Off by
  default: without it, a leftover branch still fails loud exactly as before (`interface/git.py`
  `Git.reset_to_base`, threaded through `interface/run_service.py`, `interface/cli.py`, and
  `interface/mcp/server.py`).
- **A workspace lock so concurrent runs fail loud instead of corrupting the tree.**
  *(consumer-affecting: adds a `busy` MCP `error_kind` value a caller may branch on.)* A run now
  holds an exclusive lock (`<workspace>/.git/convoy-run.lock`, out of the tracked tree) from
  after a clean pre-flight through the end of the run; a second `convoy run` against the same
  workspace raises `WorkspaceBusyError` (CLI: exit `usage`; MCP: `error_kind: "busy"`) rather
  than interleaving git operations. Released on both normal and error exit
  (`interface/workspace_lock.py`, wired in `interface/run_service.py`).

### Changed

- **README rewritten** for first contact: how a run works, install (plugin + CLI),
  a CLI quickstart, a trimmed real series exemplar, CLI reference, the MCP tool
  signatures (including the previously undocumented `reset` argument), telemetry,
  adoption notes, architecture, and development pointers.
- **`skills/convoy/SKILL.md` brought current and extended**: documents
  `convoy_run`'s `reset` argument and the `--fresh` re-run path (replacing the
  manual-surgery instructions) with the honest reset scope (branches only — a
  budget/infrastructure halt's uncommitted debris needs a hand clean), the `busy`
  `error_kind`, budget-calibration guidance (a `fix` budget scales with repair
  complexity, not the impl estimate), the supported long-run pattern (the MCP
  call blocks; use the CLI in a background shell), and a new "Adopting convoy in
  an existing project" section with the deliberate non-features.
- **Design docs resynced with shipped code**: `00-overview.md` repo-layout map
  regenerated (serving-layer modules were missing) and the spawn Protocol/impl
  split corrected; the `oracles/` committable-asset convention recorded as the
  resolution of the open independence-asset-home decision in `02-formats.md`
  (worked example updated), `00-overview.md`, and `01-gate.md`; series.toml keys
  added to the consumer-affecting enumeration in `02-formats.md` and this file's
  header, matching shipped practice.
- **`pyproject.toml` metadata**: license (Apache-2.0), authors, keywords,
  classifiers, and project URLs.
- **`pr_skipped.reason` no longer implies a dependency edge.** Wording changed from
  `upstream <id> halted (<cause>)` / `upstream <id> blocked` to
  `series halted at <id> (<cause>) before this PR started` — "upstream" read as a DAG
  edge, but the skip is sequence-positional: every PR after the halt is skipped,
  dependent or not. The field is documented free-form (`02-formats.md`); a consumer that
  grepped `upstream` should key on the parenthesised cause tag instead
  (`interface/drivers/headless.py`).

### Fixed

- **A Windows locale default can no longer crash or garble a run — UTF-8 is pinned at
  every text boundary.** Gate-check and git subprocess output, the driver's prompt read,
  and the CLI's series-file read all decoded via the locale default (cp1252 on Windows),
  so one agent-produced byte in `{0x81, 0x8D, 0x8F, 0x90, 0x9D}` raised
  `UnicodeDecodeError` and killed the run after its green PRs. Subprocess decoding now
  follows one policy — `TEXT_ENCODING`/`TEXT_ERRORS` (UTF-8, replace) in
  `interface/proc.py`, applied in `run_with_timeout` and `Git._run`; the prompt read pins
  UTF-8 with replacement (mid-series, degrade beats halt); the series read pins UTF-8
  strict and a legacy-encoded file exits as a usage error, not a traceback. Both entry
  points also reconfigure stdout/stderr to UTF-8-with-replacement
  (`interface/streams.py`), so convoy's own narration cannot raise `UnicodeEncodeError`
  on a cp1252 stream. The `PLW1514` (unspecified-encoding) lint rule is enabled to keep
  every future file-read site explicit; operators no longer need a standing
  `PYTHONUTF8=1`.
- **Spawn economy no longer under-reports turns to zero.** When the terminal
  `result` stream event omits or mistypes `num_turns`, the per-spawn economy now
  falls back to the assistant turns counted during the run rather than recording
  `0` — the assistant-turn fallback previously ran only when no `result` event
  arrived at all (`interface/headless_spawn.py`).
- **A budget-capped spawn is classified `budget`, not `infrastructure`, when its
  partial output mentions a usage phrase.** Classification is now explicitly
  ordered so the authoritative `error_max_budget_usd` subtype beats a weaker
  agent-authored result-text signal; the CLI's own stderr signature still takes
  precedence and overrides a budget cap (`interface/headless_spawn.py`).

## [0.1.1] - 2026-07-04

Fixes found by the 0.1.0 install verification (a blind-agent probe passed the docs, and
the smoke-call-through-the-installed-plugin step caught the blocker below).

### Fixed

- **MCP tools no longer hang the client when they shell out (the blocker).** Under a stdio
  MCP server, a `git` subprocess that inherited the server's JSON-RPC stdin — or left a
  Git-for-Windows background daemon (fsmonitor / auto-maintenance / auto-gc) holding an
  inherited pipe — kept `subprocess` from ever seeing EOF, so `convoy_init` completed its
  scaffold yet never returned its result, and a real `convoy_run` (which drives git and
  `claude -p`) would hang the same way. Every subprocess convoy spawns now runs with
  `stdin=subprocess.DEVNULL`, and every `git` invocation is passed
  `-c core.fsmonitor=false -c maintenance.auto=false -c gc.auto=0` to suppress those
  daemons (`interface/proc.py` `GIT_HERMETIC_FLAGS`, applied in `interface/git.py`,
  `interface/scaffold.py`, and `interface/proc.py::run_with_timeout`). A new integration
  test (`tests/test_mcp_stdio_integration.py`) drives the tools over a **real** stdio server
  subprocess and asserts they return — the unit tests call the coroutines directly and could
  not catch this.

### Changed

- **`[review].blocking` is now optional (default `false`).** It is reserved for an optional
  blocking LLM self-review the v1 headless driver does not run, so requiring it forced
  authors to set a field with no v1 effect (and read as contradicting `[[checks]].blocking`).
  The deterministic `[[checks]]` gate remains the sole merge arbiter (`core/spec.py`,
  `docs/design/02-formats.md`, `skills/convoy/SKILL.md`). Additive/loosening — existing
  series that set it still parse.
- **A could-not-start `convoy_run` result now carries an `error_kind`** (`spec` |
  `governance` | `git` | `filesystem`) alongside the human-readable `error`, so an agent can
  branch on the failure class instead of parsing a string (`interface/mcp/server.py`).
  Additive.

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
