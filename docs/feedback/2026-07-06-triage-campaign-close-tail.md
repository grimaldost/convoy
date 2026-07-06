# Triage — convoy feedback backlog (delta pass: 1 new report, 2026-07-06)

Delta pass over the baseline `TRIAGE-2026-07-06.md` (6 reports, triaged 2026-07-06
morning). One report was filed after it — `2026-07-06-tu-v16-campaign-close-tail.md` —
and is the sole un-triaged input. The **Current backlog** table below supersedes the
baseline's promotion table as the status of record; cluster IDs continue the baseline's
namespace (T1–T7 minted there, T8 minted here).

## Already shipped — NOT re-proposed

Nothing shipped since the baseline pass: HEAD is unchanged (`d9ea1ea`, 2026-07-05), so
every baseline reconciliation stands and no `proposed` row has landed. (The tail ran
with `PYTHONUTF8=1` standing on every launch — an operator workaround, not a shipped
fix; T1 remains open.)

## Inputs

- `2026-07-06-tu-v16-campaign-close-tail.md`

(Directory holds 7 reports; the other 6 are covered by `TRIAGE-2026-07-06.md`'s Inputs.
The invocation said "new reports" plural; by input-list detection exactly one is
un-triaged — the directory is authoritative.)

## Headline

The v1.6 campaign closed: 14 series, $159.64 convoy-metered, 34/37 PR gate-arcs
attempt-0, zero gate-red merges. The tail contributes **one new promotable cluster** —
T8, a `repair_hint` channel for repo-declared regeneration recipes, which **revises the
baseline's route-out** of the stale-generated-artifact class (there is a convoy-side
build after all) — plus evidence updates that sharpen T4's mechanism (the bare commit is
the *residual sweep* firing on agent-uncommitted work; position-independence now
empirically confirmed) without moving any other status.

## Clusters

### T8 — failing-check *detail* reaches the fix agent, but repo-declared *repair recipes* have no channel (ATTACK; MAJOR; 2 reports)

`2026-07-06-tu-v16-overnight-p4-fleet §W-CV-2` (W4a: the fix spawn *inferred* the
regeneration script from the failing test's name and repaired, attempt-1 PASS, $2.26) +
`2026-07-06-tu-v16-campaign-close-tail §F-CV-7` (WS-C-W3 PR-1a: two fix spawns burned
**both** repair attempts on the same freshness test without ever running
`generate_references.py`; the director regenerated manually and adopted — §W-CV-6).
Same failure class, opposite outcomes — which is the finding: whether the repair loop
can self-serve a generated-artifact freshness red is **luck-of-inference**, because the
gate hands the fix agent the failing check's *output* (`_red_detail` → `_fix_brief`,
verified in the baseline's route-out note) but the repo has nowhere to declare the
*recipe*.

**Verified in source:** `Check` (`core/spec.py:60`) carries
`name/run/blocking/independent/asset` — no repair field; `_fix_brief`
(`interface/drivers/headless.py:89-107`) already iterates the failing blocking checks
with the full `Check` object in hand (`result.check`), so a declared hint threads
through with no new plumbing. The optional `asset` field is the exact schema precedent
(optional str, `''` default, omitted on round-trip — `_parse_check` `spec.py:309`,
`_check_table` `spec.py:389`).

**Supersedes (partially) the baseline's first Routed-out bullet:** the discipline half
stays routed to the consuming project (its gates/`AGENTS.md` describe its own
artifacts); the "nothing to build in convoy" conclusion is withdrawn — the missing
schema channel is convoy's to build.

| # | proposed promotion | home | status |
|---|--------------------|------|--------|
| T8a | Optional per-check `repair_hint` in `[[checks]]` — a command or one-line instruction appended to the fix brief when *that* check fails (e.g. `repair_hint = "run plugins/.../generate_references.py and commit the diff"`). Mirror `asset`'s optional-field pattern in `Check`/`_parse_check`/`_check_table`; append it in `_fix_brief` under the failing check's line; round-trip + `_fix_brief` tests. **(consumer-affecting: new series.toml key — mark in CHANGELOG per the shipped convention.)** | `core/spec.py`, `interface/drivers/headless.py::_fix_brief`, `docs/design/02-formats.md:23`, `tests/` | proposed |

### T4 — evidence update (no new row; T4a stays `proposed`, T4b stays `watch`)

`campaign-close-tail §F-CV-8`: final tally **7 bare-`pr.id` commits** across the
campaign, including PR1s (w3c ×2, wsc-w6 PR1, wsc-w5 PR1) — the overnight report's
"last-PR-of-series" hypothesis is empirically refuted, confirming the baseline's
source-level call. One mechanism refinement for the builder: `commit_all` is a no-op on
a clean tree (`interface/git.py:72-74`), so an agent that commits its own work already
has its message preserved; the bare `pr.id` fires exactly when the impl spawn ends with
uncommitted changes (`headless.py:262`), and fix spawns get the same shape
(`{pr.id}-fix-N`, `headless.py:306`). T4a's build is therefore the *residual sweep*
path — make the sweep produce a real message (or ensure the agent commits) — not "stop
overwriting"; nothing is overwritten. Director cost datum: ~2 min per occurrence
(reset + re-merge when already integrated) — corroborating color for T4b's
observability case, but T4b remains the secondary additive half at `watch`.

### T3 — adjacent evidence only (statuses unchanged)

The tail hand-authored a **third** remainder series (`w3c`, after WS-C-W3 PR-1a's
blocked halt) — another instance of the tax T3a would remove. But the report does not
establish that the skipped PRs were DAG-independent of PR-1a, so the *defect* count
(independent PRs skipped under an "upstream" reason) stays at one. T3a stays `watch`;
T3b stays `proposed`.

### T1 — supporting evidence (statuses unchanged)

`PYTHONUTF8=1` standing on all 4 tail launches: **zero cp1252 recurrences** over 11
impl + 2 fix spawns. Confirms the workaround holds and the class is what T1 says it is;
T1a is still the build — the workaround lives in the operator's shell, not in convoy.

### T2 / T5 / T6 / T7 — no new evidence; unchanged.

## Confirmed wins (non-promotable; recorded for the docs clusters)

- `§W-CV-5` — a 3-small-PR series shipped 3/3 attempt-0 for $3.18 / 7.9 min agent time:
  convoy is economical at the bottom of the size range, not just amortized at fleet
  scale. Calibration datum for the "is a series worth it for 3 small PRs" question
  (yes) — fold into T7a's adoption section if it ships.
- `§W-CV-6` — adopt-after-director-fix completed the recovery-shape set (repair loop /
  adopt-if-green / adopt-after-director-fix); every failure shape preserved paid-for
  work — nothing was re-implemented across the campaign. Candidate content for the same
  docs.

## Routed out

Nothing new. (T8 is the reverse move: a class the baseline routed out is partially
routed back in — see T8.)

## Declined

Nothing new.

## Current backlog (status of record after this pass)

| # | promotion (short) | cluster | status | set by |
|---|-------------------|---------|--------|--------|
| T1a | UTF-8 decode on the 4 unguarded subprocess/`read_text` sites | T1 locale crash (CRITICAL) | proposed | baseline |
| T1b | ≥0x80-byte regression test | T1 | proposed | baseline |
| T1c | self-enable UTF-8 mode at entry points | T1 | proposed | baseline |
| T2a | `stderr_tail` on `SpawnComplete` | T2 seat/infra opacity | proposed | baseline |
| T2b | seat-viability preflight before staging | T2 | proposed | baseline |
| T3a | DAG-aware continuation past a halt | T3 halt over-skips | watch | baseline (tail: adjacent evidence) |
| T3b | truthful skip reason | T3 | proposed | baseline |
| T4a | agent-authored commit messages / real residual-sweep message | T4 bare commits | proposed | baseline (tail: mechanism refined) |
| T4b | commit-provenance telemetry | T4 | watch | baseline |
| T5a | mixed-tier design decision (per-PR override vs documented pattern) | T5 | proposed | baseline |
| T6a | `files touched` in impl narration | T6 legibility | watch | baseline |
| T6b | per-PR integration state in telemetry | T6 | watch | baseline |
| T7a | "Adopting convoy" docs section | T7 adopter docs | watch | baseline (tail: W-CV-5/6 content) |
| T7b | deliberate non-features doc | T7 | watch | baseline |
| T8a | per-check `repair_hint` → fix brief | T8 repair recipes | proposed | **this pass** |

Leverage order for the builder, unchanged at the top: **T1a/T1b (CRITICAL crash) →
T2a/T2b (production halts) → T8a (new; cheap, removes the one failure class the repair
loop demonstrably cannot self-serve) → T4a → T3b → T5a**.

## Promotion-gate ledger

- **T8** — promoted `proposed` on **reinforcement across 2 reports** (overnight §W-CV-2
  + tail §F-CV-7; success-by-inference and failure-by-inference of the same class),
  specific (verified schema seam + fix-brief seam, `asset` precedent), actionable (one
  optional field + one append). Not a BLOCKER; does not need the exemption. The
  baseline's route-out is revised, not contradicted: it was decided on "nothing to
  build in convoy", a premise §F-CV-7's fix shape dissolves.
- **T4** — evidence update only; F-CV-8 self-describes as "no new proposal". T4a keeps
  `proposed` (position-independence now empirical, mechanism sharpened); T4b keeps
  `watch` — its hold was "secondary additive half", which more occurrences do not
  change.
- **T3** — the w3c remainder corroborates the *cost*, not the *defect*
  (DAG-independence of the skipped PRs unverified). Deliberately not counted as the
  second occurrence; T3a stays `watch`.
- **T1** — workaround-held evidence recorded; no status motion.
- **No other cluster received evidence.** Assertion: **no singleton non-BLOCKER was
  promoted this pass** — the only promotion (T8a) is 2-report reinforced.
