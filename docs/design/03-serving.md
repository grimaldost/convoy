# convoy — the serving layer

> Draft, 2026-07-09 (rev. 2026-07-25, resynced with 0.2.0: the seat probe now
> covers every distinct model, and the envelope carries a per-PR
> `effective_model`). Read [00-overview.md](00-overview.md) first. The serving
> layer postdates the founding docs (it shipped in 0.1.0/0.1.1 and after; see
> `CHANGELOG.md`): one request-level run operation shared by two surfaces — the
> `convoy run` CLI and an MCP stdio server — plus the safeguards around a run's
> lifecycle and the packaging that lets an agent install and drive convoy as a
> plugin. Everything here is shell (`src/convoy/interface/`); the core is
> untouched.

## One operation, two surfaces

`run_series_headless` (`interface/run_service.py`) is the request-level
operation extracted from the `convoy run` CLI: pre-flight, workspace lock,
config isolation, seat probe, optional fresh reset, output-dir creation, and
engine wiring, in one tested path. Both surfaces call it; neither owns a private run
path that could drift.

It raises typed errors instead of exiting: `PreflightError` (carrying every
located `Problem`) when pre-flight is not clean, and the engine's
`GovernanceError` / `GitError` / `OSError` unchanged; the workspace lock raises
`WorkspaceBusyError`. Each caller maps them to its own surface — the CLI to an
exit code and a stderr message, the MCP tool to a structured result. The other
verbs share their internals the same way: `convoy validate` and the tool's
`dry_run` both call `preflight` (`interface/preflight_probe.py`), and `convoy
init` and `convoy_init` both call `scaffold` (`interface/scaffold.py`).

## The run lifecycle — safeguards in order

A real run passes these stages, in this order (`run_series_headless`):

1. **Pre-flight** — the pure structural checks plus the filesystem probes
   (prompts exist, `outputs` out-of-tree, asset isolation). A `PreflightError`
   here precedes any side effect: no lock, no spawn, no git mutation. Pre-flight
   returns a `PreflightReport` carrying two lists: the blocking `problems` that
   decide runnability, and non-blocking `advisories` that do not (today: a PR that
   phase-scoped checks leave with no blocking check, so it integrates unverified).
   Only `problems` raises; advisories are reported and the run proceeds. They are
   reported on **every** path, the run included: on a run they ride the `run_start`
   telemetry line and the reporter narrates them under the run header. Until 0.7.0 the
   run path computed them and dropped them, so the ungated-PR advisory said nothing on
   the run that actually integrated the unverified PR.
2. **Workspace lock** (`interface/workspace_lock.py`) — an exclusive lock file,
   `<workspace>/.git/convoy-run.lock` (under `.git`, so it never dirties the
   tracked tree), created with `O_CREAT | O_EXCL` and holding the run's pid. A
   second run against the same workspace raises `WorkspaceBusyError` instead of
   interleaving git operations. Held from right after a clean pre-flight through
   the end of the run; released on both normal and error exit. A hard-killed
   process (no `finally` ever ran) can leave a stale lock; the error message
   says it can be removed by hand.
3. **Seat probe** (`interface/seat_probe.py`) — a minimal spawn through the
   *same* adapter and credential-only config dir the scored run will use, run
   once per **distinct model the run can spawn on** (the `[governance]` model
   plus any per-PR override), in first-PR-seen order: a tool-less brief (`Reply
   with exactly: ok`), low effort, default permission mode, a $0.05 budget cap,
   a 120-second timeout. An `'infrastructure'` classification (expired seat,
   usage limit, retry exhaustion, or an invocation the CLI refuses outright) or a
   CLI that cannot start becomes a
   `kind='seat'` pre-flight problem — located at the section that *declared* the
   failing model, `[governance]` or the overriding `[[prs]]` table — and the run
   stops with zero side effects, before the fresh reset or any branch is staged.
   Probing stops at the first dead model: once the seat is proven unable to
   serve one, there is nothing to gain by paying to probe the rest. `'ok'` and
   even `'budget'` pass: the seat answered. The probe is pre-flight, not a
   scored spawn — it writes no telemetry line, and it costs ~$0.05 per distinct
   model (usually one to three).
4. **Optional resume** — with `--resume` / `resume=true`, the run continues the
   existing integration branch instead of creating one, and skips every PR whose
   work that branch already contains. Two consistency checks run in pre-flight,
   before any side effect: `resume` with `fresh` is rejected (fresh deletes the
   branch resume continues from), and `resume` with no integration branch is
   rejected rather than quietly starting a full run, which is the expensive
   failure when the real cause is a wrong workspace. "Already contained" means a
   **strict** ancestor (`Git.is_merged_into`), not mere containment: a PR branch
   whose implementation committed nothing points at the same commit as the
   integration branch, and treating that as done would silently drop a PR that
   never landed.
5. **Optional fresh reset** — with `--fresh` / `reset=true`, `Git.reset_to_base`
   (`interface/git.py`) checks out the base branch and force-deletes the
   integration branch and every PR branch the series names, so a completed or
   halted run re-runs without manual git surgery. Off by default: a leftover
   branch still fails loud exactly as before.
6. **Engine** — the `outputs` dir is created and `run_series`
   (`interface/drivers/headless.py`) takes over.

## Config isolation — credential-only scored spawns

A scored spawn must not inherit the operator's ambient config — settings, hooks,
plugins, memory — or runs are neither reproducible nor comparable across
operators. `isolated_config` (`interface/config_isolation.py`) builds a
throwaway temp config dir holding *only* the authenticating credential (the
`.credentials.json` file, copied from `$CLAUDE_CONFIG_DIR` or `~/.claude` when
present; keychain-backed auth keeps no file there, so the dir is simply empty
and still authenticates). The spawn adapter receives it as `CLAUDE_CONFIG_DIR`;
the dir is removed on exit, including on error, with the credential file
unlinked first so the plaintext token is gone even if the directory removal
fails. The seat probe runs through the same isolated dir, so it proves the
credential the scored run will actually use.

Alongside the config dir, the spawn env strips billing and routing overrides
(API keys, auth tokens, base-URL and alternate-backend variables — the C5
invariant, `interface/headless_spawn.py`).

Isolation is on by default with a deliberate escape: the CLI flag
`--no-config-isolation` or a truthy `CONVOY_NO_CONFIG_ISOLATION` environment
variable (read by the CLI entry point only), and the tool argument
`config_isolation=false`. Note the polarity: the flag turns isolation *off*,
the tool argument states it *positively*.

## The MCP stdio server

`src/convoy/interface/mcp/` is the agent-facing surface: a stdio server
(`python -m convoy.interface.mcp`, in-process Python) exposing three tools that
mirror the CLI verbs but return structured dicts instead of exit codes and
console text (`interface/mcp/server.py`):

- **`convoy_run(series_file, workspace, dry_run=false, config_isolation=true,
  reset=false, resume=false, detach=false)`** — run a series through the headless
  engine and return the summary envelope below. `dry_run` pre-flights for free: no
  git mutation, no spawn (seat probe included), no spend. `detach` returns a handle
  instead of a result (below).
- **`convoy_init(directory)`** — scaffold the runnable starter series and
  return `{ok, created, series_file, workspace, next}`, naming the paths to
  hand straight to `convoy_run`.
- **`convoy_status(series_file, run_id='', workspace='')`** — report a run's state
  and economy so far from the ledger, including a run still in progress and a run
  this server never started. Spends nothing, holds no state between calls, writes
  nothing. `workspace` is optional and read for exactly one thing: the run lock
  there names its owner process, which is what tells `dead` apart from `running`.

Each tool offloads its blocking work with `asyncio.to_thread`, which keeps the
server's event loop responsive — but `convoy_run` itself still blocks until the
run completes, and a real run is minutes to hours. There are two ways not to wait:
the CLI in a background shell, or `detach=true`.

### Detached launch

`convoy_run(detach=true)` starts the run and returns at once with
`{ok: true, outcome: "started", state: "running", run_id, pid, telemetry_path,
result_path, log_path, next}` — a handle, not a result. `ok` reports the launch,
since the run has no verdict yet; `state` uses `convoy_status`' vocabulary so one
branch handles both envelopes.

The child is convoy's own CLI, started as `sys.executable -m convoy run
--run-id <id> --json` (`interface/detached.py`). Three things follow from that
choice:

- **One run path stays one run path.** No second engine wiring to drift.
- **The run id is pinned by the parent.** A handle the caller cannot poll by is
  not a handle, and the child cannot be asked afterwards what id it chose. Hence
  `--run-id`, which refuses an id the ledger already holds lines for: every fold
  selects by `run_id`, so reusing one would sum two runs' economies into a single
  envelope with nothing downstream able to detect it (a `kind='run_id'`
  pre-flight problem).
- **The child records its own verdict.** Under `--json` its stdout is exactly one
  envelope on every path, so `result_path` holds the answer even for a run that
  died before the engine wrote a ledger line. `convoy_status` reads that file when
  the ledger holds nothing under the id — otherwise a detached run that hit a busy
  workspace or an expired seat would report `running` forever. The ledger wins
  whenever it has anything; a half-written file does not parse and is treated as
  absent.

The **free pre-flight still runs in the calling process**, so a malformed series
is refused immediately: detaching is about not waiting for the run, not about
deferring what is knowable now. What genuinely needs the running process — the
seat probe, the workspace lock, git — is the child's to discover. `dry_run` takes
precedence over `detach`: a pre-flight is free and instant, so there is nothing to
detach.

Detachment is `start_new_session` on POSIX and `DETACHED_PROCESS |
CREATE_NEW_PROCESS_GROUP` on Windows. Neither escapes a **job object**: a host that
confines its children to a job with kill-on-close still takes the run down when it
exits. Convoy does not attempt `CREATE_BREAKAWAY_FROM_JOB` — that limit is usually
a deliberate host policy, and breaking out of it silently would be worse than
honouring it. A run killed that way stops advancing, which is what `convoy_status`
reports.

### A run whose driver is gone

The ledger records only completions, so `running` was derived from the *absence* of a
terminal line — which is exactly what a killed driver leaves behind. Every correct
long-run integration therefore reimplemented an OS process query on the side.

The lock supplies the missing fact. A run acquires the workspace lock before it writes its
first ledger line and holds it until it returns, and the lock has always recorded its
owner's pid; nothing read it back. `convoy_status`, given a `workspace`, does: a run with
ledger lines, no `run_complete`, and a lock naming a process that no longer exists is
`dead`. The terminal fields stay `null` — `dead` is the absence of an outcome, not one of
them — and the economy is final rather than partial.

Two limits are deliberate. **`dead` is claimed only on positive evidence**: no lock file at
all reads `running`, because the commonest way to see that is asking from the wrong
directory, and a false `dead` sends an operator to restart a run that is still spending.
And **a pid is reusable** once its process is gone, so a live check cannot answer for a run
that died last week and whose lock has since been cleared.

That second limit is why the recovery path writes the fact down rather than leaving it to be
queried. When `convoy clean` clears a stale lock it appends a terminal `run_abandoned` line
for the run that left it, if that run recorded no outcome of its own — the last moment at
which the abandonment is establishable. From then on the entry reads `finished` with
`outcome: "abandoned"`, whether or not any lock survives. It is the only write `clean` makes
outside the workspace, it is append-only like every other, and it is idempotent: the line it
writes is itself terminal, so a second `clean` finds a finished run and does nothing.

**The result envelope** is built by `summarize_run`: it reads the on-disk
`spawns.jsonl`, keeps only the lines tagged with this run's `run_id` (the file
is append-only across runs, so a reused outputs dir stays safe), and folds them
into `economy` totals (`total_cost_usd`, `cost_estimated`, token counts,
`num_turns`, `spawn_count`) plus a per-PR view (spawn count, any spawn still
`in_flight`, the implementation
spawn's `effective_model`, the *latest* gate verdict with the names of its
failing blocking checks, any skip reason). `effective_model` is keyed on the
`implementation` role rather than append order — a fix spawn's model never
overwrites it — and is `null` for a PR that never ran an implementation spawn.
The envelope also carries **`halt`** — `null` on a clean run, else the located reason the
run stopped, read from the `run_complete` line rather than threaded through `RunOutcome`
so the envelope stays reconstructible from the ledger alone. It also carries
**`advisories`** — always present, empty when there is nothing to say — read from the
`run_start` line the same way, so a run reports what its pre-flight said and
`convoy_status` can too, without having been the process that pre-flighted it. The per-PR list is
capped at 50 with a `truncated` report; the complete per-line trace stays on
disk at the returned `telemetry_path`, referenced and never inlined. `ok` is
true exactly when `outcome` is `completed`, and the envelope carries the same
`exit_code` the CLI would have returned.

**Failure shape.** A run that cannot start returns `outcome: "usage"` rather
than raising: with `problems` (the located pre-flight list) for a
`PreflightError`, or with `error` plus an **`error_kind`** the agent can branch
on — `spec` (invalid or malformed series), `governance` (unresolvable
model/tier), `git`, `busy` (another run holds the workspace lock), or
`filesystem` (any other `OSError`) — classified by `_error_kind`.

## Subprocess hygiene under a stdio server

The stdio transport makes two ambient assumptions explicit (`interface/proc.py`,
`interface/streams.py`):

- **stdout belongs to the JSON-RPC stream.** Progress narration goes to stderr
  via the `Reporter` (the CLI's default); an MCP run uses the null reporter and
  narrates nothing.
- **No child may inherit the server's stdin.** A subprocess holding the
  inherited JSON-RPC input pipe keeps `subprocess` from ever seeing EOF — the
  hang fixed in 0.1.1. Gate, git, and scaffold children run with `stdin=DEVNULL`; the
  agent spawn gets its own pipe, closed by `communicate`.
- **Hermetic git.** Every git invocation carries `GIT_HERMETIC_FLAGS`
  (`core.fsmonitor=false`, `maintenance.auto=false`, `gc.auto=0`) so no
  background daemon outlives the command holding an inherited handle.
- **One text policy.** Every text-mode child is decoded as UTF-8 with
  replacement (`TEXT_ENCODING` / `TEXT_ERRORS`), never via the locale default
  (cp1252 on Windows raises mid-run); both entry points call
  `harden_std_streams` so convoy's own output cannot raise `UnicodeEncodeError`
  on a legacy-encoded stream.

## Plugin packaging — the repo is its own marketplace

`.claude-plugin/plugin.json` declares the plugin and its MCP server (launched as
`uv run --project ${CLAUDE_PLUGIN_ROOT} python -m convoy.interface.mcp`);
`.claude-plugin/marketplace.json` lists that plugin with `source: "."`. The
repository therefore serves itself: `claude plugin marketplace add
grimaldost/convoy`, then `claude plugin install convoy@convoy` — no clone
needed, and the plugin runs from its own cache clone so local edits never
perturb it. A reference skill (`skills/convoy/SKILL.md`) ships alongside,
documenting the tool arguments, the result envelope, cost and latency, when not
to use the tools, and the full series.toml schema.

## CLI ↔ MCP parity

The two surfaces expose one engine; the mapping is mechanical.

| CLI | MCP tool | Notes |
|---|---|---|
| `convoy run SERIES [--workspace DIR]` | `convoy_run(series_file, workspace)` | the CLI defaults the workspace to its working directory; `--workspace` makes it explicit, as the tool's argument always was |
| `convoy validate SERIES [--workspace DIR]` | `convoy_run(..., dry_run=true)` | same pre-flight; neither spawns (seat probe included) nor mutates. Advisories print to stderr / fill the `advisories` key, and change neither the exit code nor `ok`/`outcome` — so `validate` can write to stderr and still exit `0` |
| `--no-config-isolation` / `CONVOY_NO_CONFIG_ISOLATION` | `config_isolation=false` | polarity inverted; the env escape is read by the CLI entry point only |
| `--fresh` | `reset=true` | the same `Git.reset_to_base` path |
| `--resume` | `resume=true` | continue the existing integration branch, skipping PRs already merged into it; rejected together with `--fresh`/`reset` |
| `--run-id ID` | — | pins the run id instead of minting one; the tool mints its own, and only needs the flag to pin a *detached* child's. An id already in the ledger is refused either way |
| a background shell | `detach=true` | the CLI's answer is the operator's shell; the tool's is a detached child of the same CLI, returning `outcome: "started"` plus the `run_id` to poll |
| `--quiet` | — | an MCP run is always silent (null reporter); the CLI narrates to stderr by default |
| `convoy status SERIES [--run-id ID] [--workspace DIR]` | `convoy_status(series_file, run_id, workspace)` | the same ledger read; `--json` gives the CLI the tool's envelope verbatim. The CLI defaults the workspace to its working directory, the tool never guesses one |
| `convoy clean SERIES [--workspace DIR] [--dry-run]` | — | the recovery verb: no tool equivalent, because it is destructive and takes no run. It restores the tree `--fresh` cannot (uncommitted changes, untracked files) and closes a killed run's ledger entry |
| `convoy init [DIR]` | `convoy_init(directory)` | the same scaffold; the tool result names the follow-up `convoy_run` arguments |

| CLI exit code | MCP result |
|---|---|
| `0` completed | `outcome: "completed"`, `ok: true`, `exit_code: 0` |
| `1` blocked | `outcome: "blocked"`, `exit_code: 1` |
| `2` infrastructure | `outcome: "infrastructure"`, `exit_code: 2` |
| `4` budget | `outcome: "budget"`, `exit_code: 4` |
| `3` usage | `outcome: "usage"`, with `problems` (pre-flight) or `error` + `error_kind` ∈ {`spec`, `governance`, `git`, `busy`, `filesystem`} |
| `convoy validate`: `0` / `3` | `dry_run`: `outcome: "validated"` (`ok: true`) / `"usage"` with `problems`. `advisories` is always present (empty when there is nothing to say) and never affects either |
| — | `detach`: `outcome: "started"` (`ok: true`, `state: "running"`), carrying `run_id`, `pid`, `telemetry_path`, `result_path`, `log_path`. No exit code: the run has not finished |

An executed run's envelope carries `exit_code` alongside `outcome`, so a
consumer that already branches on the CLI's codes needs no second mapping.
