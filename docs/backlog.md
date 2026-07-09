# Backlog — the durable improvement ledger

This is the canonical, tracked record of convoy's improvement backlog. It is fed
by triage passes over dogfooding feedback; the raw feedback reports and the triage
documents themselves are session artifacts and stay local-only in
[docs/feedback/](feedback/) (see the `.gitignore` there). A row here is written so
a maintainer can build it without the source reports.

Row IDs (`T<cluster><letter>`) are minted by triage passes and are stable across
them. Status vocabulary: `proposed` (cleared the promotion gate, ready to build) /
`watch` (anchored but awaiting a second report) / `accepted` (build decision taken) /
`shipped(<ref>)` / `declined`. Consumer-affecting rows must carry the CHANGELOG
marker convention from [docs/design/02-formats.md](design/02-formats.md) when built.

Last reconciled: 2026-07-09, at `main` `4643bc5` (triage pass over 4 reports,
2026-07-06..09).

## Leverage order

**T9a (cut the 0.1.2 release — everything shipped is invisible to the plugin until
it) → T10a + T16a (one `cli.py` pass: clean verb + `--workspace`) → T11a (resume;
biggest per-halt $ recovery) → T13a (one-line env strip protecting the fix loop) →
T12b → T14b → T15a → T5a (decide) → T4a.**

## Open rows

| # | promotion | home | status |
|---|-----------|------|--------|
| T9a | Cut **0.1.2** from `[Unreleased]` and re-tag the plugin marketplace so `claude plugin install` serves the fixed engine. Production runs on 2026-07-08/09 re-diagnosed defects already fixed on main (~15–20 min each) because the plugin pins 0.1.1. | release process (`CHANGELOG.md` cut + git tag + plugin/marketplace manifests) | proposed |
| T9b | State the release discipline in contributor docs: a backlog row isn't done until a tagged release serves it; pre-1.0 cadence = cut after each backlog build round. | `CONTRIBUTING.md` | proposed |
| T10a | `convoy clean <series.toml>` verb (MCP mirror optional): reset to base, delete the series' integration+PR branches, `git clean -fd`, remove the run lock — without starting a run (no seat probe, no lock acquisition). Seams: `cli.py` 4th verb reusing `_load_or_exit`; `git.py` new `clean_untracked`; `workspace_lock.py` `remove_stale_lock` helper. Recovery today is fully manual and was needed ~5× in one campaign; `--fresh` can't help because it acquires the lock and runs the seat probe before resetting. | `interface/cli.py`, `interface/git.py`, `interface/workspace_lock.py` | proposed |
| T10b | Stale-lock auto-reclaim: the lock file already records the owning PID (`workspace_lock.py:43`) but never reads it back — reclaim iff the recorded process is dead. | `interface/workspace_lock.py:34-43` | watch |
| T11a | `--resume`: check out the existing integration branch (it provably retains every green merge after any halt — `headless.py:345`), skip PRs already merged into it (`git merge-base --is-ancestor`), record skipped-because-done PRs with a distinct `pr_skipped` reason, preflight consistency. Thread like `--fresh` (`cli.py:106` → `run_service.py:49` → `mcp/server.py:166`). **(consumer-affecting)** | `interface/drivers/headless.py:235-243`, `interface/git.py`, `interface/run_service.py`, `interface/preflight_probe.py` | proposed |
| T12a | Document budget calibration where series are authored: the `fix` budget scales with fix complexity, not the impl estimate; the validated recovery lever is raise-cap-and-re-run. | `skills/convoy/SKILL.md`, `docs/design/02-formats.md` | proposed |
| T12b | Self-describing budget halt: halted PR + phase + spend-vs-cap on the terminal record and in `summarize_run`'s envelope; classification field on `spawn_complete`. Today the cap is recorded nowhere and `RunComplete` carries only `run_id/outcome/integrated`. **(consumer-affecting)** | `core/telemetry.py`, `interface/drivers/headless.py:318-323`, `interface/mcp/server.py` | proposed |
| T13a | Sanitize the gate-check env: strip `VIRTUAL_ENV` (and uv siblings) via `run_with_timeout`'s existing `env` param; `_ENV_STRIP` in `headless_spawn.py:50-61` is the precedent. A benign uv warning on stderr currently displaces the real failure in `detail` and mis-briefs the fix spawn. | `interface/gate_runner.py:54` | proposed |
| T13b | Stream-robust `detail`: combine bounded tails of stderr *and* stdout instead of stderr-precedence (`gate_runner.py:70-71`). | `interface/gate_runner.py::_red_detail` | watch |
| T14a | Document the supported long-run pattern: MCP `convoy_run` blocks for the whole series; for long/autonomous runs use the CLI in a background shell. | `skills/convoy/SKILL.md` | proposed |
| T14b | Launch-and-poll: detached launch returning `{run_id, telemetry_path}` + a `convoy_status(run_id)` tool reusing `summarize_run`'s on-disk reconstruction; requires persisting the terminal outcome. **(consumer-affecting)** | `interface/mcp/server.py:144,296,335`, `interface/run_service.py:104` | proposed |
| T15a | Subcommand context on `GitError` at the `_run_checked` choke point (`git checkout -b <branch>: <stderr>`), enriching every call site at once. | `interface/git.py:43-48` | proposed |
| T15b | Classify a mid-run git failure as a halt (reuse the infrastructure-halt pattern: `_skip_remaining` + `RunComplete` + distinct outcome) so telemetry doesn't dangle after `run_start`. **(consumer-affecting)** | `interface/drivers/headless.py:235-243`, `core/telemetry.py` | watch |
| T15c | Bounded auto-retry of the branch-setup step before halting (observed environmental `checkout -b` flake). | `interface/drivers/headless.py` | watch |
| T16a | `--workspace <dir>` (default: cwd) on `run`/`validate`, mirroring the MCP tool's explicit argument; at minimum a `--help` line naming the cwd coupling. 4 reports across 4 arcs. | `interface/cli.py:59,96` | proposed |
| T17 | MAX_PATH detection + "scaffold into a shorter directory" hint in `convoy_init`; wire `_error_kind` into `_init_impl` (classifier exists, only `_run_impl` uses it). | `interface/scaffold.py:107,134-136`, `interface/mcp/server.py:196` | watch |
| T18 | Meter the seat probe (a `role: "preflight"` spawn line) if a consumer ever needs to-the-cent totals; probe cost currently precedes the telemetry file. **(consumer-affecting)** | `core/telemetry.py`, `interface/seat_probe.py` | watch |
| T5a | Mixed-tier design decision: per-PR `model`/`tier` override vs a documented one-tier-per-series pattern. Three arcs of evidence; the third shows a sibling planning tool advertising per-PR tiers `core/spec.py:21` rejects. Decide this cycle; the resolution must be propagated to that tool either way. | `core/spec.py` + `docs/design/02-formats.md` (or docs-only) | proposed |
| T4a | Real commit messages on the residual sweep: `commit_all(pr.id)` fires when an impl spawn ends with uncommitted work, so the bare `pr.id` becomes the message of record (7 occurrences, position-independent). Make the sweep produce a real message or ensure the agent commits. | `interface/drivers/headless.py:262`, `interface/git.py::commit_all` | proposed |
| T4b | Commit-provenance telemetry (agent-authored vs engine-synthesized). **(consumer-affecting)** | `core/telemetry.py` | watch |
| T3a | DAG-aware continuation past a halt (continue PRs whose dependency closure excludes the halted PR). Economics largely subsumed by T11a. | `interface/drivers/headless.py`, `core/dag.py` | watch |
| T6a | `files touched: N (+A/-B)` in per-PR impl narration. | `interface/reporter.py` | watch |
| T6b | Per-PR integration state in telemetry — re-evaluate against T12b if it ships. | `core/telemetry.py` | watch |
| T7a | "Adopting convoy in an existing project" docs section (no fixture committed; series+prompts on demand; conventions come from the workspace's own agent docs). | `skills/convoy/SKILL.md`, `README.md` | watch |
| T7b | Deliberate non-features doc (no prompt-injection assembly, no consumer hooks, telemetry is economy+gate). | `skills/convoy/SKILL.md`, `README.md` | watch |

## Shipped (recent)

| # | promotion | shipped by |
|---|-----------|-----------|
| T1a–c | UTF-8 pinned at every text boundary + regression tests + entry-point streams | PR #11 (unreleased) |
| T2a | `output_tail` on non-ok `spawn_complete` lines | PR #14 (unreleased) |
| T2b | Seat probe before staging | PR #14 (unreleased) |
| T3b | Truthful skip reason | PR #13 (unreleased) |
| T8a | Per-check `repair_hint` briefed to the fix spawn | PR #12 (unreleased) |

## Declined (recent)

- Fix budget draws from series budget — superseded by validated recalibration;
  weakens the runaway backstop.
- `SpawnResult.output` structured stderr accessor — LOW singleton, acceptable
  as-is; revisit only if a structured consumer appears.
