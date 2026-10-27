# Recipe: judge Claude Code Workflow agents with `convoy gate`

A copy-pasteable recipe for running implementer agents from a Claude Code Workflow script and
having the project's gate, not the implementers' own reports, decide whether each one is done.
It follows [ADR-0011](../adr/0011-the-runner-is-frozen-the-gate-is-the-product.md): the runner
is frozen, the gate recipe lives in a native Workflow, and `convoy gate`, armed by a
`.convoy/gate.toml` whose hash is on the trust list, is one possible judge in it.

The commands and the `hook.log` lines were first checked against convoy 0.17.1, and checked
again on 2026-10-25 against the
[CONV-B75](../backlog.md#conv-b75--a-worktree-isolated-subagent-is-judged-against-the-main-checkout-not-the-worktree-that-holds-its-changes)
fix, which ships in the first release after 0.17.2 and changes which tree a worktree agent is
judged in ([Worktree-isolated agents](#worktree-isolated-agents)). The commands were run; the
`hook.log` lines in [What the log shows](#what-the-log-shows) were produced by feeding hand-built
`SubagentStop` events to `convoy hook`, not by a live Workflow run, so they show the record's
shape and not a Workflow agent's own transcript. The only observation of the hook under the
Workflow tool is the dated probe,
[2026-10-08-subagentstop-under-workflow.md](../notes/2026-10-08-subagentstop-under-workflow.md),
which predates the fix; no Workflow run has exercised the worktree behaviour yet, and the tests
named in that section pin it.

## What you need

- The convoy plugin installed in the Claude Code session that runs the Workflow, so its
  `SubagentStop` hook is wired (`hooks/hooks.json`):

  ```sh
  claude plugin marketplace add grimaldost/convoy
  claude plugin install convoy@convoy
  ```

  Or a project that wires `convoy hook` itself in its own `.claude/settings.json`.
- `uv`, which the plugin's hook runs through, and the `convoy` command for the setup commands
  below (`uv tool install git+https://github.com/grimaldost/convoy`).
- A git repository that is the session's project root, where the session was started. The hook
  uses the nearest `.convoy/gate.toml` above the agent's `cwd`, then
  `$CLAUDE_PROJECT_DIR/.convoy/gate.toml`, then, for an agent in a linked git worktree, the main
  checkout's (`gate_service.find_gate_spec`). An agent in the project checkout therefore runs
  the project's spec, and an agent in a worktree is judged in its worktree (see
  [Worktree-isolated agents](#worktree-isolated-agents)).

## Step 1: write the gate

Create `.convoy/gate.toml` in the project root. This is a small but complete shape: a gate-only
file with a `[series]` id, an optional `[governance]` timeout and three `[[checks]]`, one for every
agent and one each for two phases:

```toml
[series]
id = "my-project"

[governance]
timeout_seconds = 300

[[checks]]
name = "tests"
run = "uv run pytest -q"
blocking = true
repair_hint = "make the failing tests pass without weakening them"

[[checks]]
name = "api-contract"
run = "python scripts/check_api.py"
blocking = true
phases = ["api"]
repair_hint = "the API module must expose the documented functions"

[[checks]]
name = "cli-contract"
run = "python scripts/check_cli.py"
blocking = true
phases = ["cli"]
```

The rules the loader and the gate enforce (`core/spec.py`, `gate_service.run_gate`):

- `name`, `run` and `blocking` are required on every check; names are unique.
- A check with no `phases` runs for every agent. A check with `phases` runs only for an agent
  whose brief carries one of those tags (below).
- **Every phase tag you put in a prompt must appear in some check's `phases`.** A tag no check
  declares makes the gate refuse to run (outcome `usage`), because a green from the remaining
  checks would look gated while it never was.
- The selection must contain a blocking check; a selection of advisory checks only is refused.
- `timeout_seconds` is read from `[governance]` and bounds each check (default 300). The
  checks together should fit the gate budget of 1500 s, because Claude Code kills a hook at
  1800 s and says nothing; `convoy validate` warns past it.

To start from the project's own toolchain instead of by hand, `convoy gate --init` scaffolds
`.convoy/gate.toml` (and a `.gitignore` for the hook's log and locks) from what it finds, and
`convoy gate --init --independent <name>` adds a held-out oracle placeholder under
`CONVOY_ORACLES`. The scaffold does not arm the hook. Edit it, then arm it as below. The project's
own suite is what an implementer can satisfy by self-report; the defects the gate exists to catch
need a check the implementer cannot reach, written before the implementer is dispatched
(see `docs/authoring-series.md`, "Gate granularity", and `skills/convoy/SKILL.md`, "The
per-project gate").

Check the file and run it once by hand:

```sh
convoy validate .convoy/gate.toml     # prints: ok (gate-only)
convoy gate --phase api               # runs "tests" and "api-contract"; exit 0 green, 1 blocking red, 3 usage
```

## Step 2: arm the hook

The hook executes nothing from a project this machine has not trusted, so a cloned
`.convoy/gate.toml` cannot run commands on dispatch until you say so. From the project root:

```sh
convoy gate --trust
```

The exact effect (`gate_service.trust_project`): the project root and the sha256 of
`.convoy/gate.toml` are recorded in `~/.convoy/hook-trust.toml` (`$CONVOY_HOME` overrides
`~/.convoy`). The command prints `trusted <root> for the hook, spec <path> pinned (<trust file>)`.
`--workspace <dir>` names the project when you are not in it.

- **Re-run `convoy gate --trust` after every deliberate edit of the spec.** A spec that no longer
  matches its pinned hash is refused loudly (exit 2, outcome `spec_changed`), because the
  implementer edits the tree the spec lives in and a gate it can rewrite is no gate.
- `convoy gate --init` does not trust the project it scaffolds; run `--trust` after it.
- `convoy gate` with no argument prints `note: the hook is not armed for this project` on stderr
  until the project is trusted, so it is also the check that arming took.
- A harness that stages a fresh workspace can instead set `CONVOY_TRUSTED_ROOTS` (roots separated
  by `os.pathsep`) in the environment of the process that launches Claude Code; those roots carry
  no hash pin.

## Step 3: mark the phase in each agent prompt

Put `[convoy-phase: <tag>]` in the prompt you pass to `agent()`. The judge reads the first user
turn of the subagent's transcript, which is that prompt, and runs the checks a PR carrying that
tag would be gated on: the checks with no `phases` plus the checks that list the tag
(`hook.parse_phase_markers`).

- Several tags: `[convoy-phase: api, cli]`, or several markers; the tags union.
- No marker: the whole gate runs.
- Use one distinct tag per task. The tag is also what lets you attribute a log line to a task
  afterwards, because the Workflow script is not handed the subagent's `agent_id`.

## Step 4: the Workflow script

Plain JavaScript, for the Workflow tool. It runs the implementers one after another, then has a
read-only agent return the judge's fields from `.convoy/hook.log` and sorts the tasks into green,
residual red and not judged. Pass `args` as real JSON, not a string.

How the log is read matters, so it is stated before the script. A Workflow script has no file
access, so a reader agent has to fetch the log. The reader cannot use Bash and cannot be given a
`schema`: the judge treats any tool outside its read-only list as a write (`hook.READ_ONLY_TOOLS`),
and Bash and the `StructuredOutput` call a schema forces are not on it, so either would make the
reader a gated subagent. That leaves Claude Code's Grep and Read tools. Both shorten long lines: a
plain Grep prints `[Omitted long matching line]` in place of any matching line of about 500
characters or more, and a real judge line is 1100 to 1700 characters (it carries the paths, the
spec hash and every check's `detail`), so a plain Grep returns no verdict at all. The script
therefore asks Grep for only the fields it needs (`-o`, which prints just the matched parts, each
prefixed with its line number), and rebuilds one record per line number. A fragment that is itself
long, such as a `repair_brief` with a full test failure in it, is omitted too, so the script does
not ask for it.

```js
export const meta = {
  name: 'gated-implementation',
  description: 'Run implementers one at a time and read back what the convoy hook judged',
  phases: [
    { title: 'Implement', detail: 'one agent per task; the hook judges each when it stops' },
    { title: 'Read the log', detail: 'a read-only agent returns the judge fields of this run' },
  ],
}

// args: {
//   since: '2026-10-19T12:00:00+00:00',   // UTC, ISO-8601 with +00:00, earlier than this run
//   tasks: [{ tag: 'api', brief: 'Implement ...' }, { tag: 'cli', brief: 'Implement ...' }],
// }
// Every tag must be listed in the `phases` of some check in .convoy/gate.toml.
const { since, tasks } = args

// The fields of a judge record that decide the verdict, as short Grep matches.
const FIELDS = String.raw`"ts": "[^"]*"|"leg": "[^"]*"|"agent_id": "[^"]*"|"stop_hook_active": [a-z]+|"outcome": "[^"]*"|"phases": \[[^\]]*\]|"blocked_stop": [a-z]+|"reason": "[^"]*"|"error": "[^"]*"|"tree_mismatch": [a-z]+`

phase('Implement')
for (const task of tasks) {
  // Sequential, so the agents share the project checkout safely. To run writers in parallel,
  // give each `isolation: 'worktree'` (see "Worktree-isolated agents").
  // Add model / effort here if the task needs a tier other than the session's.
  await agent(`[convoy-phase: ${task.tag}]\n${task.brief}`, {
    label: `implement ${task.tag}`,
    phase: 'Implement',
  })
}

phase('Read the log')
// No schema and no Bash on this agent (see above). Grep is on the read-only list.
const text = await agent(
  'Call the Grep tool once, with these arguments: path ".convoy/hook.log" (in the project root), ' +
    'output_mode "content", -o true, head_limit 0, and this exact pattern:\n\n' +
    FIELDS +
    '\n\nReply with the tool output exactly as it is, one line per line, nothing else. ' +
    'Reply NONE if nothing matches.',
  { label: 'read hook.log', phase: 'Read the log' },
)

// Grep -o prints `<line>:<match>`. Rebuild one record per log line.
const byLine = {}
for (const raw of String(text).split('\n')) {
  const m = raw.trim().match(/^(\d+):(.*)$/)
  if (!m) continue
  try {
    Object.assign((byLine[m[1]] ||= { line: Number(m[1]) }), JSON.parse(`{${m[2]}}`))
  } catch {
    // an omitted or mangled fragment: that field stays unknown
  }
}
const lines = Object.values(byLine)
  .filter(record => record.leg === 'judge' && record.ts >= since)
  .sort((a, b) => a.line - b.line)

const verdicts = tasks.map(task => {
  const mine = lines.filter(record => (record.phases || []).includes(task.tag))
  const last = mine[mine.length - 1]
  if (!last) return { tag: task.tag, state: 'not judged' }
  if (last.outcome === 'completed') {
    // Judged in another tree than the agent's: a red only in its worktree was not seen.
    if (last.tree_mismatch === true) return { tag: task.tag, state: 'green in another tree', log_line: last.line }
    return { tag: task.tag, state: 'green' }
  }
  if (last.outcome === 'blocked' && last.blocked_stop === false) {
    // The failing checks' text: `convoy gate --phase <tag> --brief` prints it as JSON.
    return { tag: task.tag, state: 'residual red', log_line: last.line, agent_id: last.agent_id }
  }
  return { tag: task.tag, state: last.outcome, reason: last.reason || last.error, log_line: last.line }
})

log(verdicts.map(v => `${v.tag}: ${v.state}`).join('; '))
return verdicts
```

What was checked: the Grep call above, with this pattern, was run on a `hook.log` made by the
hook (judge lines of 1100 to 1700 characters, one more with a 4400-character `repair_brief`), and
the parsing was run under Node with `agent()` stubbed to return that Grep output. It gave `green`
for a pass, `residual red` for a residual red, `usage` with its `error`, and `not judged` for a tag
with no line; the same run with every line omitted, as a plain Grep would return, gave `not
judged` throughout. The `tree_mismatch` field and the `green in another tree` state were checked
the same way on 2026-10-25, against a `hook.log` written by the CONV-B75 hook. What was not
checked: a live Workflow agent making the Grep call and repeating its output, because no
Workflow run was available. If that agent mangles the pattern or the
output, the failure is `not judged`, never a green. A `spec_changed` line carries no `phases`, so
its task also reads `not judged`; the line itself is in the log.

What happens when a task's agent tries to stop: Claude Code fires `SubagentStop`, the hook runs
the gate in the tree the agent worked in (its worktree, for an isolated agent), and

- green: the hook exits 0, says nothing, and the agent stops;
- blocking red: the hook exits 2 with the repair brief on stderr, which Claude Code hands to the
  **agent** as the reason it may not stop yet. The agent repairs its own work and tries to stop
  again, and the gate re-runs. This is the one repair round; the brief is the failing checks'
  `detail` plus each check's `repair_hint`.

The script above never sees either exchange. Its only evidence is the log.

## What the log shows

Each firing appends one JSON line to `.convoy/hook.log` in the project root; an agent working in a
worktree of the project is logged there too, not in the worktree. Count the lines with
`"leg": "judge"`; the `messenger` leg does not fire for Workflow agents. Below, fields that do not
help in reading the verdict (`session_id`, `tool_name`, `tool_use_id`, `model`, `cwd`,
`convoy_version`, `checks`, `spec`, `spec_sha256`, `workspace`, `gate_ms`, and `anchor`,
`agent_tree` and `tree_mismatch`, which [Worktree-isolated agents](#worktree-isolated-agents)
describes) are left out. Timestamps
and ids are from the run that produced them.

**Pass.** `outcome` `completed`, no red, hook exit code 0:

```json
{"ts": "2026-10-19T22:14:09.192+00:00", "event": "SubagentStop", "leg": "judge", "agent_id": "agent-pass", "agent_type": "workflow-subagent", "stop_hook_active": false, "outcome": "completed", "series_id": "wave-demo", "phases": ["api"], "blocking_red": false, "independent_red": false, "counts": {"selected": 2, "passed": 2, "failed": 0}, "repair_brief": "", "exit_code": 0}
```

**Red, first stop.** `outcome` `blocked`, `blocked_stop` true, hook exit code 2. The brief is in
`repair_brief`, and was sent to the agent on stderr:

```json
{"ts": "2026-10-19T22:14:10.866+00:00", "event": "SubagentStop", "leg": "judge", "agent_id": "agent-red", "agent_type": "workflow-subagent", "stop_hook_active": false, "outcome": "blocked", "series_id": "wave-demo", "phases": ["api"], "blocking_red": true, "independent_red": false, "counts": {"selected": 2, "passed": 1, "failed": 1}, "repair_brief": "## Failing checks to repair\n\n- api-contract: exited 1:\nstderr:\napi module missing\n  repair hint: the API module must expose the documented functions", "blocked_stop": true, "exit_code": 2}
```

If the agent then repairs its work, the next line for the same `agent_id` has
`"stop_hook_active": true` and `outcome` `completed`. The last line for a task is what the script
reads.

**Residual red.** The agent stopped again and the gate is still red. `stop_hook_active` is true,
`outcome` is still `blocked`, but `blocked_stop` is false, there is a `reason`, and the hook
exits 0, so the agent is allowed to stop:

```json
{"ts": "2026-10-19T22:14:12.511+00:00", "event": "SubagentStop", "leg": "judge", "agent_id": "agent-red", "agent_type": "workflow-subagent", "stop_hook_active": true, "outcome": "blocked", "series_id": "wave-demo", "phases": ["api"], "blocking_red": true, "independent_red": false, "counts": {"selected": 2, "passed": 1, "failed": 1}, "repair_brief": "## Failing checks to repair\n\n- api-contract: exited 1:\nstderr:\napi module missing\n  repair hint: the API module must expose the documented functions", "blocked_stop": false, "reason": "residual red after the repair round; the subagent may stop", "exit_code": 0}
```

From a shell, `grep '"blocked_stop": false' .convoy/hook.log` lists every residual red (the log is
written with Python's default JSON separators, so that spelling is exact).

Other `outcome` values on a judge line, all from `hook.py`:

| `outcome` | Meaning | Hook exit |
|---|---|---|
| `skipped` | Read-only subagent; not gated. `reason` says so. | 0 |
| `usage` | The gate could not run: an unknown phase tag, an invalid spec, a dead workspace. `error` has the reason; on the retry the agent may stop. A workspace a `convoy run` is driving is also `usage`, but refused with exit 2 on every firing. | 2, then 0 on the retry |
| `busy` | Another firing held `.convoy/judge.lock` past the wait bound. On the retry the agent stops ungated, with its own `reason`. | 2, then 0 on the retry |
| `spec_changed` | The spec no longer matches the trusted hash. Re-run `convoy gate --trust`. | 2 |
| `untrusted` | Written only for an agent in a worktree of a trusted project, when the worktree carries a spec nothing trusted vouches for and the project has no spec of its own (next section). Nothing ran. `reason` says so. | 0 |

An untrusted project leaves no line in its own tree at all (the plugin's guard exits before
starting `convoy`, and `convoy hook` itself writes nothing into an untrusted project), so a
missing line is never a green. A task that shows `not judged` in the
script, with the hook installed, is most often one of: the project was never trusted, no
`.convoy/gate.toml` was found above the agent's `cwd`, in the session's project or in the
worktree's main checkout, the agent used only read-only tools, the spec changed after it was
trusted or a worktree's spec differs from the trusted one, or a worktree's spec could not be
vouched for (a `spec_changed` or `untrusted` line has no `phases`, so the script cannot attribute
it to a task), or Claude Code killed a hook that outran its 1800 s timeout. A task that shows
`green in another tree` was judged in the project checkout while its agent worked in another
tree, a separate repository nested in the project: a red only there was not seen (next
section).

## Worktree-isolated agents

An agent started with `isolation: 'worktree'` works in a linked git worktree, which Claude Code
puts under `<project>/.claude/worktrees/<id>`. The hook judges it in that worktree, so the checks
see the agent's edits, by one of two specs:

- **The worktree's own spec**, when the worktree carries one (the spec is committed): the walk up
  from the agent's `cwd` finds it first. The worktree is not on the trust list itself: it runs on
  the entry of the project it was made from (the session project, else git's main checkout), as
  long as that entry pins a hash, the project's spec still matches it, and the worktree's spec
  matches it too, with CRLF and CR line endings read as LF so git's line-ending conversion is no
  difference.
- **The project's trusted spec, run in the worktree**, when the worktree has no spec of its own
  (the spec is untracked in the project, the state `convoy gate --init` leaves until you commit)
  or its copy cannot be vouched for (the project is trusted only through `CONVOY_TRUSTED_ROOTS`,
  or by an entry with no pinned hash). The spec is read from the project, where it was trusted;
  the checks run in the worktree (`gate_service.gated_tree`). In the second case a stderr line
  says the nearest spec is not vouched for, and `fallback_from` in `hook.log` names it.

Either way the verdict is logged in the project's `.convoy/hook.log`, a blocked verdict carries
`convoy gate: judged <worktree> against <spec>`, and the default oracles directory is the
project's, so an independent check finds the oracle the scaffold wrote there.

To use it:

- **Trust the spec from the project**, with a pin: `convoy gate --trust --workspace <project>`.
  Commit it before starting isolated agents if they should run their own copy. Never run
  `--trust` inside an agent's worktree. A worktree that carries its own `.convoy/gate.toml`
  would have the pin trust whatever the worktree holds; one without would record the main
  checkout's spec as it stands on disk, uncommitted edits included, from a tree the operator
  did not name. No message from convoy asks for it there; the advice names the project.
- Give each parallel writer its own worktree. Writers that share one checkout are not safe: the
  judge lock makes their gates take turns, but each gate judges whatever the others have half
  written. Worktrees judged by the project's spec each take a judge lock of their own, so they do
  not wait for each other.

The cases in which the agent's work is not judged:

| Case | What happens | Trace |
|---|---|---|
| The worktree's spec differs from the trusted one, or the project's spec changed since it was trusted | Refused (`spec_changed`) once, with a message addressed to the operator; on the retry the agent stops unjudged. | `spec_changed` lines in the project's `hook.log`. The messenger leg reports the refusal to an orchestrator on an `Agent` dispatch, but it did not fire for Workflow agents (Known limits). |
| The worktree carries a spec, the project is trusted without a pin (or only through `CONVOY_TRUSTED_ROOTS`), and the project has no spec of its own | Nothing runs: nothing trusted vouches for the worktree's spec, and there is no project spec to judge it by. | An exit-0 stderr line, `convoy gate: <worktree> was not judged — ...`, which Claude Code keeps out of the model's context, and an `untrusted` line in the project's `hook.log`. |
| The agent works in a separate repository nested in the project, not a worktree of it | The project's checkout is judged. A red only in the nested repository passes. | An exit-0 stderr line, `convoy gate: judged <project> against <spec> — not <tree> ...`; `"tree_mismatch": true` and `agent_tree` in `hook.log`; `green in another tree` in the script above. |

Read-only agents are not gated wherever they run (`skipped`, above).

The tests that pin this, all in `tests/test_hook.py`:
`test_a_worktree_agent_is_judged_in_its_own_worktree`,
`test_an_untracked_project_spec_judges_the_agents_worktree`,
`test_a_project_that_cannot_vouch_for_a_worktree_spec_judges_the_worktree`,
`test_a_worktree_spec_nothing_trusted_can_vouch_for_leaves_a_trace`,
`test_a_nested_repository_is_judged_in_the_project_and_says_so`,
`test_a_differing_worktree_spec_is_refused_once_then_let_through`,
`test_a_changed_anchor_spec_reached_from_a_worktree_is_refused_once`,
`test_a_worktree_spec_differing_only_in_line_endings_is_judged`,
`test_a_worktree_agent_is_judged_and_reused_without_a_project_dir` and
`test_run_hook_logs_a_worktree_verdict_in_its_anchors_log`; `tests/test_mcp_server.py`'s
`test_convoy_gate_and_the_hook_judge_the_same_worktree` pins that `convoy_gate` agrees.

## A residual red after the repair round

The judge blocks an agent's stop once. If the gate is still red on the retry, the red is recorded
(`blocked_stop` false, above) and the agent is let go, so it cannot be held forever by a failure
it cannot fix. The hook's messenger leg is what tells an orchestrator of such a red on a synchronous
`Agent` dispatch, and it did not fire for Workflow agents in the probe. So the script learns of a
residual red only by reading `.convoy/hook.log`, which is why the example ends by reading it.

This is the shape of backlog row
[CONV-B60](../backlog.md#conv-b60--on-the-agent-tools-default-dispatch-a-residual-red-after-the-judges-repair-round-reaches-nobody),
written for the Agent tool's default dispatch: the row proposes to measure first how often the
judge's one round leaves a residual red (the `blocked_stop: false` records) and to add an
orchestrator-side leg only if it is common. What to do with a residual red is the script's call:
the result it returns names the log line and the `agent_id`, and the failing checks' text comes
from running `convoy gate --phase <tag> --brief` in the project, which prints the repair brief as
JSON on stdout. That text is what a fix agent should be given, with the same `[convoy-phase]` marker so the
fix is judged too. The script does not read `repair_brief` from the log because a long one is
omitted by the Grep tool (Step 4).

## Known limits

From the probe note and [ADR-0011](../adr/0011-the-runner-is-frozen-the-gate-is-the-product.md),
fact 2:

1. **A gate in a directory the agent does not work in is not found**, even when the agent edits
   that directory. The hook finds the nearest `.convoy/gate.toml` above the agent's `cwd`, then
   the one in the project the session was started in, then, for a worktree, its main
   checkout's. (`$CONVOY_GATE_SPEC` in the environment that launches Claude Code names a spec
   elsewhere; neither the probe nor this recipe exercised it.)
2. **The messenger leg did not fire for Workflow agents**, so an orchestrator that started the
   agents from a script hears of a residual red only by reading `.convoy/hook.log` (read from the
   hook's code, not observed: the probe's gates were all green).

Also true of the probe, and worth knowing before you rely on it: it was a probe, not a run of
this recipe. No Workflow script has yet dispatched a series of agents and acted on the judge's
verdicts, which is the end-to-end run ADR-0011 names as the precondition for retiring the runner.

## Where each statement comes from

| Statement | Source |
|---|---|
| `convoy gate [--phase TAG] [--workspace DIR] [--init] [--independent NAME] [--trust] [--json] [--brief]` | `convoy gate --help`, `interface/cli.py` |
| `convoy validate <file>` prints `ok (gate-only)` for a gate-only file | `interface/cli.py` |
| Trust list `~/.convoy/hook-trust.toml`, root plus spec hash | `interface/gate_service.py` (`trust_project`, `trust_status`) |
| Gate discovery order | `gate_service.find_gate_spec` |
| A worktree's trust, anchor and fallback, and the tree its checks run in | `gate_service.trust_decision`, `anchor_of`, `judged_target`, `gated_tree` |
| The judged-tree line and the `anchor`, `agent_tree`, `tree_mismatch`, `fallback_from` fields | `hook.py` (`_notice`, `_judged_line`) |
| Phase marker `[convoy-phase: <tag>]` | `interface/hook.py` (`parse_phase_markers`) |
| Repair brief text and one repair round | `core/gate.py` (`repair_brief`), `hook.py` (`_decide_stop`) |
| Log record fields and `outcome` values | `hook.py` (`_record`, `_verdict_record`, `_decide_stop`) |
| Plugin hook wiring | `hooks/hooks.json`, `interface/hook_guard.py` |
| Behaviour under the Workflow tool | `docs/notes/2026-10-08-subagentstop-under-workflow.md` |
