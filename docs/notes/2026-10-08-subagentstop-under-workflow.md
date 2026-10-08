# `SubagentStop` under the Workflow tool — 2026-10-08

**Question.** convoy's hook (`convoy hook`) judges a subagent when Claude Code fires
`SubagentStop`. The Workflow tool starts agents from a script (`agent()`), not through the
`Agent` or `Task` tools. Does `SubagentStop` fire for agents the Workflow tool starts, with and
without worktree isolation; with what `cwd`; and what does the judge see?

## Verdict

`SubagentStop` fires for Workflow agents, with and without `isolation: 'worktree'`; the
payload's `agent_type` is `workflow-subagent`, and a `[convoy-phase: <tag>]` marker in the
`agent()` prompt reaches the judge. The payload `cwd` is the session project root for a
non-isolated agent and the agent's own worktree for an isolated one. In both cases the judge
found the project spec at `$CLAUDE_PROJECT_DIR/.convoy/gate.toml` and ran the gate in the session
project root, so a worktree-isolated agent was judged against the main checkout, not its
worktree. A gate in a directory the agent edits but does not work in was never discovered. The
messenger leg (`PostToolUse` on `Agent|Task`) left no record for either agent.

## Environment

- Claude Code 2.1.293 (desktop entrypoint) on Windows 11; the `claude` CLI on `PATH` was 2.1.291.
- convoy plugin 0.16.1, installed. Its `hooks/hooks.json` wires `SubagentStop`
  and `PostToolUse` (`Agent|Task`) to `uv run --project "${CLAUDE_PLUGIN_ROOT}" convoy hook`,
  timeout 1800 s. The hook process saw
  `CLAUDE_PLUGIN_ROOT=<home>/.claude/plugins/cache/convoy/convoy/0.16.1` and
  `CLAUDE_PROJECT_DIR=<project>`.
- Before the probe there was no `~/.convoy/hook-trust.toml` and no `.convoy/` in `<project>`.
- Both rounds used one session; every agent ran with model `haiku`, effort `low`.

## Setup

`T` is a scratch git repository under `<scratch>/probe/T`, outside `<project>`. Its gate,
`T/.convoy/gate.toml`:

```toml
[series]
id = "probe-t"

[[checks]]
name = "probe-evidence"
run = 'python "<scratch>/probe/probe_check.py" T'
blocking = true
phases = ["probe-a1", "probe-b1", "probe-a2", "probe-b2"]
```

The evidence check, `<scratch>/probe/probe_check.py`, appends one JSON line per run to
`<scratch>/probe/probe-evidence.ndjson` and exits 0:

```python
import datetime, json, os, sys
rec = {
    'label': sys.argv[1] if len(sys.argv) > 1 else '',
    'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds'),
    'check_cwd': os.getcwd(),
    'CLAUDE_PROJECT_DIR': os.environ.get('CLAUDE_PROJECT_DIR'),
    'CLAUDE_PLUGIN_ROOT': os.environ.get('CLAUDE_PLUGIN_ROOT'),
    'ppid': os.getppid(),
}
with open(r'<scratch>/probe/probe-evidence.ndjson', 'a', encoding='utf-8') as f:
    f.write(json.dumps(rec) + '\n')
```

The gate was validated once by hand, then trusted:

```
convoy gate --workspace T --phase probe-a1      # [ok ] probe-evidence, outcome completed, exit 0
convoy gate --trust --workspace T               # T's root and spec hash added to the trust list
```

The by-hand run wrote one evidence line with label `T`, `check_cwd` `T`, and
`CLAUDE_PROJECT_DIR` null, which confirms the check records what it is run with.

Each probe agent was started with `agent()` from a Workflow script, model `haiku`, effort `low`,
and a prompt that began with `[convoy-phase: <tag>]`, then: use the Write tool to create the file
`T/probe-<tag>.txt` containing the single line `<tag>`, and reply with the single word `done`.
In each round one agent ran with no isolation and one with `isolation: 'worktree'`. The agents
were told to write into `T` by absolute path, so the isolated agent's own worktree stayed
unchanged.

## Round 1 — only T's gate armed

Workflow run `wf_b6974ce7-711`, two agents:

| Label | agentId | Isolation | Result |
|---|---|---|---|
| probe-a1 | `a5d6783b1437d67dc` | none | `done` |
| probe-b1 | `ac464b171d308e67d` | worktree | `done` (preceded by one line naming the file it wrote) |

Both files exist in `T`. `T/.convoy/hook.log` does not exist and `probe-evidence.ndjson` was not
created: the judge never ran T's gate.

Round 1 alone cannot say whether the hook fired. With no gate spec reachable from the payload
`cwd` or from `$CLAUDE_PROJECT_DIR`, the hook exits 0 and writes nothing (`hook.py::decide`
returns before any record is built), so "did not fire" and "fired and found nothing" leave the
same trace, which is none.

## Round 2 — control: a second trusted gate at the session project root

To tell the two apart, an untracked gate was added at the session project root with the same
check under the label `ROOT` (series id `probe-root`, the same four phases), and trusted:

```
<project>/.convoy/gate.toml                 # [series] id = "probe-root"; run = '... probe_check.py" ROOT'
convoy gate --trust --workspace .           # run in <project>; spec sha256 d927eba4...
```

Workflow run `wf_7edbbf40-6d1`, two agents:

| Label | agentId | Isolation | Result |
|---|---|---|---|
| probe-a2 | `aac2c6440a7448fdc` | none | `done` |
| probe-b2 | `ab829481fc36b2f43` | worktree | `done` |

Both files exist in `T`. `<project>/.convoy/hook.log` holds two lines, one per agent (values as
recorded; `session_id`, `tool_name`, `tool_use_id`, `convoy_version` and the per-check detail
are left out):

```json
{"ts": "2026-10-08T16:33:11.082+00:00", "event": "SubagentStop", "leg": "judge", "agent_id": "aac2c6440a7448fdc", "agent_type": "workflow-subagent", "model": "claude-haiku-5-5", "stop_hook_active": false, "cwd": "<project>", "outcome": "completed", "series_id": "probe-root", "phases": ["probe-a2"], "blocking_red": false, "independent_red": false, "counts": {"selected": 1, "passed": 1, "failed": 0}, "gate_ms": 136, "spec": "<project>\\.convoy\\gate.toml", "spec_sha256": "d927eba45ecd795138d89bc7f25f06504a7e02478683a939fa1e7d3345facd1f", "workspace": "<project>", "exit_code": 0}
{"ts": "2026-10-08T16:33:12.210+00:00", "event": "SubagentStop", "leg": "judge", "agent_id": "ab829481fc36b2f43", "agent_type": "workflow-subagent", "model": "claude-haiku-5-5", "stop_hook_active": false, "cwd": "<project>\\.claude\\worktrees\\wf_7edbbf40-6d1-2", "outcome": "completed", "series_id": "probe-root", "phases": ["probe-b2"], "blocking_red": false, "independent_red": false, "counts": {"selected": 1, "passed": 1, "failed": 0}, "gate_ms": 130, "spec": "<project>\\.convoy\\gate.toml", "spec_sha256": "d927eba45ecd795138d89bc7f25f06504a7e02478683a939fa1e7d3345facd1f", "workspace": "<project>", "exit_code": 0}
```

`probe-evidence.ndjson` holds two lines, both label `ROOT` (the `T` label never appears), each
with `check_cwd` `<project>` and `CLAUDE_PROJECT_DIR` `<project>`:

```json
{"label": "ROOT", "ts": "2026-10-08T16:33:11.072+00:00", "check_cwd": "<project>", "CLAUDE_PROJECT_DIR": "<project>", "CLAUDE_PLUGIN_ROOT": "<home>/.claude/plugins/cache/convoy/convoy/0.16.1", "ppid": 22756}
{"label": "ROOT", "ts": "2026-10-08T16:33:12.199+00:00", "check_cwd": "<project>", "CLAUDE_PROJECT_DIR": "<project>", "CLAUDE_PLUGIN_ROOT": "<home>/.claude/plugins/cache/convoy/convoy/0.16.1", "ppid": 9244}
```

Agent ids to labels, from the two Workflow run journals: `a5d6783b1437d67dc` probe-a1,
`ac464b171d308e67d` probe-b1, `aac2c6440a7448fdc` probe-a2, `ab829481fc36b2f43` probe-b2. The ids
in `hook.log` are the journal ids, so each line is tied to its agent. Each evidence timestamp
precedes its log line by about 10 ms and 11 ms, which is the gate running before the record is
written.

What round 2 shows:

- The hook fires for Workflow agents under both isolation settings, with `agent_type`
  `workflow-subagent`, and the `[convoy-phase: ...]` marker selected the phase (`phases`
  `["probe-a2"]` and `["probe-b2"]`).
- The non-isolated agent's payload `cwd` was `<project>`; the isolated agent's was its worktree,
  `<project>\.claude\worktrees\wf_7edbbf40-6d1-2`.
- For both, `spec` was `<project>\.convoy\gate.toml` and `workspace` was `<project>`, and the
  evidence check ran with `check_cwd` `<project>`. The isolated agent's gate ran in the main
  checkout.
- T's gate was not discovered in either round, though it was trusted and its phases matched.
- Neither log has a `leg: messenger` line. The Workflow tool did not dispatch these agents through
  `Agent` or `Task`; a `PostToolUse` event for any other tool name returns silent with no record,
  so the absence is what that predicts. Whether `PostToolUse` fired for the Workflow tool itself
  was not observed.
- Both gates were green. No red, no `exit 2` and no retry (`stop_hook_active` true) was observed.
- The probe's isolated agent wrote into `T`, not into its own worktree, so it left the worktree
  unchanged and the harness removed it. The probe shows which tree the gate ran in; it does not
  show a gate judging a worktree's changes.

## Derived from code, not observed

Gate discovery is `gate_service.find_gate_spec`: `$CONVOY_GATE_SPEC` when set (refused when it
names a missing file), then `$CLAUDE_PROJECT_DIR/.convoy/gate.toml`, then `.convoy/gate.toml` in the
payload `cwd` and each of its parents. The first file that exists wins; an environment root with no
spec falls through to the walk.

- With a committed `.convoy/gate.toml` the main checkout always has it, so the
  `$CLAUDE_PROJECT_DIR` candidate wins for every worktree agent as well. The probe used an
  untracked spec; the committed case is read from the code only.
- A worktree under `<project>/.claude/worktrees/` sits inside the main checkout, so the walk alone
  reaches the main checkout's spec when the worktree has none. A worktree that carries its own
  committed spec is still skipped while `$CLAUDE_PROJECT_DIR` is set and has a spec, because that
  candidate comes first.

## What it means for using the gate inside a Workflow run

Facts and consequences only; nothing here changes code.

- The per-project gate judges a non-isolated Workflow agent in the session project, on the
  strength of `SubagentStop` and the `[convoy-phase: <tag>]` marker, exactly as it judges an agent
  started through the `Agent` tool.
- A worktree-isolated Workflow agent is judged against the main checkout, not against its
  worktree. Checks that read the working tree therefore see the main checkout's files, so they
  cannot see edits that live only in the agent's worktree. Observed with an untracked spec; by the
  discovery order above it holds for a committed spec too.
- A gate that sits in a directory other than the session project, even one the agent edits, is not
  found.
- The messenger leg did not fire for these agents. On a blocking red the judge still answers the
  subagent with the repair brief (design doc 03, `convoy hook` row), and after the retry it records
  the residual red in `.convoy/hook.log`; an orchestrator that started the agents from a script
  hears of that residual only if it reads `.convoy/hook.log`. This is read from the hook's
  description and code, not from a red observed in the probe.

## Cleanup performed

- `<project>/.convoy/` removed (it was created for round 2).
- `~/.convoy/hook-trust.toml` removed (it did not exist before the probe; it held the entries for
  `T` and `<project>`).
- `git status` in `<project>` clean afterwards.
- The Workflow runs' worktrees were removed by the harness, all unchanged.
- `T`, the evidence check and the evidence files remain under `<scratch>`.
