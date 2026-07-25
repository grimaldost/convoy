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

- **`convoy status` / `convoy_status` — ask a run how it is doing, including one still in
  progress.** *(consumer-affecting: a new CLI verb, a new MCP tool, and a new `state` key
  on the run envelope both surfaces return.)* `convoy_run` blocks for the whole series and
  the documented pattern for a long run is the CLI in a background shell — but nothing
  could then ask that run anything. Status reads only the append-only ledger, so it reports
  on a run **this process never started**, spends nothing, holds no state between calls,
  and never touches the workspace. Polling is cheap and safe.

  The envelope gains **`state`**, the field to branch on first:
  - `running` — no `run_complete` line yet, so `outcome` / `integrated` / `exit_code` are
    `null` and `economy` is a partial running total (what it has spent so far).
  - `finished` — the terminal fields are meaningful, exactly as from `convoy_run`,
    `halt` included.
  - `unknown` — nothing recorded under that id. Not an error: a run that has not written
    its first line yet is a legitimate thing to observe.

  A finished run's outcome is **rebuilt from the ledger**, not from a live `RunOutcome`:
  `run_complete` carries `outcome` and `integrated`, and the exit code follows from
  `outcome` by the published mapping in `docs/design/02-formats.md`. The absence of that
  line is itself the "still running" signal, which is what lets this work with no
  server-side state. `run_id` defaults to the most recent run in the ledger — run ids sort
  lexicographically by start time by construction, which is what makes "the latest run"
  answerable from a ledger that accumulates many (`interface/run_summary.py`,
  `interface/cli.py`, `interface/mcp/server.py`). Serves the polling half of backlog row
  T14b; the detached-launch half is now tracked separately as T14c.

- **A halted run now says where and why it stopped.** *(consumer-affecting: a new
  `classification` field on every `spawn_complete` line, a new `halt` object on
  `run_complete`, and a new `halt` key in the run envelope both surfaces return.)* The
  terminal record carried only `run_id` / `outcome` / `integrated`, so the first question
  a halt raises — which PR, in which phase, and how close to which cap — meant hand-reading
  the whole ledger. The cap itself was recorded nowhere at all.

  `run_complete` now carries **`halt`**: `null` on a clean run, else
  `{pr_id, phase, role, spend_usd, cap_usd}`. `role` is the spawn role that hit it
  (`implementation` / `fix`) or `gate` when the bounded fix loop was exhausted — a repair
  exhausting its own smaller ceiling is a different diagnosis from the implementation
  doing so, and the fix role's cap is what gets reported in that case. `spend_usd` /
  `cap_usd` are populated **only** for a `budget` outcome; they stay `null` for `blocked`
  and `infrastructure`, because naming a ceiling that did not cause the halt would point
  the reader at the wrong fix.

  Each `spawn_complete` line also carries **`classification`** (`ok` / `infrastructure` /
  `budget`) — the adapter verdict that drove the run's control flow all along. Without it
  a consumer had to infer the cause from `exit_code` plus the shape of `output_tail`, an
  inference that is wrong exactly when it matters, since a budget cut and an auth failure
  can both exit `1`.

  The envelope reads `halt` from the `run_complete` line rather than threading it through
  `RunOutcome`, keeping `RunOutcome` a control-flow value and the envelope reconstructible
  from the ledger alone (`core/telemetry.py`, `interface/drivers/headless.py`,
  `interface/run_summary.py`). Serves backlog row T12b.

- **`convoy run --json` — the run summary on stdout, as one JSON object.**
  *(consumer-affecting: new CLI flag, and stdout gains structured output on a verb that
  previously wrote nothing there.)* The folded envelope — outcome, exit code, economy
  totals, the per-PR view, and the `telemetry_path` holding the full trace — existed only
  on the MCP surface, so every CLI-driven measurement harness re-implemented the
  per-spawn fold over the raw `spawns.jsonl` itself. Off by default, so stdout stays
  empty for a caller that only reads the exit code, and progress narration stays on
  stderr either way. The exit code is unchanged: `--json` adds output, it does not
  replace the contract.

  Under `--json`, stdout carries exactly one JSON object **on every path** — including a
  run that could not start, which returns the same `outcome: "usage"` shape (with
  `problems`, or `error` plus `error_kind`) the MCP tool returns. A machine consumer needs
  the failure case to be parseable most of all; prose on stderr would force it to
  special-case exactly what it is trying to classify.

  This required lifting `summarize_run` and the `error_kind` classifier out of
  `interface/mcp/server.py` into a shared `interface/run_summary.py`. They were
  surface-bound by accident, not by coupling — one implementation is what keeps the two
  surfaces from reporting different totals for the same run, and there is a test asserting
  the CLI envelope equals the module's for one ledger. No behaviour change to the MCP tool
  (`interface/cli.py`, `interface/run_summary.py`, `interface/mcp/server.py`). Serves
  backlog row T20a.


### Fixed

- **A gate check's `detail` no longer opens with a warning convoy itself provoked.**
  Checks run in the scored workspace, which is not the environment convoy was launched
  from, so an inherited `VIRTUAL_ENV` pointing elsewhere makes a Python launcher announce
  an environment mismatch on stderr before the check has done anything. That mattered more
  than it looks: `_red_detail` prefers stderr, so the warning became the *first* thing in
  `detail` — and `detail` is exactly what the bounded fix loop re-briefs the repair spawn
  with, so a repair could be aimed at a non-problem while the real failure sat further
  down. Checks now run under a sanitized environment (`gate_env`) with `VIRTUAL_ENV`,
  `VIRTUAL_ENV_PROMPT` and `UV_PROJECT` removed; everything else is inherited unchanged,
  since a check legitimately needs `PATH` and the repo's own tooling variables. Stripping
  at the source beats filtering the text downstream, which would rot with every launcher
  release. Same posture as `_ENV_STRIP` in `headless_spawn` — that one keeps billing and
  routing overrides out of a scored spawn; this is its check-environment counterpart
  (`interface/gate_runner.py`). Serves backlog row T13a.

## [0.4.0] - 2026-07-25

### Added

- **`convoy run --resume` / `convoy_run(resume=true)` — continue a halted run instead of
  paying for it twice.** *(consumer-affecting: a new CLI flag and MCP tool argument, a new
  `resume` pre-flight problem `kind`, and a new `pr_skipped.reason` value — `already
  integrated before this resume` — that a consumer folding a resumed run must distinguish
  from the halt reasons, because "done" and "never ran" are opposite outcomes.)*

  After any halt the integration branch provably retains every green merge, so the work is
  already on disk; re-running re-spawned it anyway. Measured against this corpus,
  implementation spawns run ~$0.20–0.90 each, so a 4-PR series halting at PR4 discarded
  roughly $0.6–2.7 of verified work per attempt — and an agent-CLI auth session that
  expires mid-run makes that halt class recur by construction on any long series, not just
  on a git flake.

  `--resume` checks out the existing integration branch instead of creating one, skips
  every PR whose work it already contains, and re-attempts the rest. **Containment alone
  is the wrong test**: a PR branch whose implementation committed nothing points at the
  *same commit* as the integration branch, which `merge-base --is-ancestor` reports as
  contained — skipping it would silently drop a PR that never landed and still report
  `completed`. Because the driver always integrates with `merge --no-ff`, a genuinely
  merged branch is a **strict** ancestor, and that is the signal (`Git.is_merged_into`). A
  PR branch carrying unmerged commits is a failed attempt: it is deleted and re-attempted
  from the current integration state rather than built on.

  Two incoherent requests are rejected in pre-flight, before the lock, the seat probe, or
  any git mutation: `--resume` with `--fresh` (fresh deletes the branch resume continues
  from), and `--resume` with no integration branch (falling back to a full run would be
  friendlier but far more expensive when the real cause is a wrong workspace). A first run
  takes no flag (`interface/drivers/headless.py`, `interface/git.py`, `interface/cli.py`,
  `interface/run_service.py`, `interface/mcp/server.py`). Serves backlog row T11a.

- **`convoy clean <series.toml>` — a destructive recovery verb for a halted or killed
  run.** In order: discard uncommitted changes to tracked files, delete untracked files
  and directories (ignored files are kept — a local venv survives), check out the base
  branch, delete the series' integration and PR branches, and remove a stale run lock.
  `--dry-run` / `-n` prints exactly what that means for this workspace and changes
  nothing; the preview is built from git's stable porcelain status rather than parsing
  `git clean`'s prose, so it reads the same under any locale.

  This is deliberately not `run --fresh`. `--fresh` acquires the workspace lock and pays
  for a seat probe *before* it resets anything, so it cannot clear a lock left by a
  hard-killed run — the exact situation recovery is needed in. `clean` starts no run: no
  lock, no probe, no spend. Recovering by hand was otherwise the only option, and one
  campaign needed it five times (`interface/cli.py`, `interface/git.py`
  `discard_changes` / `clean_untracked` / `status_porcelain` / `branch_exists`,
  `interface/workspace_lock.py` `remove_stale_lock` / `lock_path`). Serves backlog row
  T10a.

- **`convoy run` / `convoy validate` take `--workspace DIR` (`-w`), defaulting to the
  current directory.** The workspace was implicitly the process working directory, which
  is not discoverable from `--help` and does not survive being run from anywhere else —
  four separate reports across four campaigns hit it. The default is unchanged, so every
  existing invocation behaves identically; the flag makes the coupling explicit and lets
  either verb target a tree the shell is not sitting in, mirroring the `workspace`
  argument the MCP tool always took explicitly. A path that is not an existing directory
  is now a located usage error instead of a confusing git or filesystem failure later
  (`interface/cli.py`). Serves backlog row T16a.

## [0.3.0] - 2026-07-25

### Added

- **Phase-scoped `[[checks]]` — a check may declare the PR phases it gates.**
  *(consumer-affecting: a new optional series.toml key `[[checks]].phases`, and a new
  `phases` pre-flight problem `kind` a caller may branch on. An older engine rejects a
  series that sets the key outright.)* The gate ran the whole check tuple after every PR,
  so an **incremental** series was unrunnable: if PR1 lands a core slice and PR2–PR4
  extend it, the full suite is red until the last PR and PR1 cannot pass its own gate.
  That forced every real series into one fat PR or per-PR full-suite green, which left
  `depends_on` — the reason the engine walks a DAG at all — with no workable incremental
  use case.

  A check with no `phases` gates every PR, so a series that scopes nothing is
  bit-for-bit unchanged. A check that names `phases` gates only the PRs whose
  `[[prs]].phase` is among them. Scoping decides *which* checks run and nothing else:
  whatever is selected is judged under the existing rules, a blocking red still blocks,
  and a PR's checks resolve once so the fix re-gate is judged by exactly the checks that
  failed it. `[[prs]].phase` — parsed and serialized since v1 but read by nothing — is
  now load-bearing. A `phases` tag no PR declares is a pre-flight problem, because a typo
  would silently reduce the check to gating nothing, and a check that never runs is worse
  than a missing one (ADR-0008; `core/spec.py`, `core/gate.py`, `core/preflight.py`,
  `interface/drivers/headless.py`, `docs/design/01-gate.md`, `02-formats.md`,
  `skills/convoy/SKILL.md`).

- **A non-blocking advisory channel in pre-flight.** *(consumer-affecting: adds an
  `advisories` list to the `convoy_run(dry_run=true)` result.)* Phase scoping makes it
  possible for a PR to end up with no blocking check, so it integrates unverified. That
  is a legitimate authoring choice (a docs-only PR), so it does not block the run — but
  it is silent and expensive to discover afterwards. Pre-flight had nowhere to put a
  non-fatal remark: every `Problem` is fatal and both surfaces treat a non-empty list as
  failure. Pre-flight now returns a `PreflightReport` carrying `problems` and
  `advisories` side by side; only `problems` decides runnability. `Advisory` is a
  distinct type rather than a severity flag on `Problem`, so no surface can turn advice
  into a failure — or lose a failure among advice — by accident.

  **`convoy validate` can now write to stderr and still exit `0`**: a caller that treated
  any stderr output as failure must key on the exit code instead. On the MCP surface
  `advisories` is always present (empty when there is nothing to say) and never affects
  `ok` or `outcome` (`core/preflight.py`, `interface/preflight_probe.py`,
  `interface/cli.py`, `interface/mcp/server.py`, `interface/run_service.py`).

### Fixed

- **`docs/design/03-serving.md` is now actually in the repository.** Six references across
  five tracked files point at it — the 0.1.2 notes below list it as added, `AGENTS.md`
  puts it in the canonical read order, `docs/README.md` maps it, `docs/adr/0001` cites it,
  and `00-overview.md` links it twice — but the file was never committed on any branch and
  is not ignored, so every clone at 0.1.2 and 0.2.0 carries six dangling references to a
  design doc it does not have. Committed, and resynced with 0.2.0
  in the same pass: the seat probe covers **every distinct model** the run can spawn on
  (not one), with the `kind='seat'` problem located at the section that declared the
  failing model and probing stopping at the first dead one; and the result envelope's
  per-PR view carries **`effective_model`**.

### Changed

- **The `independent` gate lane now cites convoy's own measurement**
  (`docs/design/01-gate.md`, `skills/convoy/SKILL.md`). The doc previously rested on an
  external study. An in-house blind-implementer trial (the implementer sees only the spec;
  a held-out acceptance suite it cannot reach is the gate) corroborates every existing
  claim — the lane is bounded, opt-in, and **null at the strong/default tier** — and adds
  the weak-tier magnitude (gate red 3/3, bounded fix loop recovered 3/3, three `fix`-role
  spawns in the ledger, against a no-gate control that shipped failing trees 3/3). It also
  makes explicit a usage condition the doc previously only implied: when the acceptance
  tests are visible in the workspace the gate is **redundant, not vacuous** — the
  implementer runs them and self-corrects — so the lane's correctness value requires a
  blind implementer. Three trials per cell: mechanism evidence, not an effect size.

## [0.2.0] - 2026-07-15

### Added

- **Optional per-PR `model` / `tier` / `effort` in `[[prs]]` — a PR's own governance,
  falling back to `[governance]`.** *(consumer-affecting: three new optional series.toml
  keys, and the spec parser no longer rejects them — a series may now vary the model per
  PR, so a consumer that relied on the parser rejecting these keys to hold every PR on one
  model must pin it itself; an older engine rejects a series that sets them outright.)* A
  `[[prs]]` table may set its own `model`, `tier`, and `effort`. Absent means the PR
  inherits `[governance]` — behaviour is bit-for-bit unchanged for a series that sets none
  of them. A PR that sets `model` **or** `tier` supplies both (its `(model, tier)` pair
  replaces the series pair, which is not consulted, so a series `model` never shadows a
  per-PR `tier`); both spawns of a PR — implementation and fix — resolve the same value.
  `[governance]` must still resolve a model even when every PR overrides it (it is the
  fallback and the audit baseline). The pre-flight now resolves every overriding PR's
  governance, so an unknown per-PR tier fails `convoy validate` instead of raising mid-run
  after earlier PRs already spent money. `budget` / `budgets` stay rejected per PR —
  budgets are per-role (`implementation`/`review`/`fix`), so a per-PR scalar has no role to
  bind to. (ADR-0007, supersedes ADR-0005; `core/spec.py`, `core/governance.py`,
  `core/preflight.py`, `interface/drivers/headless.py`, `docs/design/02-formats.md`,
  `skills/convoy/SKILL.md`.)

- **The per-PR model is in the run summary.** *(consumer-affecting: adds an
  `effective_model` field to each `prs[]` entry in the `convoy_run` result.)* The model a PR
  ran under was already on disk on every `spawn_complete` line, but the result envelope
  dropped it, so answering "which model ran this PR" meant hand-reading the raw trace.
  `prs[]` entries now carry **`effective_model`** — the model the PR's implementation spawn
  actually ran under, `null` for a PR that never spawned (skipped) — joinable against the
  per-PR `gate` already in the envelope, so "which model ran this PR, and did it gate green
  at attempt 0" is answerable from the result itself (`interface/mcp/server.py`).
  A PR's spawns normally share one model; where an implementation and a fix spawn diverge,
  the field reports the implementation spawn's — the spawn the gate judged — and the
  per-spawn breakdown stays in the trace at `telemetry_path`.

  The signal is asymmetric, and worth stating plainly: it can show that a model failed to
  clear the gate, never that a cheaper one would have sufficed.

### Changed

- **The seat probe now covers every distinct model the run can spawn on**, not just the
  `[governance]`-resolved one — one probe per distinct model (the series model plus any
  per-PR override), in first-PR-seen order, stopping at the first dead model. Not
  consumer-affecting: it adds no key, event, field, exit code, or `outcome`/`error_kind`
  value, and the `kind='seat'` pre-flight problem already exists. The only visible change
  is pre-flight cost and coverage — $0.05 per distinct model (usually 1-3) instead of a
  flat $0.05 — so a per-PR model the seat cannot access fails in pre-flight rather than at
  that PR after branches were staged (`core/governance.py`, `interface/seat_probe.py`,
  `interface/run_service.py`, `skills/convoy/SKILL.md`).

## [0.1.2] - 2026-07-09

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

### Removed

- **`structlog` dropped as a runtime dependency.** It was declared but imported
  nowhere in `src/` — dead weight in every install. Removed from
  `pyproject.toml`; `uv.lock` re-resolved.

### Fixed

- **Two decode-boundary gaps at the serving layer.** A legacy-encoded (non-UTF-8)
  series file made `convoy_run` raise `UnicodeDecodeError` out of the tool call
  instead of returning the structured usage envelope (now `error_kind: "spec"`,
  matching the CLI path, which already handled it); and the scaffold's git
  children still decoded via the locale default, bypassing the
  `TEXT_ENCODING`/`TEXT_ERRORS` policy every other subprocess site follows
  (`interface/mcp/server.py`, `interface/scaffold.py`).

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
