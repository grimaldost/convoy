# convoy feedback — packaging the agent-serving plugin + blind-probe dogfooding

- **Date:** 2026-07-04
- **Tool/version:** convoy 0.1.0 (exercised on branch `feat/agent-serving-plugin` @ `b04fda3`; PR #2 not yet merged, so `main` is still 0.0.1 — version read from `pyproject.toml`/`plugin.json` on the branch)
- **Context:** Designed and built convoy's agent-facing layer to a paste-in "plugin frame" (one MCP tool set + one skill + manifests): a stdio MCP server (`interface/mcp/`) with `convoy_run`/`convoy_init`, an extracted `run_service.run_series_headless` shared by the CLI and the tool, `skills/convoy/SKILL.md`, and `.claude-plugin/` manifests. Dogfooded the agent-facing surface with a four-round blind-probe loop (two fresh `claude -p` agents per round, each given only the rendered tool schemas + skill).
- **Outcome:** The plugin landed clean (gate green, `claude plugin validate .` clean, `claude mcp list` shows the server `✔ Connected`, a no-spend `dry_run` through the installed plugin returns `validated`); the blind probe converged from both agents answering "can't use every feature" to both answering "can, all params documented." But the install-verification smoke call then caught a **blocker**: `convoy_init` hangs the MCP client on Windows — it completes its git-scaffold side effects yet never returns the tool result, and by strong inference the real `convoy_run` is affected too (both shell out to subprocesses under the stdio server).

## What worked

- **The v1 fixes from the prior dogfooding (PR #1) directly enabled this layer.** `convoy_init`/`scaffold` became the `convoy_init` tool's return with no rework; `preflight`/`validate` became the tool's free `dry_run` no-spend mode verbatim; the exit-code taxonomy + reporter made the structured MCP result envelope a mechanical mapping. The on-ramp work paid off one release later.
- **Functional core / imperative shell made the service extraction a lift, not a rewrite.** `run_series_headless` is the body of `cli.run` moved behind a function that raises instead of exiting; the CLI kept identical behavior (tests green with only monkeypatch-target moves), and the MCP tool reuses the exact same path. The seam the architecture already had is the seam the frame wanted.
- **The telemetry contract made a rich structured result nearly free.** `summarize_run` is a pure aggregation over `spawns.jsonl` filtered by `run_id`; per-spawn granularity + the additive `gate_complete`/`pr_skipped` events meant the tool could report per-PR gate state and economy totals without a single new plumbing change. Versioned, append-only, run_id-tagged telemetry is exactly the shape an agent-facing summarizer needs.
- **The design's own C7 note ("agent-facing layer = a skill") anticipated this work.** The frame only added the always-on MCP surface on top; nothing in the design fought the packaging.

## Friction

- **[MED]** `[[checks]]` is a required section with a ≥1-entry rule, but that requirement is only discoverable by tripping it (`missing required section [[checks]]`) or reading `02-formats.md`. A fresh author/agent constructing a minimal series hits it. The error is clear; the schema's required-vs-optional shape is not surfaced anywhere an author looks first.
- **[LOW]** The CLI tests monkeypatch `cli.run_series` at its import site, so extracting the shared service required moving 8 patch targets to `run_service.run_series`. A minor coupling to the import site; not wrong, but it made a behavior-preserving refactor touch the tests.
- **[LOW]** After `uv sync` pulled the new `mcp` dependency, the freshly-written `pytest.exe`/`ty.exe` console-script shims were blocked by a Windows application-control policy (`os error 4551`); `uv run python -m pytest` / `-m ty` worked. Environment, not convoy — but any convoy contributor on locked-down Windows will hit it, so the `uv run python -m …` convention is worth stating in `CLAUDE.md`.

## Misses

- **[BLOCKER] `convoy_init` hangs the MCP client on Windows — and by strong inference so does a real `convoy_run`.** Driving the *installed* plugin over stdio (both via the bare cache-venv python and via the exact production command `uv run --project <cache> python -m convoy.interface.mcp`), a `convoy_init` call completes all its side effects — the demo is scaffolded and `workspace/` is a committed git repo on `base` (`seed` commit present) — but the tool-call **response never returns to the client**; it times out at 45–90s, reproducibly. A git-free `convoy_run(dry_run=true)` on the same server returns instantly (`validated`). The differentiator is that `convoy_init` shells out to `git` (six commands via `subprocess.run` in `interface/scaffold.py::_init_workspace`), and a subprocess spawned under a **stdio** MCP server that inherits the server's std handles (or leaves a lingering Git-for-Windows child, e.g. an fsmonitor/maintenance process) keeps the JSON-RPC pipe from ever signalling message-complete to the client. The real `convoy_run` shells out even more (`HeadlessSpawn` → `claude -p`, and `SubprocessGateRunner` → each check), so the plugin's core action almost certainly hangs the same way over MCP — only the no-spend `dry_run` (pure pre-flight, no subprocess) is safe. This makes the plugin's two shelling-out entry points unusable over the very surface they are meant to be driven through. **phase: integration test.** The unit tests (`tests/test_mcp_server.py`) call the tool coroutines directly via `asyncio.run`, never over a real stdio-server subprocess, so they never exercise the "subprocess under a stdio server" path; nothing tested the transport. (Not paid-confirmed for the real `convoy_run` — inferred from the identical shell-out pattern; `convoy_init` is confirmed.)
- **[MED] `[review].blocking` is a required field that is inert in v1** — the driver never reads it (only `dump_series` does); the merge-blocking gate is entirely `[[checks]].blocking`. Both blind-probe agents independently flagged the apparent contradiction ("skill says a red always blocks, yet the example sets `[review].blocking = false`"). A required field with no v1 consumer is a footgun that reads as a contradiction. **phase: design / spec review** (a required spec field with no runtime consumer should have been caught when the spec was defined).
- **[LOW] Re-run leaves the workspace un-resettable.** A completed or halted `convoy_run` leaves the `integration` and PR branches behind; a re-run does `git.checkout(<branch>, create=True)` and collides. There is no resume (a stated v2 goal) and no `--fresh`/reset affordance, so the documented recovery is "manually reset base and delete the branches." Surfaced directly in the blind probe (agents asked how to safely re-run). **phase: design** (the walk-away flow has no defined re-entry).

## Vacuous gates

None observed. The build gate (`ruff` + `ty` + `pytest`, 260 tests) is substantive, and the blind probe is a real adversarial gate — it failed the docs twice before passing, and caught a genuine doc defect (`[review].blocking`) rather than rubber-stamping.

## Proposed promotions / changes

1. **[BLOCKER]** Stop MCP-served subprocesses from hanging the client (miss above): every subprocess convoy spawns while serving over stdio — `interface/scaffold.py::_git`, `interface/headless_spawn.py` (`claude -p`), `interface/gate_runner.py` (each check) — must run with all three std streams redirected away from the server's stdio (`stdin=subprocess.DEVNULL`, `stdout`/`stderr` to pipes) and no handle inheritance (`close_fds`), and on Windows should suppress Git-for-Windows background children (e.g. `-c core.fsmonitor=false -c maintenance.auto=false` on the scaffold's git calls). Add an **integration test that drives the tools over a real stdio server subprocess** (not the current direct-`asyncio.run` calls) so a `convoy_init` round-trip returning is asserted. This is the top priority — it makes the shelling-out tools usable over the plugin at all. Home: `interface/scaffold.py`, `interface/headless_spawn.py`, `interface/gate_runner.py`, `tests/`.
2. **[MED]** Resolve the `[review].blocking` inert-field footgun (miss above): make it **optional** (`default false`) in `core/spec.py` and mark it "reserved for the v2 blocking LLM self-review" in `docs/design/02-formats.md`, OR wire the self-review the flag implies. Either removes a required no-op that both blind agents read as contradicting `[[checks]].blocking`. Home: `core/spec.py` + `docs/design/02-formats.md`.
3. **[MED]** Add a re-run affordance (miss above): a `convoy run --fresh` / `convoy_run(reset=true)` that resets the workspace to `base` and deletes the prior `integration` + PR branches, or make per-PR branch creation reuse-or-reset instead of `create=True`. Home: `interface/drivers/headless.py` + a CLI flag / MCP param. Closes the "how do I re-run" gap the probe surfaced.
4. **[LOW]** Give runtime failures a structured shape: a could-not-start real run returns `error` as an opaque string, unlike the located `problems` list. Consider a `{kind, message}` for git/filesystem/governance runtime failures so an agent can branch on them. Home: `interface/run_service.py` + `interface/mcp/server.py`.
5. **[LOW]** Guard concurrent runs on one workspace: currently unsupported and unguarded (two runs would corrupt the tree silently). A workspace lock that fails loud would match convoy's fail-loud posture. Home: `interface/run_service.py`.
6. **[LOW]** Consider a launch-and-poll mode for `convoy_run`: a real run blocks the MCP call for minutes-to-hours (it spawns nested agents). A background-run + status-tool shape would fit agent ergonomics better than one long synchronous call — and dovetails with fixing #1. Home: `interface/mcp/server.py` (`dry_run` covers the fast path today).

## Method note (for the maintainer, not a convoy defect)

The blind-probe loop was an effective acceptance gate for agent-facing docs: two independent fresh agents per round, given only the rendered schema + skill, marking `UNDER-DOCUMENTED` rather than guessing. It converged in four rounds (both-false → both-true), pinpointed the exact surface to fix each round (schema description > docstring > skill), and its one "real defect" find (`[review].blocking`) was a code/doc contradiction a human review had missed. Worth keeping as the ship gate for any future convoy agent surface.

## Cost (blind-probe verification runs; no convoy engine run occurred)

No paid convoy engine run (`claude -p` spawns) happened this session — the spend was the blind-probe verification workflow. All agents ran on `claude-opus-4-8`.

| Round | Agents | Subagent tokens | Duration |
|------:|-------:|----------------:|---------:|
| 1 | 2 | 85,230 | ~72s |
| 2 | 2 | 91,191 | ~157s |
| 3 | 2 | 92,778 | ~160s |
| 4 | 2 | 93,373 | ~151s |
| **Total** | **8** | **~362,572** | — |

$ not computed (internal Claude Code subagent tokens, not a metered provider bill). Signal: ~45k tokens per blind agent per round; four rounds was the cost of converging the docs to both-agents-pass.
