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

### Removed

- **`core/pricing.py` and `apply_cost_fallback` are gone (consumer-affecting).**
  They substituted a token x local-price estimate whenever the provider reported
  `cost_usd == 0.0`, on the premise that subscription auth reports no cost. The
  premise is false and was measured so: `cost_estimated` was true **0 times across
  76 production spawns**, 0 of 22 more re-counted on 2026-09-05, and a direct check
  against the installed CLI on a subscription seat returns a real `total_cost_usd`.
  The module was also internally inconsistent — its docstring promised a
  conservative fallback while its default rate under-counted a frontier-priced model
  two-fold — and it was a second copy of a price list convoy had to keep in sync with
  a lineup it does not own. `cost_usd` is now always the provider's number.
  **`cost_estimated` stays in the telemetry schema, permanently `false`**: the schema
  is a public contract, and removing a key a consumer reads is worse than freezing
  one. A future zero-cost provider gets `cost_usd: null` and a consumer that decides,
  not a price table here.

### Added

- **`[governance]` rejects an unknown field (consumer-affecting).** The parser read
  only the keys it named and dropped the rest, so a series authored against a newer
  convoy would load, have the unread key silently ignored, and run every PR on
  whatever the built-in table resolves — a wrong run with plausible telemetry and no
  signal anywhere. It is now an allow-list, because the failure is always the key
  nobody thought to forbid, and the error names the near-miss (`'permision_mode'; did
  you mean 'permission_mode'?`) rather than sending the author to a schema doc.
  ADR-0005 already refuses an unknown per-PR governance key; this closes the same
  hole on the series block. A spec that relied on a typo being ignored now fails at
  load, which is the point.

### Changed

- **The `frontier` tier resolves to `claude-fable-5-1`**, and `DEFAULT_TIER_MODELS`
  is documented as the **floor** it always was, with a `LINEUP_RECONCILED` stamp. The
  stamp records when the upstream tier data was reconciled against the platform's
  model list, **not** when this file was edited: dating the edit would let a table
  copied from an already-stale source certify itself fresh, and an age check would
  then be measuring the stamp rather than the lineup. A series that resolves its own
  model never reaches this table; it exists so convoy installs and runs for someone
  with no access to whatever maintains a lineup, and it goes stale between releases
  by design. `skills/convoy/SKILL.md` says the same instead of restating the ids.

### Fixed

- The changelog gate (`scripts/changelog_gate.py`) no longer lets one commit's
  `Changelog: none (<reason>)` trailer exempt every other commit in the pushed range,
  and no longer accepts merely touching `CHANGELOG.md` — a deletion, or an edit that
  only rearranges text that was already there — as recording a change. The
  record-or-declare check is now judged per commit: a commit that changes the engine
  passes only if the PR's CHANGELOG diff adds at least one line that the same diff
  does not also remove once whitespace is collapsed, or that same commit carries the
  trailer. That rules out an appended blank line, a trailing space or a re-indent on
  an existing line, a CRLF conversion, and a reordering of existing bullets.
- The changelog gate stops skipping merge commits, and charges one only with its
  *resolution* — the content an automatic merge of its parents would not have
  produced, computed with `git merge-tree --write-tree` and diffed against the merge's
  own tree. A conflict resolution that edits `src/` now needs the same recording as
  any other commit, while a clean auto-merge is charged nothing: two branches editing
  one engine file in different hunks, and the synthetic `refs/pull/N/merge` that CI
  checks out once the base branch has moved, both merge without a human writing
  anything. Charging a two-parent merge needs git 2.38 or newer, and the gate fails
  naming the git it ran under rather than guessing on an older one, while a pair git
  refuses outright (unrelated histories) has no automatic merge to compare against
  and falls back to the combined diff instead of failing — an approximation that
  under-charges a resolution taking one root's file verbatim; an octopus merge
  is outside that scope and keeps the combined (`--cc`) diff.
- Judging the changelog gate per commit trades in a new false positive: an
  intermediate commit whose own diff touches the engine but is reverted later in the
  same range must still carry the trailer or a changelog line, even though the pushed
  range's net diff shows nothing for it — declare it with the trailer, same as any
  other commit.

### Security

- `cryptography` moves from 49.0.0 to 50.0.1, closing the high-severity advisory that
  covers `>= 44.0.0, < 50.0.0`. It reaches convoy transitively, through `pyjwt[crypto]`;
  only `uv.lock` changes. The alert had no pull request behind it because Dependabot was
  configured to watch GitHub Actions and nothing else, which `.github/dependabot.yml`
  now fixes for the Python dependencies as well.

## [0.12.0] - 2026-09-02

The gate becomes a hook, and a project can carry one. Written at cut time, over the
entries below as they stand: **this release is consumer-affecting** — a new command
(`convoy hook`) and two plugin-shipped hooks, a per-project spec (`.convoy/gate.toml`)
with discovery and a scaffold, a per-machine trust list the hooks require, `${CONVOY_*}`
expansion in check commands, `--brief`, and an optional `series_file` on `convoy_gate`.
Two blind reviews ran on the candidate; every blocker, high and medium they found is
closed here, and the two limits that remain are stated where they apply: an
asynchronous dispatch's residual red reaches the orchestrator only through the
subagent's own message, and a gate whose checks together outrun the hook's timeout is
killed silently. Smoked end to end in a real session: an asynchronous dispatch judged at
the subagent's stop, blocked once with the brief, repaired by the subagent itself, and
passed on the retry.

### Changed

- A literal `${...}` in a `[[checks]]` `run` or `asset` is no longer passed to the
  shell **(consumer-affecting)**: `${CONVOY_*}` names expand at load and every other
  braced reference is refused, so a spec that carried one now needs the variable set
  and named in the `CONVOY_` namespace. An expanded value carrying shell syntax is
  refused at load; the default oracles directory derived from the project name is
  sanitised before it can reach a command.
- `convoy_gate` lists `workspace` before `series_file` **(consumer-affecting)**, so the
  latter can default; parameters are keyword-addressed over the protocol. A discovered
  spec (no `series_file`) must be trusted on this machine, the standard the hook holds.
- `convoy gate --init` no longer trusts the project it scaffolds: the scaffold is red
  until edited, and arming is a second, deliberate act (`convoy gate --trust`).

### Added

- `convoy gate` and `convoy_gate` discover the project gate spec
  **(consumer-affecting)**. The series argument is optional on both surfaces: omitted,
  `$CONVOY_GATE_SPEC` is used when the launching process set it (a set but missing file
  is refused, never walked past), then `$CLAUDE_PROJECT_DIR/.convoy/gate.toml`, then
  `.convoy/gate.toml` in the workspace and each of its parents, and nothing found is a
  usage failure
  (`error_kind: spec`) naming where it looked. A project spec — one living at
  `.convoy/gate.toml` — loads with `CONVOY_ORACLES` defaulted to
  `~/.convoy/oracles/<project dir name>` when the caller has not set it, so the
  `${CONVOY_ORACLES}/...` references a scaffold writes resolve on a machine that never
  exported the variable; an explicit series file gets no default. The presence of the
  project spec is the per-project switch the hook keys on; a spec found outside
  `.convoy/` governs the workspace — trust, the hook log and the oracles default key
  on the workspace, not on the directory the file sits in. Over the MCP protocol
  the tool's parameters are keyword-addressed, so the reorder that makes `series_file`
  optional (`workspace` now first) changes no caller.
- `convoy hook` and the plugin-shipped hooks **(consumer-affecting)**. Installing the
  plugin now registers `hooks/hooks.json`, which runs `convoy hook` with the event JSON
  on stdin on two events. `SubagentStop` is the judge: when a subagent tries to finish,
  the project gate runs in the session's tree; a blocking red is exit 2 with the repair
  brief on stderr, which Claude Code hands to the subagent as the reason it may not
  stop yet — the implementer repairs its own work, the same shape as a governed run's
  fix spawn — once; on the retry (`stop_hook_active`) a residual red is recorded and
  the subagent may stop. A subagent whose transcript shows no mutating tool use is not
  gated. `PostToolUse` on `Agent` (or `Task`) is the messenger for synchronous
  dispatch: when the dispatch returns completed, the hook reuses the judge's verdict
  for that subagent from the log (or runs the gate when there is none) and on a
  residual red exits 2 with the brief, which Claude Code shows to the orchestrator as
  feedback on the completed tool call — its cue to dispatch a fix subagent. An
  asynchronous dispatch (`async_launched`, the Agent tool's default when
  `run_in_background` is unset — observed, not documented) is recorded, not gated, at
  the tool call; its subagent is still judged at its stop. The hook discovers the
  project spec the way `convoy gate` does and does nothing where none exists — the spec
  is the per-project switch, so the plugin arms nothing until a project opts in. Green:
  exit 0, no output, nothing in any model's context. A gate that cannot run is exit 2
  with a one-line reason, never a silent green. `[convoy-phase: <tag>]` in the
  subagent's brief scopes the gate on both legs; orchestrator feedback needs a
  synchronous dispatch (`run_in_background: false`). The judge reads the subagent
  transcript for the brief (string or block content), the model and the tool use —
  anything not on the read-only list (Read, Grep, Glob, web fetches, todo) counts as a
  write, so an MCP writer or a nested dispatch is gated; a gate that cannot run lets the
  subagent stop on the retry. The event is read as UTF-8 bytes whatever the locale. Each
  firing appends one JSON line to `.convoy/hook.log` — `leg` (judge / messenger),
  `event`, `outcome`, the hook's `exit_code`, `agent_id`, `agent_type`, `model` (from
  the transcript on the judge leg), `phases`, `stop_hook_active`, per-check facts
  (`exit_code`, `timed_out`, `detail`), `repair_brief`, `gate_ms`, `series_id`, `spec`,
  `spec_sha256`, `workspace`, `cwd`, `session_id`, `tool_use_id`, `convoy_version`,
  millisecond `ts` — the attestation an experiment counts from (count the judge's
  lines). The messenger reuses the judge's record keyed on session and agent, a
  read-only verdict as silence. A gate whose checks together exceed the hook timeout
  (1800 s) is killed by Claude Code and says nothing — keep the sum under it. Exit codes
  are the hook protocol's (0, 2),
  not convoy's (0, 1, 3). Config isolation keeps the hook out of every scored spawn.
  The hook executes a project's checks only where this machine trusts the project:
  `convoy gate --trust` records the project root and the hash of its spec in
  `CONVOY_HOME/hook-trust.toml` (default `~/.convoy/`, `[[projects]]` tables of `root`
  and `spec_sha256`); an untrusted project executes nothing and gets no file written
  into it, and a spec that changed since it was trusted is refused loudly (exit 2) —
  a cloned repository's gate file must not run commands on dispatch until the operator
  says so, and the implementer must not be able to rewrite the gate it is judged by
  (a new guardrail). A workspace a `convoy run` holds the lock on is refused. An
  explicit `convoy gate` on an untrusted project still runs, and says on stderr that
  the hook is not armed there. `CONVOY_HOME` overrides `~/.convoy`
  for the trust list and the default oracles home; `CONVOY_TRUSTED_ROOTS` (path-separated
  roots) lets the process that launches Claude Code — a harness, a CI job staging a
  fresh workspace — vouch for roots it cannot have listed in advance.
  The captured Claude Code 2.1.258 event payloads and one subagent transcript are
  committed as test fixtures, so the fields the hook reads are the protocol as sent,
  not as read.
- `convoy gate --init [--independent NAME]` **(consumer-affecting)**: scaffold the
  project gate spec at `.convoy/gate.toml` (plus `.convoy/.gitignore` for the hook
  log) from the toolchain found in the workspace — Python: the uv lockfile check, ruff
  lint and format, the type checker the pyproject names, pytest, under `uv run` when
  the project is uv-managed; Node: the `lint`, `typecheck` and `test` scripts; nothing
  detected: a `configure` placeholder that stays red until the checks are declared —
  as blocking, non-independent checks, with repair hints. The file's header says what
  that default is (the project's own suite, which an implementer can satisfy by
  self-report) and names the next step. `--independent NAME` also scaffolds a
  placeholder held-out oracle `NAME.py` under `CONVOY_ORACLES` (default
  `~/.convoy/oracles/<project dir name>/`) and declares it as a blocking independent
  check through `${CONVOY_ORACLES}`; the placeholder is red until written — the judge
  is appointed before the defendant, and the authoring guide now says so. Refuses to
  overwrite any target before writing anything. `core.spec.dump_gate_spec` serializes
  the gate-only shape it writes.
- `convoy gate --brief` and `convoy_gate(brief=true)` **(consumer-affecting)**: the
  compact envelope `{ok, outcome, repair_brief, convoy_version}` and nothing else, for
  a caller that must read the verdict inside a model turn — the four fields a repair
  decision needs, without a per-check list to skim past. Usage paths are unchanged.
- `[[checks]]` `run` and `asset` expand `${NAME}` from the environment at load
  **(consumer-affecting)**. Only the braced form expands — `$NAME` and `%NAME%` pass
  through untouched, so a command keeps its own shell syntax on either platform — and an
  unset name is a `SpecError` naming the field and the variable: a check whose oracle
  path cannot resolve on this machine is not runnable on this machine, and the loader
  says so instead of handing the shell a reference that expands to nothing. The
  convention it serves is `${CONVOY_ORACLES}`, the out-of-tree home for a project's
  held-out oracles, so a spec names its independent check's asset without baking one
  machine's path in. A spec that carried a literal `${...}` in `run` or `asset` before
  this change now needs the variable set. `repair_hint` is prose and is never expanded.

## [0.11.0] - 2026-09-01

The gate becomes something an orchestrator can consume without reading prose. Written at
cut time, over the entries below as they stand: **this release is consumer-affecting** —
the gate envelope gains two fields and `convoy validate` answers a new input class — and it
also closes a defect one of those changes shipped with (a broken series file validating as
a gate), found by a blind review after merge and fixed before this cut.

### Added

- The gate envelope carries `repair_brief` and `convoy_version`
  **(consumer-affecting)**. `repair_brief` is the failing-checks section — each blocking
  red's name, `detail` and declared `repair_hint`, plus the independence note — in the
  exact form the run's own fix loop appends to a fix spawn's brief, and `''` when the
  gate is green. It was previously private to the driver, so an orchestrator that ran
  the gate standalone and repaired the red itself had to reassemble the same text from
  the per-check fields; the section is now `core.gate.repair_brief`, one pure function
  both paths read. `convoy_version` names the engine that produced the verdict, so a
  stored envelope stays interpretable as the shape grows.

- `convoy validate` accepts a gate-only file **(consumer-affecting)**. `validate` was
  bound to `load_series`, so the minimal `[series] id` + `[[checks]]` file `convoy gate`
  documents as valid input failed with `missing required section [branches]` — the one
  surface that could have told a gate-only adopter their file was sound instead told
  them it was a broken series. It now falls through to `load_gate_spec` when
  `load_series` refuses and the file carries no orchestration section, applies the two
  refusals the gate decides from the spec alone (the selection must contain a blocking
  check; every blocking independent check must back its isolation), and prints `ok
  (gate-only)` on stdout. Two surfaces a consumer keys on move for one input class,
  gate-only files: stdout gains a second success token beside the contracted `ok`, and
  a valid gate-only file now exits `0` where it exited `3`. Everything else is
  unchanged — a file carrying `[branches]`, `[paths]`, `[review]` or `[[prs]]` is
  validated as the full series it is, defects and exit code included, and a file that is
  neither a series nor a gate still reports the series loader's message.

### Changed

- `docs/authoring-series.md` states the condition gate adoption carries: a gate whose
  checks are the implementer's own suite is not an oracle, so the surface alone changes
  nothing.

## [0.10.0] - 2026-09-01

The round the gate stopped being part of the run. Convoy's most valuable mechanism — the
deterministic, fail-closed gate — was reachable only by buying the whole engine, so a
dispatch decision that rejected the runner on its merits discarded the gate with it. It is
now a surface of its own, and the engine needed no new gate semantics to expose it.

**This release is consumer-affecting**: two new surfaces with a shared result envelope,
two new `CheckResult` fields, and one input a loader now refuses. A tool driving convoy as
an engine should read the marked entries below rather than assume the contract stood still.

The round also finished the guardrail work it started as: two review-enforced guardrails
became mechanisms, two prose disciplines became gates, and CI gained the second operating
system the engine's failure history keeps naming.

### Added

- A commit-time lane. `.pre-commit-config.yaml` runs the fast half of the gate — `uv lock
  --check`, then both ruff checks, in CI's order — plus a commit-message lane: the
  conventional subject shape, and a rejection of AI-attribution trailers. Installed via
  the tracked wrapper scripts in `scripts/git-hooks/` (`git config core.hooksPath
  scripts/git-hooks`), which go through `uv run python -m pre_commit` rather than the
  bare `pre-commit` shim a locked-down machine silently never runs. `ty check` and
  `pytest` stay CI-owned deliberately: the slow half of the gate does not belong in front
  of every commit. `tests/test_doc_claims.py` reads the hook config the way it already
  reads `ci.yml`, so the lane cannot drift from the gate it mirrors.

- The changelog rule is now a gate. "Docs and CHANGELOG in the same change" was prose in
  `AGENTS.md` and `CONTRIBUTING.md`; the last build round followed it five times out of
  five, and nothing would have caught the sixth. The `changelog` workflow
  (`scripts/changelog_gate.py`) fails a PR that touches `src/` without touching
  `CHANGELOG.md` unless a commit declares the exemption (`Changelog: none (<reason>)`),
  pins an added release heading to an actual version bump, and — advisory, a warning
  that never fails the job until it has proven quiet on ordinary PRs — flags a
  contract-surface diff whose entry never says **(consumer-affecting)**.

- The changelog gate also asserts this file's *shape*: an added `### ` section heading
  must be one of the six Keep a Changelog words (Added / Changed / Deprecated / Removed /
  Fixed / Security). A heading outside the vocabulary reached `main` once, caught by a
  merge-conflict resolution rather than by anything mechanical — content claims were
  gated while shape stayed prose. Only added diff lines are read, so history is
  grandfathered by construction.

- The unit suite now hard-fails a real agent spawn. The spawn path was stubbed per test
  by convention — the arrangement under which a live seat once turned five CLI tests into
  five real spawns per suite pass. A second autouse guard in `tests/conftest.py` makes a
  `HeadlessSpawn` left on the default `claude` binary raise instead of launch; subprocess
  tests point the spawn at a stub executable, which the guard passes through. The
  guardrail document now names the fixture instead of the convention.

- CI runs the gate on Windows as well as Linux. The engine's failure history is
  platform-shaped — the locale-decode class and the path-separator class were each caught
  after merge, on a Windows machine, invisible to a Linux-only leg.

  The matrix arrives behind an aggregating job that keeps the name. A matrix job reports one
  check per leg (`gate (ubuntu-latest)`, `gate (windows-latest)`) and never the bare `gate`
  context the branch ruleset requires, so adding the second operating system stopped that
  context from being reported at all and left this pull request unmergeable with all eight of
  its checks green — the change breaking the requirement it had to satisfy. The matrix job is
  now `checks`, and a plain `gate` job depending on it asserts every leg passed. The name is
  kept here rather than re-pointing the ruleset at the two leg names, so the matrix can gain
  or lose an operating system without the merge requirement being edited again.
  `tests/test_doc_claims.py` asserts the three properties that ruleset depends on — a `gate`
  job exists, is not itself a matrix, and carries `needs: checks` with `if: always()` — because
  the ruleset lives in repository settings and is invisible from the tree.

- The gate without the run. **(consumer-affecting)** `convoy gate` (CLI) and
  `convoy_gate` (MCP) run a series' `[[checks]]` against a workspace once — the same
  runner, the same fail-closed independence guard on `independent` checks, and the same
  verdict rules the run applies after every PR, with no spawn, no branch, no merge, no
  lock and no telemetry. The engine always had the primitive (`SubprocessGateRunner`
  had exactly one production call site, inside the per-PR loop); this exposes it, for
  verifying work produced outside convoy instead of letting the implementer self-report.
  Both surfaces emit the same envelopes from one fold (`interface/gate_service.py`),
  the failure paths included: per-check verdicts with structured failure facts
  (`exit_code`, `timed_out`) beside the prose `detail`, `blocking_red` /
  `independent_red`, counts (`total` / `selected` / `passed` / `failed`), an
  always-present `advisories` list, the run envelope's `truncated` report (the
  per-check list caps at 50), and the CLI-equivalent `exit_code` — 0 green, 1 blocking
  red, 3 usage, reusing the run's own codes and outcome words (`completed` / `blocked`
  / `usage`). `series_file` may be a full series.toml or a minimal file carrying only
  `[series] id` and `[[checks]]` (`load_gate_spec`; a missing
  `[governance] timeout_seconds` defaults to the runner's 300s; duplicate check names,
  an empty `[[checks]]`, and a malformed `[governance]` are refused at load). `--phase
  TAG` (repeatable; MCP `phases`) runs exactly the checks a PR carrying those tags
  would be gated on. An invocation that cannot produce a meaningful answer is refused
  as `usage`, never answered green: a phase tag no check declares (the run-side
  pre-flight treats the same typo as a blocking problem — a silently narrowed gate
  still looks gated), a selection with no blocking check, an empty selection, and a
  blocking independent check whose isolation is not backed (a red there would point a
  repair loop keyed on `independent_red` at a spec defect no repair can fix — the run
  classifies it as pre-flight usage, and now so does the gate).

- `Check` results carry the structured half of their prose: `CheckResult` gains
  `exit_code` (the command's own, `None` on a timeout) and `timed_out`, populated by
  the gate runner. **(consumer-affecting)** for the gate envelope's `checks[]` entries;
  telemetry lines are unchanged.

- `[governance] timeout_seconds` must now be positive in both loaders. A `0` loaded as
  "every check times out instantly", which reads as a full red gate — a one-character
  typo masquerading as a code failure, with no pre-flight in between on the gate-only
  path.

### Changed

- Convoy's presentation names the gate as separable. The skill's trigger description
  now states two capabilities dispatched separately — the runner and the standalone
  gate — displacing the single-package framing under which a dispatch decision that
  rejected the runner discarded the gate with it (measured cost, one production round:
  11 externally orchestrated PRs verified only by the agents that implemented them).
  `docs/authoring-series.md` opens with the separability doctrine and the
  one-PR-series pattern, under a word budget set at the file's birth; the skill's
  gate-only section points at it.

- The two spawn sites that spelled the decode policy as literals now import
  `TEXT_ENCODING`/`TEXT_ERRORS` from `interface/proc.py`, and `tests/test_proc.py` fails
  on the next literal respelled outside `proc.py` and `streams.py` — the guardrail's
  "one decode policy" sentence is now true, and mechanical.

- The release checklist opens with a step 0 that makes the version-bump decision
  mechanical: minor when any `[Unreleased]` entry carries **(consumer-affecting)**, patch
  when none does, citing the enumeration in `docs/design/02-formats.md`. It was the one
  judgement call in the cut that no document signposted — steps 1–4 were mechanized, and
  the rule deciding the number lived in a document the checklist never pointed at — and
  it produced a wrong recommendation once (0.10.0 where the rule said 0.9.1).

## [0.9.1] - 2026-08-28

The delta triage build round: nothing in the engine's contract moves, so this is a patch
cut — no new event, field, `outcome`, `error_kind`, exit code or series.toml key, and
therefore nothing marked consumer-affecting. What changes is what convoy *says*. The skill's
trigger no longer fires only after someone has chosen convoy; a pre-flight advisory that two
production workspaces had drowned in vendored files is readable again; a failing engine-side
`git` command reports what git actually said; and two engine behaviours an operator could
previously only discover by paying for them are in the manual.

Consumers parsing advisory *message text* — never a promised contract, but worth naming
rather than leaving to be discovered — will see two changes: paths are POSIX-separated on
every platform, and a long uncovered-test list now names directories with counts instead of
three file names.

### Changed

- The skill's trigger description now states the **pre-condition** — a plan, spec or PR
  manifest that already names two or more PR-sized changes — instead of leading with
  convoy's own artifacts. The old wording opened on the MCP tool names and its first
  trigger was "when running a convoy series.toml", a condition that only becomes true after
  someone has already chosen convoy: the trigger fired after the decision it exists to
  inform. Both clauses are displaced, not appended to. A documented program recorded zero
  convoy invocations across two sessions doing governed multi-PR work; a post-hoc telemetry
  pass over the same window recorded the skill entered 3 times against 271 engine
  invocations, while more than half the feedback corpus cites the skill document as what a
  series was authored from — the content is load-bearing and the trigger was not reaching
  it.

- The manual now describes two engine behaviours it was silent about, both of which cost an
  operator in production. **Mid-series gate repair**: `resume` re-reads the series file, so
  `[[checks]]` edited between two PRs govern every PR the resumed run still has to run while
  already-integrated PRs are skipped rather than re-gated — a supported pattern that one
  night used to put five added checks in front of the remaining PRs of a seven-PR series
  without re-paying for four. **A driven workspace is not safe to write to**: the engine
  moves `HEAD` between branches for the run's duration, so an outside commit lands on
  whichever branch is checked out at that instant. Both are engine behaviour the manual is
  supposed to carry, not new advice.

### Fixed

- The pre-flight advisory naming the test files a blocking gate will not run now skips the
  files the workspace's **own** ignore rules exclude, and names the directories holding
  them once the list is too long to read as a list. Two production workspaces had turned
  the advisory into noise the same way — a virtualenv under a name no hardcoded list
  anticipated (526 site-packages test files), and a build directory of archived sibling
  repositories (474) — which trains an operator to skip advisories, including the ones that
  are right. `git check-ignore` answers with the repository's rules rather than convoy's
  guess at what a borrowed directory is called; a workspace that is not a repository, or a
  machine with no `git`, is unchanged. Advisory paths are now POSIX-separated on every
  platform.

- `CONTRIBUTING.md` and the PR template now list **every** command CI runs, in CI's
  order. Both listed four of the six and CONTRIBUTING called it "the same set CI runs";
  the omitted `uv lock --check` is the step whose position the same file elsewhere calls
  load-bearing, and skipping it is how `uv.lock` recorded `convoy-engine 0.1.1` through
  the whole of `0.2.0`. `tests/test_doc_claims.py` now reads the workflow and fails on a
  documented gate that is missing a step or lists them out of order, so the fourth
  recurrence of this class is the last one prose has to catch.

- A failing engine-side `git` command now reports what git said on **either** stream. The
  detail was read from stderr alone, so `git commit` with nothing staged — which says why on
  stdout and leaves stderr empty — produced a bare `git commit -m '…': exited 1`. In
  production an engine-side commit failed exactly that way and the message did not
  distinguish an empty commit from a hook rejection or an index lock, so it was diagnosed by
  inspecting the workspace by hand. Stderr, then stdout, then the exit code, which still
  stands in when git genuinely said nothing anywhere. This is the same stream-precedence
  mistake the gate's failure detail was corrected for in 0.8.0, in the engine's own
  subprocess calls.

## [0.9.0] - 2026-08-12

One consumer-affecting change and nothing else: the `strong` tier resolves to a different
model than 0.8.0 gave it. A tier is a name a series pins, so the switch needs a version a
consumer can pin against rather than arriving as a silent change of meaning under a
constant name.

### Changed

- **(consumer-affecting)** The `strong` tier now resolves to `claude-opus-5`
  (`DEFAULT_TIER_MODELS`, the skill's tier map). The previous id is still served, so
  existing explicit `model =` pins keep working; only series that say `tier = "strong"`
  pick up the new model. Mirror sync with the model-policy owner's canonical lineup
  (reconciled 2026-08-11); family-keyed pricing needed no change.

## [0.8.0] - 2026-08-11

Backlog wave 1 (`docs/backlog.md`): the run becomes legible and honest under failure —
budget nearing before the bust, a dead driver distinguishable from a running one, a
refused spawn never scored clean, the manual held to the engine by test, and a series
pinned to the spec it was decomposed from.

### Added

- **A series can now pin the spec it was decomposed from, and a run refuses to start against
  a spec that has moved.** `[series]` accepts two optional keys, set together: `spec_path`,
  the spec's repo-relative path in the workspace, and `spec_sha256`, its content hash at
  decomposition time. Pre-flight resolves the path and compares the hash **before the first
  spawn is purchased**, which is what "before any paid run" means — blocking, not advisory,
  because the point is that no paid run executes against a spec that has changed since it
  was decomposed. A matching pin is then recorded on the `run_start` line, so the join key
  reaches the run record rather than stopping at the series file.

  Without it a run recorded nowhere which spec produced it, so "which version of which spec
  produced this run" was simply unanswerable afterwards — the same silent shape as an
  unvalidated `effort`: nothing fails at run time, and the comparison the ledger exists to
  support is missing when someone finally needs it. Like a hash comparison generally, this
  needs no heuristic and has no false-positive budget. The path must be relative and an
  absolute one is rejected at load, because a series directory travels by copy and a
  machine-absolute path in it is wrong on arrival. A series with no pin behaves exactly as
  before the keys existed (`core/spec.py`, `interface/preflight_probe.py`,
  `core/telemetry.py`, `interface/drivers/headless.py`). **(consumer-affecting: two new
  series.toml keys, two new `run_start` fields, and a new `spec_pin` pre-flight problem
  kind)** Serves backlog row CONV-B36.

- **Pre-flight now says what the blocking gate will not run.** Phase scoping made subset
  gates possible and convoy said nothing about how to scope one. The quiet failure is the
  expensive one: a subtree-scoped suite cannot see the repository-wide guards a PR mutates,
  so a 16-PR wave gated 16/16 green while two of them were red — found only by running the
  full suite by hand after the run reported `completed`, which means the series' own quality
  claim was stronger than the tree warranted.

  A third `kind='gate'` advisory answers it for free at `dry_run`, since convoy already
  holds both the gate commands and the workspace: it names the test files present in the
  workspace that no blocking check's declared paths cover. Unlike a path detector this needs
  no heuristic and has no false-positive budget — it compares the paths a command *names*
  against the files the test runners' own discovery globs *find*, and it stays silent
  wherever the answer would be a guess. A blocking check that names no existing path runs
  whatever its tool discovers (the whole tree), so one of those silences the advisory
  entirely; a check naming only out-of-tree paths is an independent oracle and is passed
  over rather than counted as either. Advice, not a problem: a deliberately narrow gate is a
  legitimate authoring choice, and it is now a visible one
  (`interface/preflight_probe.py`). Serves backlog row CONV-B05 (T31b); the two
  authoring-side halves of that row still ride CONV-B08.

- **The ledger now says which PR is in flight, not only which ones are done.** A new
  `spawn_start` line is written immediately before each agent spawn launches, carrying
  `run_id`, `pr_id` and `role` and no economy — nothing has been spent yet, and a line
  promising numbers it could not have would be worse than none.

  Until now the ledger recorded only completions, so for the 30–90 minutes a spawn takes, a
  PR in progress looked exactly like a PR the run had not reached. Pairing `spawn_start`
  with `spawn_complete` on `(run_id, pr_id, role)` closes that, and also separates a driver
  that is dead from one that is alive but stuck: the second leaves a started spawn that
  never completes. The result envelope folds it into a per-PR `in_flight` field — the role
  in flight, or `null` (`core/telemetry.py`, `interface/drivers/headless.py`,
  `interface/run_summary.py`). **(consumer-affecting: a new `spawn_start` event and a new
  per-PR `in_flight` field in the run envelope)** Serves backlog row CONV-B02 (c).

- **`convoy clean` closes a killed run's ledger entry instead of leaving it open for ever.**
  Clearing a stale workspace lock now also appends a terminal `run_abandoned` line for the
  run that left it behind, when that run recorded no outcome of its own. It has to happen
  at that moment: the lock names the process that owned the run, and a pid is reusable once
  that process is gone, so after the lock is cleared nothing can establish the fact. The
  entry then reads `finished` with `outcome: "abandoned"`, `integrated: false`, and the
  infrastructure exit code — outside the work, and re-runnable with `--resume`.

  A distinct event rather than another `run_complete` outcome, because the writer is not
  the run: every other line is the engine's account of its own work, and this one is a
  later process's account of a run that never reached a verdict. There is deliberately no
  `halt` and no `integrated` on the line — whoever wrote it was not there. `--dry-run`
  names the record it would write and writes nothing; a workspace with no stale lock is
  left alone, since the lock is what identifies the tree a killed run left behind
  (`core/telemetry.py`, `interface/run_summary.py`, `interface/run_service.py`,
  `interface/cli.py`). **(consumer-affecting: a new `run_abandoned` event, and `abandoned`
  joins the reconstructed `outcome` vocabulary)** Serves backlog row CONV-B02 (b).

- **A run whose driver is gone now reads `dead` instead of `running` forever.** The ledger
  records only completions, so `convoy_status` derived `running` from the *absence* of a
  terminal line — which is precisely what a hard-killed driver leaves behind. Two runs on
  disk (9 spawns, about $47) have no terminal record at all and reported `running`
  indefinitely, and every driver death in the last campaign was diagnosed by hand with an
  OS process query.

  The fact was already on disk and unused: a run takes the workspace lock before its first
  ledger line and holds it to the end, and that lock has always recorded its owner's pid.
  `convoy status` and `convoy_status` now accept a `--workspace` / `workspace` argument and
  read it — nothing else, nothing written — so a run with ledger lines, no `run_complete`,
  and a lock naming a process that no longer exists is reported `dead`, with a `message`
  naming the recovery. The terminal fields stay `null`, because `dead` is the absence of an
  outcome rather than one of them, and the economy is final rather than partial.

  Deliberately one-sided: `dead` is claimed only on the positive evidence of a lock whose
  owner is gone. No lock, or no `workspace` argument, reads `running` exactly as before —
  the commonest way to see no lock is asking from the wrong directory, and a false `dead`
  would send an operator to restart a run that is still spending
  (`interface/workspace_lock.py`, `interface/proc.py`, `interface/run_summary.py`,
  `interface/cli.py`, `interface/mcp/server.py`). **(consumer-affecting: `state` gains the
  value `dead`; a consumer branching on `running` / `finished` / `unknown` must add it
  rather than fall through)** Serves backlog row CONV-B02 (a).

- **A spawn that runs close to its cap now says so, while there is still a run to save.**
  `spawn_complete` carries two new fields: `budget_cap_usd`, the ceiling that spawn ran
  under, and `budget_nearing`, true once the spend reaches 90% of it. The same moment is
  narrated on stderr as a `near cap` line, so the operator watching a long run hears it
  without tailing the JSONL.

  The hard cap is deliberately untouched — a spawn that busts it is still truncated and
  the PR still halts, which is the whole feature. What moves is when the ceiling becomes
  visible. Until now the halt was the first thing in the record that mentioned a cap at
  all, and by then the series was already forfeit: two of ten terminal runs on disk halted
  on overshoots of 0.3% and 0.4%, skipping five downstream PRs between them and discarding
  the truncated spawn's uncommitted work. The workaround that got reached for was raising
  the cap for every PR in a wave, which weakens the ceiling for every cheap PR — the
  opposite of what the cap is for. A signal on the spawn *before* the busting one is the
  cheaper half of that fix (`core/telemetry.py`, `interface/drivers/headless.py`,
  `interface/reporter.py`). **(consumer-affecting: two new telemetry fields)** Serves
  backlog row CONV-B01.

- **An `asset` nothing will ever read is now said out loud.** `[[checks]].asset` is consumed
  in exactly one place — the fail-closed isolation guard, which returns early unless the
  check is **both** blocking and independent. Anywhere else the field is accepted by the
  parser, written back by `dump_series`, and read by nothing: an author who declares an
  out-of-tree oracle on a non-blocking or non-independent check has written down an
  intention convoy silently does not act on, and the isolation they believe they bought is
  not being verified.

  Pre-flight now emits an advisory naming **which flag is missing** — `not independent`,
  `not blocking`, or `neither blocking nor independent` — since which one to set is the
  whole actionable content. It is advice, not a problem: the field changes no behaviour, the
  check still runs and still reports, so refusing the run over it would be the paternalism
  the ungated-PR advisory deliberately avoids.

  Second producer on the advisory channel, and the first one added since that channel
  started reaching the run path — so unlike the first, this one is visible on the run
  itself, not only on `convoy validate`. It is appended after the ungated-PR remark, so a
  consumer that has been reading `advisories[0]` since 0.3.0 still finds that one there
  (`core/preflight.py`, `interface/preflight_probe.py`). Serves backlog row T26a.

- **A visual identity.** `assets/` now carries the brand kit — mark, wordmark, lockup,
  README hero, and social-preview card, in light and dark — as self-contained SVGs:
  every shape is a drawn path, so nothing depends on an installed font or a network
  fetch. Tokens, embedding, and usage rules live in `assets/README.md`.

### Changed

- **`--fresh` / `reset=true` now restores the tree, not just the branches.** There were two
  destructive paths with overlapping names and a gap between them. `--fresh` touched branches
  only, while by convoy's own documentation a `budget` or `infrastructure` halt returns
  *before* the truncated spawn's work is committed — so it leaves exactly the uncommitted
  changes and untracked files `--fresh` could not remove, and that could abort its own
  checkout. The documented recovery was therefore "run `clean` by hand, then run `--fresh`",
  which means the flag did not do what its name implies in the case that most needs it.
  Budget halts were two of ten terminal runs on disk, so that is the common path.

  `--fresh` now performs `convoy clean`'s tree-restoring steps first — discard uncommitted
  changes to tracked files, delete untracked files and directories — and then deletes the
  branches as before. One destructive path, one mental model. `convoy clean` keeps its own
  job, which `--fresh` cannot do: restoring a workspace **without** starting a run, so it
  takes no lock, pays for no seat probe, and closes the killed run's ledger entry. With the
  flag off, nothing in the tree is touched and a leftover branch fails loud exactly as
  before (`interface/run_service.py`). **(consumer-affecting: `--fresh` / `reset=true` is
  more destructive than it was — it now discards uncommitted work in the workspace)** Serves
  backlog row CONV-B31.

- **The shipped documents no longer contradict the shipped engine, and a test now fails
  when they do.** Corrected: the manual's claim that "there is no resume — a halted run does
  not check-point-and-continue" (`--resume` shipped in 0.4.0 and was documented 300 lines
  above it) and that a re-run "re-spends it in full"; the §Cost & latency claim that
  `convoy_run` is synchronous and cannot be polled (false since `convoy_status` in 0.5.0 and
  `detach` in 0.6.0); the absence of `convoy clean` from the manual entirely, which cost two
  operators a hand-deleted branch that `--resume` already deletes; "two tools" in the MCP
  server docstring and in `docs/design/03-serving.md` while three are registered;
  `marketplace.json` advertising only `convoy_run` and `convoy_init`, so `convoy_status`
  shipped unadvertised for three releases; and `docs/design/00-overview.md` §7's claim that
  convoy's CI gate includes an independent check over convoy itself, which `ci.yml` has
  never had.

  The mechanism is `tests/test_doc_claims.py`, in the shape of `test_versions_are_locked`:
  every registered MCP tool name appears where the tools are listed, every CLI verb appears
  where the verbs are listed, every `convoy_run` argument is documented in the manual, and a
  stated tool count matches the registered one. Deliberately narrow — it pins the claims
  that have actually drifted and reads no prose for meaning — and it carries a non-vacuity
  guard, since the whole module is a set difference against two registries and would pass
  silently if either stopped answering. This is the third occurrence of the class and the
  first two fixes were both prose, which is the escalation trigger; `AGENTS.md` already
  carried the right rule, and what was missing was something that fails. Recorded in
  `docs/GUARDRAILS.md` with its enforcer. Serves backlog row CONV-B04.

- **A spawn the agent CLI refuses is no longer scored as a clean result with zero economy.**
  `_classify` matched the CLI's prose on stderr and returned `'ok'` for any non-success spawn
  carrying no auth, usage or retry signature. So a spawn refused at argument parse — a flag
  renamed upstream, a value dropped from a choice list — was recorded as a clean task result
  with $0 economy, and the seat probe, which blocks only on `'infrastructure'`, waved it
  through. The operator then met a `blocked` run with $0 spend and no diagnosis.

  The CLI's structured signals are now preferred over its prose wherever one exists. A
  nonzero exit with **no `result` event at all** is `infrastructure`: the CLI never got as
  far as running the task, and it says so in the `diagnosis`. And the `result` subtypes
  convoy has a decision for are named in one table, with a non-success spawn carrying
  anything else classified `infrastructure` rather than scored — an unrecognised error name
  is a reason convoy does not understand, and "clean task result" is the one guess that is
  wrong silently. When the CLI ships a new subtype the fix is to record a decision for it,
  which a test now forces. Matching a vendor CLI's prose is a permanent tax with a silent
  failure mode; this pays less of it (`interface/headless_spawn.py`). Serves backlog row
  CONV-B07.

- **`effort` is validated at load, and recorded on every spawn line.** It was an
  unvalidated free-form string. Verified against the installed agent CLI: an unknown
  `--effort` value prints a warning on stderr, then runs at the CLI's own default and exits
  `0`. So a typo produced a run whose series file and whose ledger both claimed a level the
  spawn never used — silent, undetectable downstream, and corrupting exactly the comparison
  the ledger exists to support. `effort` now gets the allow-list treatment `permission_mode`
  already had (`low`, `medium`, `high`, `xhigh`, `max`), on `[governance]` and on a per-PR
  override alike, and the resolved value is written on each `spawn_complete` line as
  `effort` so a divergence is at least visible after the fact.

  `PERMISSION_MODES` is refreshed against the same CLI in the same change: it accepts
  `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk` and `plan`, plus the
  legacy `default`. convoy's four-value list was rejecting three modes the CLI supports
  (`core/spec.py`, `core/telemetry.py`, `interface/drivers/headless.py`).
  **(consumer-affecting: a new `effort` telemetry field; `[governance].effort` and
  `[[prs]].effort` are now allow-listed, so a series carrying an unknown level — which
  never ran at that level anyway — now fails pre-flight instead of running silently
  mis-labelled)** Serves backlog row CONV-B06.

- **A failing check's `detail` is now chosen by content rather than by stream, and cut at a
  line boundary.** `_red_detail` was `stderr.strip() or stdout.strip()`, so *any* content on
  stderr meant stdout was never read at all. The case that proves it: a subset-scoped pytest
  run whose coverage-floor failure (`Required test coverage of 80% not reached`) went to
  stdout while stderr held only a launcher warning — the real answer was not truncated, it
  was discarded. `detail` is also what the bounded fix loop re-briefs the repair spawn with,
  so a discarded answer aims a paid spawn at a non-problem.

  A red now carries a bounded, labelled tail of **each** stream that said anything, split by
  one budget so neither can crowd the other out and a short stream donates its unused share
  to a long one. The bound is applied at a **line** boundary rather than a character count:
  a tail that begins mid-word reads as though the fragment were the failure, observed twice
  in production (a detail opening inside an unrelated xfail reason, and one inside a
  structured log line). Any cut is marked with a leading `...`, so a reader — and the fix
  spawn — can tell a tail from the start of the output.

  This is the third fix at this layer. The first two removed a then-known pollutant; this
  one changes how the detail is *selected*, which is the thing that kept recurring.
  `gate_complete.checks[].detail` is free-form prose and stays a string, so
  `schema_version` does not move — but a consumer that parses it will see the new shape
  (`interface/gate_runner.py`). Serves backlog row CONV-B03.

- **The release-tag workflow now gates the release page too.** No behaviour change to
  convoy; this is repo discipline, and a follow-up to T24a's own argument. Mechanizing the
  tag left its sibling artifact unmechanized: every version from `0.2.0` through `0.6.0`
  carried a tag and **no GitHub release**, so the repository's front page advertised `0.1.2`
  for six versions while the tags said otherwise. The six were backfilled from their
  `CHANGELOG.md` sections.

  The workflow checks the two **separately** rather than treating one as evidence of the
  other, because a tag with no release page is precisely the state those five versions sat
  in. `CONTRIBUTING.md` gains publishing the release as step 4, and names which artifact
  carries which weight: the tag is what the marketplace serves, the release is what the
  front page advertises.

- **The README opens with the front door.** Hero banner and badge row first, the pitch
  in one paragraph, and the quick start — install, scaffold, validate, run — within the
  first screenful, ahead of the concept walkthrough; the reference sections are
  unchanged in substance, and the docs links consolidate under one Documentation
  heading. Also fixes the plugin-install note that still counted two MCP tools while
  the agent-surface section on the same page listed three.

## [0.7.0] - 2026-07-25

### Fixed

- **A pre-flight advisory now reaches the run that provokes it.** *(consumer-affecting: a
  new `advisories` field on the `run_start` telemetry event, and a new `advisories` key on
  the run envelope both surfaces return.)* `preflight` returns `problems` **and**
  `advisories`, but the run path kept only the problems, so the only things that ever
  surfaced an advisory were `convoy validate` and `convoy_run(dry_run=true)`. ADR-0008's
  ungated-PR advisory therefore said nothing on the run that actually integrated the
  unverified PR — its stated rationale, "the advisory makes the consequence visible without
  taking the decision", held only for an operator who happened to validate first, which is
  not the operator with the problem.

  Advisories now ride the **`run_start`** line, the same way `halt` rides `run_complete`
  rather than being threaded through `RunOutcome`: the fact stays reconstructible from the
  ledger alone, so one mechanism serves the CLI reporter (a line under the run header), the
  run envelope both surfaces return, and `convoy_status` — which reports a run this process
  never started, and so could not have pre-flighted it. It also makes the channel's firing
  rate measurable for the first time, which matters for any future producer whose
  calibration would need revisiting on evidence.

  `AdvisoryLine` is telemetry's own nested record, like `GateCheckLine` and `HaltDetail`, so
  the wire model stays independent of the pre-flight model — but it serializes to the same
  `{kind, where, message}` object the dry-run envelope already returns, because meeting one
  idea in two shapes is a cost paid by every consumer. The envelope key is always present
  and empty when there is nothing to say, matching the guarantee dry-run already gave.

  Advice still never becomes failure: only `problems` gates a run, and a test pins that
  carrying advisories did not change it (`core/telemetry.py`, `core/preflight.py`,
  `interface/reporter.py`, `interface/drivers/headless.py`, `interface/run_service.py`,
  `interface/run_summary.py`). Serves backlog row T25a.

### Changed

- **A dead seat now says what is wrong before it says everything else.** The seat probe's
  pre-flight `Problem` carried a 500-character tail of the CLI's own output — newline-
  delimited JSON plus stderr — so an expired login read as a wall of noise with the one
  actionable sentence buried somewhere inside it, if it survived the cut at all. Messages
  now lead with the diagnosis and keep the stream behind it:

  ```
  seat probe failed for model 'claude-haiku-4-5': Invalid API key · Please run /login
  [raw tail: {"type":"result","subtype":"error",...]
  ```

  The text was never missing, only unextracted: the spawn adapter already decides the
  classification by reading a specific channel — the CLI's stderr, the terminal `result`
  event's text, or its `subtype` — and then threw that knowledge away into a concatenated
  `output`. `SpawnResult` gains a **`diagnosis`** field carrying it, and the classification
  and the diagnosis are now produced by one function, so the verdict and its evidence
  cannot drift: whichever channel decided the verdict is the one quoted. A timeout states
  itself (`no result within the 120s timeout`) rather than quoting whatever the CLI was
  mid-sentence about when it was killed.

  Two properties are load-bearing. The diagnosis is the **head** of the deciding text, not
  the tail, because a diagnosis leads with the diagnosis. And its whitespace is collapsed:
  the destination is a one-line message — `format_problems` renders one problem per line —
  so an embedded newline would silently break that layout for every reader downstream.

  Strictly additive for the reader: an empty diagnosis falls back to the tail alone, which
  is exactly the previous behaviour, so this can inform but never take away. Not
  consumer-affecting — `SpawnResult` is not serialized (`_record_spawn` writes named fields)
  and a `Problem` message is prose, not a keyed protocol (`interface/spawn.py`,
  `interface/headless_spawn.py`, `interface/seat_probe.py`). Serves backlog row T21a.

- **The release checklist's two unmechanized steps now have mechanisms.** No behaviour
  change to convoy itself; this is repo discipline. `test_versions_are_locked` gated the
  three hand-edited version fields agreeing, and that half always held — the halves that
  failed were the ones nothing checked.

  **The lockfile.** `uv.lock` is a fourth place the version lives, named nowhere in the
  documented cut, and it recorded `convoy-engine 0.1.1` through the whole of `0.2.0`. CI
  now runs **`uv lock --check`** before any step that would rewrite it, and `AGENTS.md`
  lists it first among the gates with the reason the order is load-bearing: `--check`
  reports a stale lockfile, while `uv sync` and every later `uv run` silently repair one.
  That is also why this is not a test — an assertion in `test_versions_are_locked` was
  written and then deliberately removed, because `uv run` re-locks before pytest reads the
  file, so it could never have gone red. A test that cannot fail is worse than no test.

  **The tag.** The marketplace serves tags, so an untagged release is invisible to every
  installed consumer however correct the merge was: `0.2.0` was bumped, changelogged and
  merged while consumers went on being served `0.1.2` for ten days. A new **`release-tag`**
  workflow checks daily that `main`'s `pyproject.toml` version has a matching `v<version>`
  tag. Scheduled (plus `workflow_dispatch`) rather than push-triggered on purpose: the tag
  is created *after* the release PR merges, so a push gate would fail every release by
  construction and leave that commit permanently red even once tagged — an alarm that is
  always wrong at first is one people learn to ignore. A scheduled run re-evaluates, so it
  clears itself.

  `CONTRIBUTING.md` now names four version locations rather than three, says to tag the
  release PR's **merge commit** rather than `main`'s tip, and states why the tag is the
  step that matters. Serves backlog row T24a — the second occurrence of this family, the
  first having been answered with documentation, which is exactly why it recurred.

## [0.6.0] - 2026-07-25

### Added

- **`convoy_run(detach=true)` — start a run and get a handle back at once.**
  *(consumer-affecting: a new MCP tool argument, a new `outcome` value `started`, a new
  `--run-id` CLI flag, and a new `problems[].kind` value `run_id`.)* `convoy_run` blocked
  for the whole series — minutes to hours — with no job handle and no progress stream, so
  the only way an agent could start a long run was to hold the call open for it.
  `detach=true` returns `{ok: true, outcome: "started", state: "running", run_id, pid,
  telemetry_path, result_path, log_path, next}`: a handle, not a result. `ok` reports the
  launch, since the run has no verdict yet, and `state` uses `convoy_status`' vocabulary so
  one branch handles both envelopes.

  The child is convoy's own CLI, started as `sys.executable -m convoy run --run-id <id>
  --json` (a new `convoy/__main__.py`, so the launcher never has to guess where the console
  script installed). One run path stays one run path. Three consequences:

  - **The parent pins the run id.** A handle the caller cannot poll by is not a handle, and
    the child cannot be asked afterwards what id it chose — hence **`--run-id`**, also
    useful to any harness that must know the id up front. An id the ledger already holds
    lines for is refused (`kind: "run_id"`): every fold selects by `run_id`, so reusing one
    would sum two runs' economies into a single envelope, wrong in a way nothing downstream
    can detect.
  - **The child records its own verdict.** Under `--json` its stdout is exactly one
    envelope on every path, so `result_path` holds the answer even for a run that died
    before the engine wrote a ledger line. `convoy_status` now reads that file when the
    ledger holds nothing under the id — otherwise a detached run that hit a busy workspace
    or an expired seat would report `running` forever. The ledger wins whenever it has
    anything; a half-written file does not parse and is treated as absent.
  - **The free pre-flight still runs in the calling process**, so a malformed series is
    refused immediately: detaching is about not waiting for the run, not deferring what is
    knowable now. `dry_run` takes precedence over `detach` — a pre-flight is free and
    instant, so there is nothing to detach.

  Detachment is `start_new_session` on POSIX and `DETACHED_PROCESS |
  CREATE_NEW_PROCESS_GROUP` on Windows. Neither escapes a **job object**: a host confining
  its children to a kill-on-close job still takes the run down when it exits. Convoy does
  not attempt `CREATE_BREAKAWAY_FROM_JOB` — that limit is usually deliberate host policy,
  and breaking out of it silently would be worse than honouring it; the run then stops
  advancing, which is what `convoy_status` reports (`interface/detached.py`,
  `interface/run_service.py`, `interface/run_summary.py`, `interface/mcp/server.py`,
  `interface/cli.py`). Completes backlog row T14b's cluster as row T14c.

### Fixed

- **The skill and README documented two MCP tools; there are three.** `convoy_status`
  shipped in 0.5.0 and reached neither, so the agent-facing manual described a surface
  without the one tool that makes a long run followable. Both now list all three, and the
  skill documents `convoy_status`' arguments and its `state` field alongside the rest of
  the envelope. The skill's `problems[].kind` list was also three values short (`resume`,
  `run_id`, `seat`).

### Changed

- **The commit convoy sweeps after each spawn now names the work, not just the PR id.** The
  driver commits whatever an implementation or fix spawn left uncommitted — a no-op when the
  agent committed properly — so that message is the message of record in the integration
  branch's history. It was the bare `pr.id`, which made `git log --oneline` a column of
  opaque identifiers, and the id is also the branch name: the one thing a reader could
  already get elsewhere. Subjects now read `pr-3: Wire the queue consumer` and
  `pr-3-fix-1: Wire the queue consumer`.

  A `[[prs]]` entry carries no `title`, so the summary is the prompt's own opening line —
  the closest thing to a human title the series holds, and free, since the driver has the
  brief in hand at that point. Leading `#` marks are stripped for a prompt written as
  markdown. An opening line with no alphanumeric character (a `---` frontmatter fence, a
  code fence) is punctuation rather than a title and falls back to the bare id, as does an
  empty prompt — so this never invents a subject where the prompt offers none. A long line
  is cut at a word boundary to keep the whole subject inside 72 columns rather than dropped:
  convoy's own starter prompt opens with an 85-character sentence. A fix commit takes the
  PR's brief, not the fix brief, so both name the same work and the `-fix-N` suffix says
  which is which.

  Not consumer-affecting: no new flag, field, exit code, telemetry value or `series.toml`
  key. The PR id remains the subject's prefix, so anything matching on it by prefix is
  unaffected — only an exact-equality match on the whole subject would see the change
  (`interface/drivers/headless.py`). Serves backlog row T4a.

- **A git failure now names the command that failed.** `GitError` carried git's stderr and
  nothing else, so a message like `fatal: pathspec did not match any file(s) known to git`
  arrived with no indication of which invocation asked — and convoy shells a dozen of them
  per PR (branch setup, staging, the per-PR commit, integration). The command is the half a
  reader cannot recover from the text; git never repeats it. Messages now read
  `git checkout -b pr-3: fatal: a branch named 'pr-3' already exists`.

  Enriched at the `_run_checked` choke point, so every call site gains it at once rather
  than each wrapper prepending its own prefix. The hermetic `-c` flags convoy adds to every
  command are left out — including them would bury the subcommand in constant noise, which
  is the burial this message exists to undo — and an argument carrying whitespace is quoted,
  so a commit message cannot be read as further operands. When git exits nonzero having
  written nothing to stderr the exit code stands in; that path is real rather than
  defensive, since `git commit` reports "nothing to commit" on *stdout*, which used to
  produce a `GitError` whose message was the empty string. `error_kind` is unchanged
  (`git`), and no consumer keys on the message text (`interface/git.py`). Serves backlog
  row T15a.

## [0.5.0] - 2026-07-25

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
