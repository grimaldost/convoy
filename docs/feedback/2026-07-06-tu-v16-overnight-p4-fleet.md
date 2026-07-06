# tool-feedback — convoy — tu-v16-p4-overnight

- **source:** tu-v16-p4-overnight (treasuryutils v1.6 campaign, overnight autonomous P4 fleet, 2026-07-05/06)
- **tool version:** convoy @ HEAD as of 2026-07-05 (MCP plugin + CLI `convoy run/validate`)
- **session shape:** 11 series runs in ~12h driving 26 PR implementations (23 sonnet, 3 opus)
  across 9 waves + 1-prime on one Windows/WDAC workspace; director QA + worktree red-check +
  `--no-ff` merge per wave.

## Cost / economy (convoy-metered, per run)

| run | series | PRs | outcome | $ |
|---|---|---|---|---|
| 20260705T191825Z | w1-cursors-tz | 3 | completed | 8.35 |
| 20260705T204919Z/205049Z | w3 attempts (seat logged out) | 0 | infrastructure ×2 | 0.00 |
| 20260705T213803Z | w3-error-boundaries | 3 of 5 | **budget** (exit 4) | 15.24 |
| 20260705T223646Z | w3b-remainder | 2 | completed | 3.15 |
| 20260705T231520Z | w2-projection-contract | 4 | completed | 15.69 |
| 20260706T003822Z | wsc-w4-attribution | 3 | completed | 8.42 |
| 20260706T013904Z | w4a-coordinator (opus) | 1 | completed (1 fix cycle) | 17.18 |
| 20260706T023840Z | w4b-remainder | 3 | completed | 9.89 |
| 20260706T033938Z | wsc-w1-daycount | 2 | completed | 3.78 |
| 20260706T041608Z | w5-dedup-semantics | 2 | completed | 5.52 |
| 20260706T045555Z | w5p-option1prime (opus) | 1 | completed | 10.02 |
| 20260706T052916Z | wsc-w2-builders | 3 | completed | 6.35 |
| 20260706T062215Z | w6 run-1 | 3 of 6 | **crash** (exit 1) | 11.61 |
| 20260706T072516Z | w6b-remainder (PYTHONUTF8=1) | 3 | completed | 7.48 |
| 20260706T082029Z | wsc-w3 attempt-1 | 0 | infrastructure (seat) | 0.00 |
| **total** | | **26 impl + 2 fix spawns** | | **$122.68** |

Gate economics: **24 of 26 PR gates passed attempt-0**; 1 repaired by the fix loop
(W4a, $2.26 fix); 1 halted at budget with complete committed work (W3-PR3, adopted by
director after independent 5-gate run). Zero gate-red merges. The repair loop's first
production firing worked exactly as designed.

## What worked (confirmed wins)

- **W-CV-1 — attempt-0 discipline held at fleet scale.** 24/26 attempt-0 across two
  workstreams and three model tiers. The certified-spec → prompt-with-binding-folds →
  five-blocking-gates pipeline is doing real work; gates never flaked.
- **W-CV-2 — repair loop (first production use).** W4a's pytest failure (stale generated
  consumer-reference mirror after a signature change) was diagnosed and fixed by the fix
  spawn within its $6 sub-budget, gate PASS attempt-1. No director intervention.
- **W-CV-3 — telemetry (spawns.jsonl) is the right observability seam.** Two runs were
  accidentally launched detached (director shell error); the append-only spawns.jsonl was
  sufficient to track liveness, progress, and completion without the CLI narration.
- **W-CV-4 — budget-halt-with-committed-work enables cheap adoption.** W3-PR3 died $0.05
  over its cap AFTER committing complete work; the director ran the 5 gates independently
  (green) and adopted the commit, losing nothing. Halting between commit and gate is a
  graceful failure shape — worth preserving.

## Findings

### F-CV-1 (CRITICAL) — cp1252 UnicodeDecodeError crash inside the engine mid-run
Run 20260706T062215Z died with `UnicodeDecodeError: 'charmap' codec can't decode byte
0x90` raised from Python's cp1252 codec INSIDE the convoy process, while starting PR4 of
6 (after 3 PRs had integrated green). On Windows, some stream/file read in the spawn or
prompt path uses the locale default encoding. A byte ≥0x80 in agent output (emoji, smart
quote, box-drawing char) kills the WHOLE run, not the offending spawn.
**Mitigation that worked:** relaunching the remainder with `PYTHONUTF8=1` — the crash did
not recur over 3 further PRs.
**Fix shape (root cause, not advice):** every `open()`/`Popen` text stream in the engine
gets `encoding='utf-8', errors='replace'` (or the engine self-enables UTF-8 mode on
win32). Same bug class as the craft-collection `anchor_inject.py` cp1252 finding —
this is the second tool in the stack bitten by Windows locale defaults.

### F-CV-2 (MAJOR) — budget/infrastructure halts skip DAG-independent PRs with a misleading reason
Run 20260705T213803Z (budget halt on PR3): PR4/PR5 had `depends_on = []` yet were
skipped with `reason: "upstream w3-pr3-report-typing halted (budget)"`. "Upstream" is
sequence-position, not DAG dependency. Cost: a director must hand-author a remainder
series for PRs the engine could have run. Fix shape: on a PR halt, continue executing
PRs whose `depends_on` closure excludes the halted PR (or at minimum, name the real
reason: "run halted before this PR started").

### F-CV-3 (MAJOR) — last-PR-of-series ships a bare commit message (2 occurrences)
w3b PR5 committed with message `w3-pr5-msal-classifier`; W4b PR4 with
`w4-pr4-shape-b-doors` — both the FINAL PR of their series, both violating the
conventional-commit instruction present in their prompt discipline blocks. Middle PRs
never did this. Hypothesis: the last PR's spawn context differs (no successor pressure?)
or the integrate step synthesizes a commit when the agent didn't. Worth instrumenting:
record whether the commit was agent-authored or engine-synthesized in spawn telemetry.
Director had to rebuild the integration merge after amending (reset + re-merge) — an
engine-side `commit message must match ^type(scope):` check (non-blocking warn or
blocking) would have caught both.

### F-CV-4 (MINOR) — `run_complete.integrated:false` is ambiguous on partial runs
The W3 budget-halt run ended `outcome:"budget", integrated:false` even though PR1+PR2
WERE merged into the series integration branch. "integrated" apparently means "the whole
series integrated", but a reader tracking state needs "which PRs are on the integration
branch" — that is only recoverable by reading git. Fix shape: per-PR `integrated:true`
events (or a final per-PR status map in run_complete).

### F-CV-5 (MAJOR, confirmed 2nd occurrence) — seat logout is invisible until spawns die
The `claude` CLI seat logged out twice during the campaign (~9h apart), each time
producing 0.1-0.2s/$0/1-turn spawn deaths classified `infrastructure`. The earlier
report's two promotions stand, now with doubled evidence: (a) surface `stderr_tail` on
spawn_complete so "Not logged in" is readable from telemetry; (b) a pre-stage seat probe
(cheap `claude -p` equivalent or credential check) in preflight, so the run refuses to
start rather than dying at PR1. Seat lifetime ~9h also suggests documenting "long fleets
must expect mid-run logout" until (b) exists.

### F-CV-6 (MINOR) — per-PR model tier requires series splitting
The ratified plan wanted PR1-opus + PR2-4-sonnet in one W4 series; the schema's
series-wide `model` forced a 2-series split (w4a/w4b) with a hand-built base/integration
chain. It worked, but the split cost an extra series file, an extra run, and the
remainder-series dependency surgery. Prior W1 feedback noted this; tonight it graduated
from annoyance to structural workaround. Fix shape unchanged: optional per-PR `model`
override, falling back to series model.

## Disposition suggestion
F-CV-1 is the promotion candidate (crash, data-independent, trivially reproducible by
echoing a 0x90 byte from a spawn on win32 without UTF-8 mode). F-CV-5's preflight probe
is second (two production halts). F-CV-2/F-CV-3 are engine-behavior fixes with clear
mechanisms; F-CV-4/F-CV-6 are schema/telemetry shape changes.
