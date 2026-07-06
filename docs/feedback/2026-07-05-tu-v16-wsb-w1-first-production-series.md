# convoy feedback — first production series (tu v1.6 WS-B W1): 3/3 attempt-0 green, 31% of envelope

- **Date:** 2026-07-05
- **Tool/version:** convoy 0.1.1 (CLI `convoy run`, headless; MCP `convoy_init`/`convoy_run` for scaffold + dry-run). Version from `pyproject.toml`.
- **Source slug:** `tu-v16-wsb-w1-first-production-series`
- **Context:** The first real (post-adoption, ADR-0101) production series: wave W1
  (cursor tz-normalization) of the treasuryutils v1.6 WS-B fix campaign. 3 PRs
  (module → routing → docs), model `claude-sonnet-5` series-wide, 5 blocking
  in-tree checks per PR (ruff×2, mypy src, full pytest, core lane), review
  non-blocking, `max_fix_attempts=2`, default config isolation. Spec certified by
  a two-round keel pre-mortem arc before the series was authored. Flow: MCP
  `convoy_init` for the schema example → hand-authored series.toml + prompts →
  MCP `dry_run` preflight → CLI run in a background shell (director loop stayed
  free for a parallel stress fleet).
- **Outcome:** `COMPLETED (integrated)` — 3/3 PRs gate PASS **attempt 0**; total
  **$8.35 vs the ~$27 envelope (31%)**; ~19 min agent time, ~45 min wall including
  gates. Director QA on the integrated branch passed (spec §4 acceptance diff +
  an independent red-check in a worktree: the routing regression tests fail 6/17
  against base+PR1 and pass post-PR2). Merged `--no-ff` by the director.

## What worked

- **The govern-gate-repair loop delivered exactly the promised discipline at
  near-zero overhead.** All three PRs came back gate-green on the first attempt —
  the repair budget was never touched — and the integrated branch needed zero
  director fixes. The per-PR sequencing (each PR branches from the integration
  branch after the previous merge) mapped 1:1 onto the campaign's git discipline.
- **`dry_run` preflight is the right free gate.** Structure/paths/gate-isolation
  validation before any spend; both series validated clean pre-launch, and the
  zero-problems result was trustworthy (nothing surfaced later that preflight
  should have caught).
- **Prompt-embedded hard rules SURVIVED config isolation.** Because
  `config_isolation` strips the operator's CLAUDE.md, the campaign's
  non-negotiables (NO AI attribution in commits — verified absent in all 3 commit
  bodies; `SKIP=` pre-commit env prefix; `python -m` WDAC discipline; TDD
  red-first documentation) were embedded in each prompt — and the scored agent
  honored all of them, including writing red-first evidence ("16 failing") into
  the commit body, which the director's independent red-check then corroborated.
  The isolation model forces prompts to be self-contained and that turned out to
  be a feature: the series file is a complete, auditable record of what the agent
  was told.
- **Per-PR economy narration (`impl ok $X N turns Ys` / `gate PASS (5 checks,
  attempt 0)`) made the campaign cost table a transcription job.** The
  cost/turns/duration lines are exactly what the tool-feedback standard's economy
  table wants.
- **Starter scaffold as schema documentation.** `convoy_init`'s example
  series.toml was sufficient to author a production series without reading the
  format spec — forbidden-key errors (see friction) were the only schema learning
  moment.

## Friction

- **[MED] Per-PR model/tier is forbidden (phase-level only), which fights
  cost-tiered PR plans.** The certified spec assigned sonnet/sonnet/haiku per PR;
  the schema (`_FORBIDDEN_PR_KEYS` in `core/spec.py`, "model/effort/budget are
  phase-level only, 02-formats.md") forced series-wide sonnet, a ~$3 overpay on
  the docs PR. Splitting into a second single-PR haiku series would cost more in
  staging overhead than it saves. Either (a) allow a per-PR `tier` within the
  parity-guard rules, or (b) document the intended pattern for mixed-tier waves
  (one series per tier? absorb the delta?) so spec authors stop planning per-PR
  tiers convoy cannot express.
- **[LOW] CLI/MCP workspace asymmetry.** The MCP tool takes an explicit
  `workspace` param; the CLI has no `--workspace` flag and resolves the workspace
  from cwd. Fine once known (the starter's header comment does say `cd workspace
  &&`), but the asymmetry cost one help-scan; a `--workspace` option (or one
  doc line in `run --help`) would remove it.
- **[LOW] Impl-phase narration can look alarming for surgical PRs.** PR2 (the
  highest-stakes routing PR) reported `7 turns 67.8s $5.27` — from the outside
  indistinguishable from a shallow skim, and it triggered a full director QA +
  red-check (which the PR passed handily; the speed was PR1's TDD scaffolding
  paying off). A one-line `files touched: N (+A/-B)` in the per-PR narration
  would let an operator tell surgical-fast from shallow-fast without spelunking
  the telemetry file.

## Misses

- None attributable this run. No defect reached the integrated branch; gates,
  prompts, and isolation all behaved as documented. (The director QA layer is
  still warranted — gate-green proves exit codes, not spec compliance — but this
  run gave it nothing to catch.)

## Vacuous gates

- None observed. All 5 checks are real external commands with real failure modes
  (two of them — mypy exclude scope and the core-lane shim — had been fixed
  earlier in this same campaign precisely because they COULD go vacuous; they ran
  here in their hardened form).

## Proposed promotions / changes

1. **[MED]** Per-PR `tier` (or a documented mixed-tier series pattern) — friction
   item 1; spec authors currently plan tiers the format cannot express.
2. **[LOW]** `--workspace` flag on `convoy run` (or a help-text line naming the
   cwd rule) — friction item 2.
3. **[LOW]** `files touched: N (+A/-B)` in the per-PR impl narration — friction
   item 3; cheap operator signal separating surgical-fast from shallow-fast.
4. **[LOW — confirmed-win data point]** Keep this run as the adoption baseline:
   first production series, 3/3 attempt-0 green, 31% of envelope, zero repair
   spend, hard-rule compliance through config isolation via self-contained
   prompts. The ADR-0101 adoption bet paid on its first real outing.

## Cost

| PR | impl $ | turns | impl time | gate | integrated |
|---|---|---|---|---|---|
| w1-pr1-cursors-module | $1.2636 | 36 | 552.7s | PASS (5 checks, attempt 0) | yes |
| w1-pr2-route-families | $5.2689 | 7 | 67.8s | PASS (5 checks, attempt 0) | yes |
| w1-pr3-docs-guard | $1.8143 | 42 | 522.2s | PASS (5 checks, attempt 0) | yes |
| **Total** | **$8.3468** | **85** | **~19.0 min** | 15/15 checks | 3/3 |

Wall ~45 min including gate runs (full pytest ×3). Envelope was ~$27 (3 × ~$9
reference): actual = 31%. Zero review/fix phase spend (review non-blocking, no
red gates). Run id `20260705T191825Z-5de00bbe`; telemetry under the series
`outputs/` dir.

## Addendum (same day) — W3 launch: INFRASTRUCTURE outcome, auth root cause invisible to the operator

The W3 series (5 PRs, same pattern) halted twice with `impl infrastructure
$0.0000 1 turns 0.1s` + downstream `skipped`. The halt/skip/telemetry discipline
worked exactly as designed (zero spend, `exit_code:1` recorded, clean
`run_complete outcome=infrastructure`). Root cause found by running the CLI
manually: **the `claude` seat had logged out** ("Not logged in - Please run
/login") between the W1 and W3 runs; the spawn died pre-API.

- **[MED] Surface the spawn's stderr tail on infrastructure exits.** Neither the
  narration line nor `spawns.jsonl` carries WHY the spawn failed — the operator
  sees `exit_code:1, 0.1s, $0` and must reproduce the spawn by hand to learn it
  was an auth expiry. One `stderr_tail` field on `spawn_complete` (or a narration
  suffix) turns a manual diagnosis into a glance. Auth expiry mid-campaign is a
  recurring operational reality (this one hit ~90 min after a clean W1 run on
  the same seat).
- **[LOW] Consider a pre-flight seat check in `run` (non-dry too):** a
  zero-cost `claude -p`-viability probe (or credential freshness check) before
  staging branches would fail the run BEFORE mutating the workspace (the halted
  runs left the tree on the PR branch; `--fresh` recovers, but a pre-stage check
  avoids the dance).
