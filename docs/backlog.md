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

Last reconciled: 2026-07-25, folding one blind-implementer measurement report
(6 findings) into rows **T19–T22** and corroborating **T11a**. The prior full
triage pass was 2026-07-09, after cutting release **0.1.2** (which serves every
row in the Shipped table), covering 4 reports over 2026-07-06..09; rows T13–T18
were added ad hoc from later reports. Reports dated 2026-07-11..17 have **not**
had a full reconcile — T19b is the only finding from that window anchored here
so far.

## Leverage order

**T19a, T10a, T16a, T11a (shipped 0.4.0), T13a, T20a, T12b, T14b (shipped 0.5.0),
T15a, T4a, T14c (shipped 0.6.0).** The stated order is **exhausted** — every row it
named has shipped. The remaining `proposed` rows (T21a, T23a, T24a) have no agreed
sequence between them, so the next pick is a decision to take, not an order to
continue. **T24a** is the one carrying a standing argument: it mechanizes the
release tag, and 0.6.0 is the fourth cut since 0.2.0 proved the manual step is the
one that gets skipped.

T19a jumped the order: it was the only row unblocking a *capability* rather than
recovering cost, and it is what makes an incremental multi-PR series runnable at all.
T10a and T16a then landed together as the planned one-`cli.py`-pass, in separate
commits — they share a file, not a concern.

**0.3.0 is the first tag since 0.1.2.** `0.2.0` was version-bumped and changelogged
on 2026-07-15 but never tagged, so the marketplace kept serving 0.1.2 and *every*
change since — ADR-0007's per-PR governance, the per-model seat probe, and now
T19a — was invisible to installed consumers. That is the failure mode the release
discipline in [CONTRIBUTING.md](../CONTRIBUTING.md) exists to prevent, and it
recurred anyway: bumping the three locked version fields is gated by a test, while
pushing the tag is not. Worth mechanizing (T24a).

## Open rows

| # | promotion | home | status |
|---|-----------|------|--------|
| T10a | `convoy clean <series.toml>` verb: reset to base, delete the series' integration+PR branches, `git clean -fd`, remove the run lock — without starting a run (no seat probe, no lock acquisition). Shipped with `--dry-run`, since the verb deletes files. Recovery was fully manual and was needed ~5× in one campaign; `--fresh` cannot serve it because it acquires the lock and probes the seat before resetting. MCP mirror still optional and unbuilt. | `interface/cli.py`, `interface/git.py`, `interface/workspace_lock.py` | shipped(0.4.0) |
| T10b | Stale-lock auto-reclaim: the lock file already records the owning PID (`workspace_lock.py:43`) but never reads it back — reclaim iff the recorded process is dead. | `interface/workspace_lock.py:34-43` | watch |
| T11a | `--resume` / `resume=true`: continue the existing integration branch, skip every PR whose work it already contains, re-attempt the rest. Containment alone is the WRONG test — an empty PR branch points at the same commit as integration, so `is_merged_into` requires a STRICT ancestor (the driver always merges `--no-ff`). Skipped PRs get a distinct `pr_skipped.reason`. `resume`+`fresh` and `resume` with no integration branch are pre-flight problems. **(consumer-affecting)** | `interface/drivers/headless.py`, `interface/git.py`, `interface/run_service.py`, `interface/cli.py`, `interface/mcp/server.py` | shipped(0.4.0) |
| T12b | Self-describing budget halt: halted PR + phase + spend-vs-cap on the terminal record and in `summarize_run`'s envelope; classification field on `spawn_complete`. Today the cap is recorded nowhere and `RunComplete` carries only `run_id/outcome/integrated`. **(consumer-affecting)** | `core/telemetry.py`, `interface/drivers/headless.py:318-323`, `interface/mcp/server.py` | shipped(0.5.0) |
| T13a | Sanitize the gate-check env: strip `VIRTUAL_ENV` (and uv siblings) via `run_with_timeout`'s existing `env` param; `_ENV_STRIP` in `headless_spawn.py:50-61` is the precedent. A benign uv warning on stderr currently displaces the real failure in `detail` and mis-briefs the fix spawn. | `interface/gate_runner.py:54` | shipped(0.5.0) |
| T13b | Stream-robust `detail`: combine bounded tails of stderr *and* stdout instead of stderr-precedence (`gate_runner.py:70-71`). | `interface/gate_runner.py::_red_detail` | watch |
| T14b | `convoy status` / `convoy_status(series_file, run_id)`: report a run's state and economy from the ledger alone — `running` / `finished` / `unknown` — so the documented long-run pattern (CLI in a background shell) is pollable. A finished outcome is rebuilt from `run_complete` plus the published outcome→exit-code mapping, so no server-side state is held; `run_id` defaults to the latest run. **(consumer-affecting)** | `interface/run_summary.py`, `interface/cli.py`, `interface/mcp/server.py` | shipped(0.5.0) |
| T14c | Detached launch: start a run and return `{run_id, telemetry_path}` immediately instead of blocking for minutes to hours. Split out of T14b, which shipped the polling half — with `convoy_status` in place the remaining work is purely process lifecycle (spawn detached, survive the server exiting, orphan behaviour on Windows vs POSIX), which is a different risk profile and deserves its own change. **(consumer-affecting)** Shipped as `convoy_run(detach=true)`: the child is convoy's own CLI under `python -m convoy run --run-id <id> --json`, so one run path stays one run path, the parent can pin the id it hands back as a handle, and the child records its own verdict even when it dies before the ledger's first line — which `convoy_status` now reads, since reporting a failed launch as `running` forever was the hole a detached launch would otherwise open. | `interface/detached.py`, `interface/mcp/server.py`, `interface/run_service.py` | shipped(0.6.0) |
| T15a | Subcommand context on `GitError` at the `_run_checked` choke point (`git checkout -b <branch>: <stderr>`), enriching every call site at once. Shipped with the hermetic `-c` flags omitted (they ride on every command and would re-bury the subcommand), whitespace-carrying arguments quoted, and an exit-code fallback for the case git exits nonzero having written nothing to stderr — which used to raise a `GitError` whose message was the empty string. | `interface/git.py:43-48` | shipped(0.6.0) |
| T15b | Classify a mid-run git failure as a halt (reuse the infrastructure-halt pattern: `_skip_remaining` + `RunComplete` + distinct outcome) so telemetry doesn't dangle after `run_start`. **(consumer-affecting)** | `interface/drivers/headless.py:235-243`, `core/telemetry.py` | watch |
| T15c | Bounded auto-retry of the branch-setup step before halting (observed environmental `checkout -b` flake). | `interface/drivers/headless.py` | watch |
| T16a | `--workspace <dir>` (default: cwd) on `run`/`validate`, mirroring the MCP tool's explicit argument; at minimum a `--help` line naming the cwd coupling. 4 reports across 4 arcs. | `interface/cli.py` | shipped(0.4.0) |
| T17 | MAX_PATH detection + "scaffold into a shorter directory" hint in `convoy_init`; wire `_error_kind` into `_init_impl` (classifier exists, only `_run_impl` uses it). | `interface/scaffold.py:107,134-136`, `interface/mcp/server.py:196` | watch |
| T18 | Meter the seat probe (a `role: "preflight"` spawn line) if a consumer ever needs to-the-cent totals; probe cost currently precedes the telemetry file. **(consumer-affecting)** | `core/telemetry.py`, `interface/seat_probe.py` | watch |
| T19a | Per-phase `[[checks]]` scoping: a check declares the phases it gates (`phases = ["core"]`), defaulting to `[]` = gates every PR, so existing series are bit-for-bit unaffected. Shipped with a non-blocking pre-flight **advisory** channel (`Advisory` + `PreflightReport`) for the case scoping creates: a PR no blocking check gates, which integrates unverified — allowed, reported, not refused. A `phases` tag no PR declares is a `phases` **problem** (a typo would silently gate nothing). ADR-0008. **(consumer-affecting)** | `core/spec.py`, `core/gate.py`, `core/preflight.py`, `interface/drivers/headless.py` | shipped(0.3.0) |
| T24a | Mechanize the tag step of the release. `tests/test_manifest.py::test_versions_are_locked` gates the three locked version fields agreeing, but nothing gates the tag actually existing — so 0.2.0 was bumped, changelogged and merged while the marketplace went on serving 0.1.2 for ten days, hiding ADR-0007 and everything after it from installed consumers. The gap is structural, not a lapse: the mechanized half of the checklist held, the unmechanized half did not. A **fourth** location drifted the same way and is named nowhere: `uv.lock` recorded `convoy-engine 0.1.1` through the whole of 0.2.0, because `uv sync` is not part of the documented cut. Shape: a `.github/workflows/ci.yml` job on `main` that fails when `pyproject.toml`'s version has no matching `v<version>` tag (or auto-tags), plus folding the lockfile into `test_versions_are_locked`'s agreement check so it cannot drift silently either. Second occurrence of this family — the 2026-07-15 release-discipline report's fix was documentation, which is exactly why it did not prevent this. Shipped in two halves, neither of them a test. The lockfile is caught by `uv lock --check` in CI ahead of every step that would rewrite it — an assertion in `test_versions_are_locked` was written and then removed, because `uv run` re-locks before pytest reads the file, so it could never go red. The tag is caught by a **scheduled** `release-tag` workflow, not a push gate: the tag is created after the release PR merges, so a push gate would fail every release by construction and leave that commit permanently red even once tagged. `CONTRIBUTING.md` now names four locations, not three.| `.github/workflows/ci.yml`, `.github/workflows/release-tag.yml`, `CONTRIBUTING.md`, `AGENTS.md` | accepted |
| T23a | Prompt-path advisory through the channel T19a built: absolute paths inside prompt files that do not resolve on the executing machine become non-blocking `advisories`, so a series authored on one machine surfaces its unportable references before the run instead of as a confused agent mid-PR. Deliberately deferred out of T19a: the detection is a heuristic (distinguishing a real path from prose or a URL, on both Windows and POSIX) and deserves its own design and false-positive budget rather than riding in on an unrelated feature. The channel, the `Advisory` type, and both surfaces already exist. | `interface/preflight_probe.py` | proposed |
| T19b | `[[checks]].terminal = true` (or a `[gate].final` block): checks that run **once after the final PR integrates**, not per-PR — the other half of T19a's cluster (T19a scopes a check to phases; this scopes one to the end of the series), for a whole-series invariant that cannot hold mid-series. Needs a new position in the run loop, after the PR walk, so it is a distinct mechanism sharing T19a's motivation rather than the same field. | `core/spec.py`, `interface/drivers/headless.py` | watch |
| T20a | `convoy run --json`: emit the already-computed run envelope on stdout at end of run, opt-in so stdout stays machine-clean by default. `summarize_run` is surface-bound, not MCP-bound — lifting it out of `interface/mcp/server.py:47` into a shared module is most of the work — so every CLI-driven measurement harness re-implements the per-spawn→per-run fold from `spawns.jsonl` today. Narrower than T14b (reattach to an in-flight run): this is the synchronous, run-just-finished case. **(consumer-affecting)** | `interface/cli.py`, `interface/mcp/server.py:47` | shipped(0.5.0) |
| T21a | Extract the agent CLI's `result` / `subtype` from the seat probe's JSON output into the `Problem` message, keeping the raw tail as trailing detail. `seat_probe.py:62` puts a 500-char tail of the raw CLI JSON blob in the message, so an expired auth session reads as noise with the actionable diagnosis buried mid-blob. Same family as the shipped `output_tail` work (T2a), which fixed the scored-spawn variant; this is the pre-flight variant, where the text is already present but unextracted. | `interface/seat_probe.py:61-67` | proposed |
| T22a | Per-role `effort` under `[governance]` — the same shape as the existing per-role `budgets` / `tools` tables. `effort` is series-global today and applies to implementation and fix alike, but a fix spawn repairing a small gate red plausibly wants a different level than the implementation that produced it. Distinct axis from the per-PR `model`/`tier`/`effort` override shipped in 0.2.0 (that varies by PR; this varies by role) — and note `resolve_spawn` already keys on role, so the seam exists. **(consumer-affecting)** | `core/spec.py`, `core/governance.py` | watch |
| T5a | Mixed-tier design decision. Resolved: optional per-PR `model`/`tier`/`effort` falling back to `[governance]` (ADR-0007, supersedes ADR-0005); `budget`/`budgets` stay rejected as a per-role axis. Propagation to the sibling planning tool that emits per-PR tiers is still outstanding. | `core/spec.py` + `docs/design/02-formats.md` | accepted |
| T4a | Real commit messages on the residual sweep: `commit_all(pr.id)` fires when an impl spawn ends with uncommitted work, so the bare `pr.id` becomes the message of record (7 occurrences, position-independent). Make the sweep produce a real message or ensure the agent commits. Shipped the first branch: the subject is now `<pr.id>: <the prompt's opening line>`, since a `[[prs]]` entry has no `title` and the brief is already in hand at the commit site. "Ensure the agent commits" was declined as the primary fix — the sweep has to stay as a backstop either way, so it would have added a prompt-side instruction without removing the defect. | `interface/drivers/headless.py:262`, `interface/git.py::commit_all` | shipped(0.6.0) |
| T4b | Commit-provenance telemetry (agent-authored vs engine-synthesized). **(consumer-affecting)** | `core/telemetry.py` | watch |
| T3a | DAG-aware continuation past a halt (continue PRs whose dependency closure excludes the halted PR). Economics largely subsumed by T11a. | `interface/drivers/headless.py`, `core/dag.py` | watch |
| T6a | `files touched: N (+A/-B)` in per-PR impl narration. | `interface/reporter.py` | watch |
| T6b | Per-PR integration state in telemetry — re-evaluate against T12b if it ships. | `core/telemetry.py` | watch |

## Shipped (recent)

All rows below are served by the **0.1.2** tag (2026-07-09).

| # | promotion | shipped by |
|---|-----------|-----------|
| T9a | Cut 0.1.2 and re-tag the plugin so `claude plugin install` serves the fixed engine | release 0.1.2 |
| T1a–c | UTF-8 pinned at every text boundary + regression tests + entry-point streams | PR #11 → 0.1.2 |
| T2a | `output_tail` on non-ok `spawn_complete` lines | PR #14 → 0.1.2 |
| T2b | Seat probe before staging | PR #14 → 0.1.2 |
| T3b | Truthful skip reason | PR #13 → 0.1.2 |
| T8a | Per-check `repair_hint` briefed to the fix spawn | PR #12 → 0.1.2 |
| T7a | "Adopting convoy in an existing project" section | PR #16 → 0.1.2 |
| T7b | Deliberate non-features documented | PR #16 → 0.1.2 |
| T9b | Release discipline in contributor docs | PR #16 → 0.1.2 |
| T12a | Budget-calibration guidance | PR #16 → 0.1.2 |
| T14a | Long-run pattern documented (CLI in background) | PR #16 → 0.1.2 |

## Declined (recent)

- Fix budget draws from series budget — superseded by validated recalibration;
  weakens the runaway backstop.
- `SpawnResult.output` structured stderr accessor — LOW singleton, acceptable
  as-is; revisit only if a structured consumer appears.
