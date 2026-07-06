# tool-feedback — convoy — tu-v16-campaign-close-tail

- **source:** tu-v16-campaign-close-tail (treasuryutils v1.6 campaign, final four runs to
  campaign close, 2026-07-06 morning — picks up where `2026-07-06-tu-v16-overnight-p4-fleet.md`
  stopped at the wsc-w3 seat-death)
- **tool version:** convoy @ HEAD as of 2026-07-05 (CLI `convoy validate/run`, PYTHONUTF8=1
  standing on every launch)
- **session shape:** 4 waves (wsc-w3 attempt-2 + w3c remainder · wsc-w6 · wsc-w5 · a4-closeout),
  11 impl + 2 fix spawns, closing the 14-series campaign.

## Cost / economy (convoy-metered, per run)

| run | series | PRs | outcome | $ |
|---|---|---|---|---|
| 20260706T090617Z + 094721Z | wsc-w3-plexpr + w3c remainder | 3 impl + 2 fix | PR-1a director-adopt; remainder completed | 7.79 |
| 20260706T101328Z | wsc-w6-perf | 2 | completed | 10.70 |
| 20260706T113533Z | wsc-w5-docs-contract | 3 | completed | 15.29 |
| 20260706T144217Z | a4-closeout | 3 | completed | 3.18 |
| **tail total** | | **11 impl + 2 fix** | | **$36.96** |

**Campaign totals (14 series):** $159.64 convoy-metered; **34/37 PR gate-arcs attempt-0**;
zero gate-red merges. PYTHONUTF8=1 held: zero cp1252 recurrences over the 4 tail runs
(supporting evidence for F-CV-1's fix priority).

## What worked (confirmed wins)

- **W-CV-5 — small-series overhead is genuinely small.** a4-closeout: 3 tiny PRs (doc/plugin
  currency + one `-m` entry-point module) shipped 3/3 attempt-0 for $3.18 / 7.9 min agent
  time. Convoy is economical at the bottom of the size range, not just amortized at fleet
  scale — useful calibration for "is a series worth it for 3 small PRs" (yes).
- **W-CV-6 — adopt-after-director-fix is a workable third recovery shape.** WS-C-W3 PR-1a
  exhausted the repair loop, but the committed work was one regeneration away from green:
  director regenerated the mirror, amended, ran the 5 gates independently (5,733 passed),
  adopted. Together with adopt-if-green (W3-PR3) and the repair loop (W4a), the engine's
  failure shapes all preserved paid-for work — nothing was ever re-implemented.

## Findings

### F-CV-7 (MAJOR) — repair loop is blind to repo-declared regeneration recipes (2nd occurrence of the class)
Two gate failures in the campaign had the same root class — a generated-artifact freshness
gate (`test_generated_references_fresh`, guarding the consumer plugin's reference mirrors)
tripped by a source signature change. W4a's fix spawn inferred the regeneration script and
fixed it ($2.26, attempt-1 PASS). WS-C-W3 PR-1a's fix spawns burned BOTH repair attempts on
the same single test without ever running `generate_references.py` — the director had to do
it manually. Whether the repair lands is luck-of-inference from the test name.
**Fix shape:** optional per-check `repair_hint` in `[[checks]]` (a command or one-line
instruction handed verbatim to the fix spawn when THAT check fails, e.g. `repair_hint =
"run plugins/.../generate_references.py and commit the diff"`). The repo knows its regen
recipes; the schema just needs a slot to declare them.

### F-CV-8 (evidence update — extends TRIAGE-2026-07-06 T4a, no new proposal)
Bare-commit final tally: **7 occurrences** across the campaign. The tail added w3c ×2,
wsc-w6 PR1, wsc-w5 PR1 — so the overnight report's "last PR of series" hypothesis is
**refuted** (later cases were PR1s; position is irrelevant). This is consistent with T4a's
source-level root cause (engine synthesizes `git commit -m pr.id` at headless.py:262 when
the agent didn't commit): it fires wherever an agent ends without committing, regardless of
series position. Reinforces T4a's promotion; director reword cost was ~2 min per occurrence
(reset + re-merge when already integrated).

## Disposition suggestion
F-CV-7 is the tail's one promotion candidate — cheap schema addition, removes the only
failure class the repair loop demonstrably cannot self-serve. Everything else this tail
produced is confirming evidence for findings already in TRIAGE-2026-07-06.
