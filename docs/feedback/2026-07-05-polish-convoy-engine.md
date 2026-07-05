# convoy feedback — polish review + self-hosted dogfood of its own backlog

- **Date:** 2026-07-05
- **Tool/version:** convoy 0.1.1 (executed the installed plugin at
  `~/.claude/plugins/cache/convoy/convoy/0.1.1` for the dry-run, and the local `main` @ `86e331d`
  engine for the paid run; both 0.1.1 per `pyproject.toml` / `__version__`).
- **Context:** Full polish pass — read the whole engine (~3.1k LOC), design docs, `SKILL.md`, and
  the MCP surface; ran a blind 7-dimension execution-audit (16 subagents, adversarial verify) over
  docs vs code; then **dogfooded the engine on its own backlog**: authored a 2-PR convoy series
  (feedback #3 re-run reset, #5 workspace lock) on a clone of convoy itself, gated by convoy's own
  `ruff + ruff format + ty + pytest` build gate, and ran it for real.
- **Outcome:** Clean self-host. The engine drove `claude-sonnet-5` through both PRs to
  `completed`/integrated, **green on the first gate attempt, no fix loops, $3.08 total**. Both
  features are production-quality on review; landed as stacked PRs #6/#7. The audit surfaced no
  blockers — nine confirmed doc/parse defects, fixed in PRs #4/#5.

## What worked

- **The engine ran its own backlog end-to-end, cleanly.** functional-core/imperative-shell paid
  off directly: both features (reset, lock) slotted into `interface/` with **zero `core/` changes**
  and no telemetry-contract touch. The DAG (pr-2 `depends_on` pr-1) sequenced correctly; pr-2
  branched off pr-1's integrated state and saw its `run_service.py` changes, so the two coupled
  features composed without conflict inside the run.
- **The telemetry contract made the economy report free — for an *external* consumer, exactly as
  designed.** I reconstructed the full per-spawn economy table straight from `spawns.jsonl` (not via
  the MCP summarizer), joining on `run_id` — the "any consumer joins on it without convoy knowing
  about that consumer" claim held in practice. `cost_estimated:false` on both lines (real metered
  cost), and the additive `gate_complete` events made the attempt-0-green result self-explaining.
- **First *paid* confirmation of config-isolation end-to-end.** The scored spawns authenticated
  under a credential-only `CLAUDE_CONFIG_DIR` (no instant infra-halt), so isolation-ON works on a
  real run on this host — a gap the prior (no-paid-run) session could not close.
- **The non-independent build gate was legible and, here, sufficient.** A red would have blocked
  and driven the fix loop; both PRs passed attempt-0, and the reporter's stderr narration
  (`impl ok $x  N turns  Ns` / `gate PASS` / `integrated`) gave a clean human trace alongside the
  machine telemetry.

## Friction

- **[MED] A real run blocks the caller for its full duration with no progress signal.** The run took
  **9m43s**. I deliberately ran it via the **CLI in the background** rather than the synchronous MCP
  `convoy_run`, precisely because the MCP call would have blocked the tool invocation for ~10 min
  with no way to observe progress or intervene — I wanted to watch `spawns.jsonl` live. This is
  lived confirmation of open finding #6 (launch-and-poll), not a hypothetical.
- **[LOW] The CLI `run` forces `cwd == workspace`** (no `--workspace` flag), while the MCP tool
  takes an explicit `workspace`. Running the engine against the clone required `cd <clone> &&
  uv run --project <convoy> python -m convoy.interface.cli run <series>`. A `--workspace` option
  would remove the cwd coupling and match the MCP surface.
- **[LOW] `spawn_complete.input_tokens` is dominated by folded-in cache reads** (3.0M / 2.5M on the
  two spawns). Correct for cost attribution (`_tokens` folds `cache_read`/`cache_creation` in on
  purpose), but a consumer reading `input_tokens` as "prompt size" would be off by ~100×. The field
  name doesn't distinguish. Contract observation, not a defect — the field is frozen — but the
  magnitude is a legibility trap worth a doc note.

## Misses

- **[MED] Two real spawn-parse bugs the unit tests never exercised.** `num_turns` silently reported
  `0` when the terminal `result` event omits or floats it (the assistant-turn fallback ran only when
  *no* result arrived); and a budget-capped spawn whose partial result text mentions a usage phrase
  was classified `infrastructure` (exit 2) instead of `budget` (exit 4). **phase: test design** —
  the stub fixtures never covered a result event with missing `num_turns` or a budget subtype whose
  text carries a usage phrase (a "synthetic-fixtures-only" gap). Fixed in PR #4 with CLI-shaped
  regression fixtures.
- **[MED] Doc-vs-code drift the docs' own review never caught.** `telemetry.py` said "three v1
  events" (there are five); `01-gate.md` presented a phantom `IsolationProbe(Protocol)` /
  `check_isolation` that ships as the free function `isolation_result`; `02-formats.md` attributed
  "DAG acyclicity" validation to `spec.py` (it lives in `preflight`/`dag.order` — `load_series`
  accepts a cyclic/duplicate graph); `SKILL.md` dropped the run_id random suffix; the driver's
  integration-branch comment called `git checkout -b` an idempotent "ensure it exists" step.
  **phase: doc review** — the design docs were never re-synced after the code settled. Fixed in
  PR #5.
- **[MED] The `review` governance role is required-but-inert in v1** — `[governance.budgets].review`
  and `[governance.tools].review` are required at load, but the driver spawns only `implementation`
  and `fix`. Same footgun class as `[review].blocking` (which #2 fixed) but for the budgets/tools.
  **phase: spec/design review** (a required field with no v1 consumer). Documented as reserved in
  PR #5. extends `2026-07-04-plugin-serving-blind-probe#2`.

## Vacuous gates

- **Not vacuous, but structurally self-grading — flagged for honesty.** The dogfood's build gate was
  `independent = false` (the implementing agent wrote its own tests), so a subtly-wrong feature with
  matching tests could have passed it. It did not here — Sonnet wrote genuinely substantive tests
  (incl. the lock's leak/busy properties and an end-to-end bare-vs-`--fresh` re-run), and my
  independent diff review + gate re-run were the real backstop. This is inherent to self-hosting (an
  independent oracle for "did it implement `--fresh` right" is hard to author generically), not a
  convoy defect — but worth recording that the dogfood's safety came from human review, not the gate.

## Proposed promotions / changes

1. **[MED]** Launch-and-poll mode for `convoy_run` — extends
   `2026-07-04-plugin-serving-blind-probe#6`. **New evidence:** this session could not use the
   synchronous MCP tool for the real run at all (a 9m43s block with no observability); it fell back
   to CLI-in-background. A background-run + status-tool shape is now demonstrated-necessary. Home:
   `interface/mcp/server.py`.
2. **[MED]** re-run reset (#3) and workspace lock (#5) — extends
   `2026-07-04-plugin-serving-blind-probe#3` and `#5`. **Now LANDED** as PRs #6/#7, built by the
   dogfood itself and reviewed. For triage: mark #3 and #5 addressed pending merge, not open.
3. **[LOW]** Add a `--workspace` option to the CLI `run` so it does not force `cwd == workspace`
   (the MCP tool already takes an explicit workspace). Home: `interface/cli.py`.
4. **[MED]** Close the spawn-parse test-design gap the two PR #4 bugs exposed: give the stub-based
   spawn tests a fixture matrix of real-CLI `result`-event variance (missing/float `num_turns`,
   budget subtype + usage-phrase text, cache-heavy usage). Home: `tests/test_headless_spawn.py`
   (partly done in #4).
5. **[LOW]** Note the `input_tokens` cache-fold magnitude prominently in `SKILL.md` / `02-formats.md`
   so a consumer does not misread it as prompt size. Doc-only — the field is a frozen contract, do
   **not** rename or split it. Home: `docs/design/02-formats.md`.
6. **[LOW]** Design docs that mirror code (`# src/...` blocks in `01-gate.md`) drift silently — the
   phantom `IsolationProbe` sat in the doc while the code shipped a free function. Either trim
   code-mirror blocks to tested signatures, or mark them "as-of-draft". Home: `docs/design/`.

## Cost / economy (mandatory — the paid engine run)

Run `20260705T123625Z-3338e0f9`, series `convoy-selfhost-ergonomics`, `claude-sonnet-5`, effort
medium, config-isolation ON. Outcome `completed`, integrated, exit 0. Per-spawn budgets impl $3 /
fix $1.5 (review $0.5, inert); `max_fix_attempts` 2 — never engaged.

| PR | role | class | cost_usd | in_tok (cache-folded) | out_tok | turns | duration_s | gate |
|----|------|-------|---------:|----------------------:|--------:|------:|-----------:|------|
| pr-1-workspace-reset | implementation | ok | 1.7677 | 3,018,096 | 19,870 | 45 | 282.7 | PASS @0 |
| pr-2-workspace-lock  | implementation | ok | 1.3097 | 2,543,826 | 15,650 | 38 | 243.7 | PASS @0 |
| **Total** | 2 spawns | completed | **3.0774** | 5,561,922 | 35,520 | 83 | 526.4 (≈9m43s wall) | 2× PASS @0 |

`cost_estimated: false` (real metered cost). No fix spawns, no skips, no budget/infra halts. Economy
reconstructed directly from `spawns.jsonl` by joining on `run_id`.

> Separate spend note (not a convoy engine run): the blind execution-audit ran as a Workflow of 16
> subagents totalling ~957k subagent tokens — that is the audit harness, not a convoy `claude -p`
> run, and is reported against the craft skills, not here.
