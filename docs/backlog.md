# Backlog — the durable improvement ledger

This is the canonical, tracked record of convoy's improvement backlog. It is fed
by triage passes over dogfooding feedback and by periodic feature reviews; the raw
feedback reports and the triage documents themselves are session artifacts and stay
local-only in [docs/feedback/](feedback/) (see the `.gitignore` there). A row here is
written so a maintainer can build it without the source reports.

**Last reconciled: 2026-10-06.** The ledger had stopped at the 0.12.0 hook round
(2026-09-02). Three releases (0.13.0, 0.14.0, 0.15.0) and one triage pass landed after it
without reaching this file, so its header, CONV-B14, CONV-B29 and the row-ID map had gone
false. Four inputs were merged in this pass:

1. The 2026-10-06 triage delta, over one feedback report (a three-PR run on 2026-09-26)
   and a re-reading, against the source, of every row the earlier triage documents left
   open: 69 rows, of which 35 had shipped, 2 were declined, 2 were superseded, 13 were
   carried `proposed` and 17 `watch`. Its statuses supersede every earlier triage
   document's.
2. The 2026-09-13 triage delta, over 13 reports from 2026-09-01..09-13, which minted the
   clusters T56–T65 and was never reconciled into this file.
3. The `CHANGELOG.md` sections for 0.13.0, 0.14.0 and 0.15.0.
4. The rows built on the 2026-10-06 maintenance branch. They are recorded as shipped 0.16.0,
   because a row is done only when a tagged release serves it.

The pass mints CONV-B65 through CONV-B71 and records where every row went under
[Shipped](#shipped), in the watch table and in the [row-ID map](#row-id-map).

**The 2026-08-11 reconciliation** merged three inputs:

1. A full triage over the 21 feedback reports spanning 2026-07-09..08-02 — the
   campaign window, covering roughly 90 governed PRs.
2. An independent feature review of every shipped surface at v0.7.0, audited against
   the current agent harness and against the run ledgers on disk (13 runs, 76 spawns,
   $743.27 of metered spend).
3. Two research briefs on the surrounding landscape: what the harness now does
   natively, and what the orchestration category still leaves unserved.

The three agree on the headline. **The engine's capability gaps are closed.** No report
in the window records a bad PR reaching integration, the last five contain no engine
defect at all, and the audit found the deterministic gate rejecting a "done" claim five
times in 73 gate events with every red repaired or halted. What remains is observability,
advice, and a set of surfaces the harness has since absorbed. Where the three inputs
disagree, the item says so rather than silently picking a side.

**A fourth input arrived afterwards: a cross-project consistency pass (2026-08-11)**, run
across the sibling projects' backlogs rather than over convoy's own evidence. It adds the
notes marked `[cross-review]` below and two receiving rows (CONV-B36, CONV-B37), and it
changes nothing else — no row was reordered and no existing argument was rewritten. Where
it disagrees with what a row already argues, the note sits under that row and both
readings stand until someone settles them.

**A status pass ran on 2026-08-12** — not a reconciliation: no input was merged, no row was
added, reordered or rewritten on new evidence. It retargets the `Status` lines of the rows
the 0.8.0 tag now serves, records CONV-B27's settlement as ADR-0009 and CONV-B14's partial
one, and **corrects CONV-B37**, whose imported measurement cited a figure belonging to an
arm its own run rejected. A row whose numbers came from outside this repository is the one
kind of row the "written to stand alone" bar does not protect, so the correction is recorded
in place rather than substituted.

**A delta pass ran on 2026-09-01**, over the two reports no prior triage lists. It mints
CONV-B52 (the corpus's only BLOCKER — the gate reachable only by buying the whole engine),
CONV-B53 (partial composition unmeasured) and CONV-B54 (CHANGELOG discipline asserting
values, never shape), ships B52 and B54 in 0.10.0, and retargets the rows the 2026-08-29
guardrail build left at `[Unreleased]`. Two of its clusters stayed at `watch` and are in
the watch table (T54a, T54b). The pass also recorded a scope defect worth carrying: the
feedback index reported six false un-triaged reports because the prior triage document was
written to this repository's `docs/feedback/` (per ADR-0006) rather than the registered
feedback directory the index scans, and its `## Inputs` list was fenced, which credits zero
stems. Both repaired; neither is a convoy defect, and both are routed to the tool that owns
the triage pipeline.

**A delta pass ran on 2026-08-28**, over the six reports the 2026-08-11 triage does not
list. Small corpus, so it is a narrow pass justified by one routed item rather than by
volume: a requirements-conformance finding routed in from a cross-project triage, reinforced
by a corrective wave in this corpus. It mints CONV-B38..CONV-B45, folds three documentation
findings into CONV-B08, and re-statuses five rows the field has since confirmed or
falsified. Two inputs beyond the reports informed it: the **first production evidence from
outside the campaign estate** (five repositories, seven series, 15 PR spawns in one night,
$157 metered), and a periodic post-hoc telemetry pass over agent transcripts for
2026-06-26..08-25, whose figures are cited below as dispatch evidence and nowhere as an
effect size — it has no control arm and counts only what an agent invoked, so its engine
counts are a floor.

**A build round ran on 2026-09-02** (program 2, Part 1 — the gate as a hook), from the
design spec of program 2 (kept with the measurement instrument, outside this repository)
rather than from a triage pass. It mints CONV-B55 through CONV-B59 and ships all five in 0.12.0; two
blind reviews of the candidate (31 findings) closed every blocker, high and medium before
the cut and left four residuals, minted here as CONV-B60 through CONV-B63, plus one doctrine
row the round's own miss earned (CONV-B64). CONV-B53's measurement — iteration 1 of the
multiagent-composition experiment — closed and was blind-reviewed on 2026-09-03; its row
carries the result.

**A build round ran on 2026-10-08**, from the 2026-10-07 review rather than from a triage
pass. It mints CONV-B72 through CONV-B75 and re-statuses CONV-B14; T67a leaves the watch
table as CONV-B73.

## Reading this backlog

- **ID.** `CONV-Bnn` is the stable build ID used from this pass forward. `T<cluster><letter>`
  IDs are minted by triage passes and remain valid; the [row-ID map](#row-id-map) resolves
  them to `CONV-B` items so older reports and triage documents stay readable.
- **Effort.** `S` — one file, no contract change. `M` — several files, usually a
  CHANGELOG entry and tests. `L` — needs an ADR, a new document, or a design first.
- **Source.** `[triage]` (dogfooding evidence), `[review]` (the 2026-08-11 feature review),
  `[research]` (the landscape and ecosystem briefs), `[cross-review]` (the 2026-08-11
  cross-project consistency pass), `[probe]` (a dated observation note under
  [docs/notes/](notes/README.md)), `operator observation` for a direct report with no
  artifact behind it.
- **Consumer-affecting** rows must carry the CHANGELOG marker convention from
  [docs/design/02-formats.md](design/02-formats.md) when built.
- Evidence is cited by date and neutral descriptor rather than by report filename.
- **An imported measurement carries its provenance or it does not license anything.** A
  number that came from outside this repository is stated with the study that produced it,
  which arm of that study, `n`, and the interval's confidence level — and is re-read against
  that source before a row leans on it. This is the one bar the "written to stand alone"
  rule cannot cover, and CONV-B37 is why it is written down: a one-line summary imported a
  figure belonging to an arm its own run had rejected, and travelled unchallenged through
  every later reading because nothing downstream could check it. A summary line is the part
  that travels, so it is the part that has to be checkable.
- A `[cross-review]` note may cite a row ID that is not a `CONV-B` one. Those are foreign
  row IDs, carried only as join keys so the two ledgers can be reconciled by whoever holds
  both. They are citations, not dependencies: convoy stays self-contained by carrying its
  own copy of anything it needs, which is the whole argument of CONV-B14.

## Leverage order

**Now** is ordered by measured cost, then by cheapness of the fix. The first two rows are
the only two defects the audit found that cost real money in production: a budget cap
evaluated one turn too late (2 of 10 terminal runs, ~$0.04 of overshoot forfeiting five
downstream PRs) and a driver death that leaves no terminal record (2 runs, 9 spawns,
about $47, reported `running` indefinitely). The next three are the highest-recurrence
findings in the feedback corpus. The last two are silent-measurement defects: a governance
value the CLI ignores without saying so, and a spawn classification that scores a refused
invocation as a clean result.

**Next** is correctness and hygiene that no run has yet lost money to, plus the
consolidation row that several other rows land in. The two rows received from the
cross-project pass (CONV-B36, CONV-B37) sit at the end of it: neither has cost a run
anything, both are cheap, and each names the dependency that holds it.

**Later** holds work that is either gated on a measurement, held at `watch` awaiting a
second report, or a positioning decision rather than a build.

**What the 2026-08-28 delta added, and where.** Every CONV-B01..B07 row is shipped, so the
open head of **Now** is the three rows that pass minted there: CONV-B38 first — the largest
measured cost in this corpus is a design deviation that executed to completion with every
gate green, and no convoy mechanism was positioned to see it — then CONV-B40 (an unreachable
check that burned two fix spawns, and that an operator now probes by hand before authoring)
and CONV-B41 (an expired on-disk credential that killed two runs outright and moved a whole
series to manual execution). **Next** takes the recovery and observability rows the same
nights produced. Four rows were built in the pass itself and are recorded under Shipped. The
pass appended nothing to `SKILL.md` as advice: the documentation findings that would have
are folded into CONV-B08, which exists to shorten that file, and the two items that shipped
there instead are descriptions of engine behaviour the manual owes a reader.

**What the 2026-10-06 reconciliation added, and where.** Two open rows: CONV-B68 at the end
of **Next** (the skill's description names concurrent writers as a dispatch case; cheap, and
the hazard it points away from was priced) and CONV-B65 in **Later** (per-PR changelog
fragments, which need an ADR). Everything else it minted was built on the maintenance branch
and is recorded under Shipped in 0.16.0. The watch rows of the 2026-09-13 and 2026-10-06
passes join the watch table.

**Retire / fold** is the review's sentence on surfaces that no longer earn their place;
each names its replacement, and the two that are conditional name the measurement that
decides them.

---

## Now

### CONV-B01 — A spawn's budget cap is only checked after the turn that busts it, so a $0.0006 overshoot forfeits the rest of the series.

**Cause / evidence.** Two of ten terminal runs on disk halted `budget`: $20.000642 against
a $20.00 implementation cap and $8.035593 against an $8.00 cap — overshoots of 0.3% and
0.4% that skipped 3 and 2 downstream PRs and discarded the truncated spawn's uncommitted
work, since the driver returns before committing it. The workaround the operator actually
reached for was raising the implementation cap 20→32 for every PR in a wave, which weakens
the ceiling for every cheap PR — so the current design pushes toward looser caps, the
opposite of its intent. [review, from the ledgers; triage: 2026-08-01 wave-B core and
wave-B2 reports, 2026-07-08 baseline]

**Change.** Emit a `budget_nearing` signal at about 90% of a spawn's cap — a telemetry
line, or a field on the next `spawn_complete` — so a monitor can raise the cap or stage
recovery before the busting turn rather than learning from the exit code. Do not soften
the hard cap; the cap binding is the feature. `core/telemetry.py`,
`interface/drivers/headless.py`. **(consumer-affecting)**

**Disagreement.** Triage rated this `med` and placed it seventh in its build order. The
review, working from the ledgers, calls it the highest-leverage unbuilt row in the corpus
and one of two defects to fix before any new feature. Ordered here on the review's
spend-weighting: 20% of terminal runs lost for four cents of overshoot.

**Status.** **Shipped** in 0.8.0. `spawn_complete` carries `budget_cap_usd` and
`budget_nearing` (90% of the resolved per-role ceiling), and the reporter narrates a
`near cap` line at the same moment. The hard cap is unchanged. The per-PR `budget`
override this row's cluster also wants stays held at CONV-B22.

**Effort** S–M · **Source** [triage] + [review] · **Row** T32a

### CONV-B02 — A dead driver is indistinguishable from a running one, so a run reports `running` forever.

**Cause / evidence.** The ledger records only completions, so `convoy_status` derives
`running` from the absence of `run_complete` — exactly what a dead driver leaves behind.
Two runs on disk have no terminal record at all (9 spawns, about $47), and three driver
deaths in the campaign window were each diagnosed by an OS process query, so every correct
long-run integration reimplements that check. Verified absent in source: no heartbeat, no
`spawn_start`, no `run_abandoned`, no `run_pid`; `state` is `running|finished|unknown`. The
lock file writes the owner PID at `workspace_lock.py:60` and nothing ever reads it back.
Detached runs make this more likely, not less. [triage: 2026-07-30 multi-wave runs,
2026-07-31 remediation wave A; review]

**Change.** Three parts, in this order. (a) `convoy_status` reads the lock's owner PID and
adds `dead` to the `state` vocabulary — no new persistence, no new event (T29a; supersedes
T10b). (b) Pre-flight appends a terminal `run_abandoned` line for the orphaned `run_id`
when it clears a stale lock — the only part that repairs history, since a PID is reusable
once the process is gone, so (a) alone cannot answer for a run that died yesterday (T29b).
(c) Emit a `spawn_start` line so "which PR is in flight" is answerable from the ledger
during a 30–90 minute spawn, and a driver that is alive but stuck becomes visible (T29c).
`interface/workspace_lock.py`, `interface/run_summary.py`, `core/telemetry.py`,
`interface/run_service.py`, `interface/drivers/headless.py`. **(consumer-affecting: a new
`state` value, a new event and `outcome` value, a new event)**

**Status.** **Shipped** in 0.8.0, all three parts. (a) `convoy status` /
`convoy_status` take an optional workspace, read the lock's owner pid, and report `dead` —
claimed only on the positive evidence of a lock whose owner is gone, so no lock and no
workspace both still read `running`. (b) `convoy clean` appends a terminal `run_abandoned`
line for the orphaned run when it clears a stale lock; reconstruction reads it as
`outcome: abandoned` with the infrastructure exit code. (c) `spawn_start` is written before
every spawn, and the envelope carries a per-PR `in_flight`.

**Confirmed in production (2026-08-28 delta).** Two machine-sleep events killed drivers in
one night and `dead` was claimed correctly both times, on positive evidence rather than a
timeout guess; the operator's report calls it exactly what was asked for. Two residuals
opened by the ship itself are now CONV-B42: the `dead` message names the destructive remedy
first, and the state's other half — a per-PR `in_flight` that never advances during a
94-minute spawn — is CONV-B43(c).

**Effort** M · **Source** [triage] + [review] · **Rows** T29a, T29b, T29c

### CONV-B03 — The gate's failure `detail` is chosen by stream rather than by content, and cut mid-token.

**Cause / evidence.** `_red_detail` is `stderr.strip() or stdout.strip()` and then the last
2000 characters, so any content on stderr means stdout is never read, and a character-count
tail begins inside a word. The case that proves the first half: a subset-scoped pytest run
whose coverage-floor failure (`Required test coverage of 80% not reached`) went to stdout
while stderr held only a launcher warning — the answer was not truncated, it was discarded.
The second half is observed twice: a detail beginning inside an unrelated xfail reason, and
one beginning inside a structured log line the repository writes at INFO. A fragment
starting mid-word reads as though it were the failure. `detail` is also what the bounded
fix loop re-briefs the repair spawn with, so a polluted detail aims a paid spawn at a
non-problem. Five sessions across four repositories — the longest lineage in the corpus —
and it recurred twice *after* 0.5.0 shipped a fix at this same layer, because that fix
removed the then-known pollutant rather than changing how the detail is selected.
[triage: 2026-07-17 (two reports), 2026-07-31 wave-A close, 2026-08-01 wave-B2,
2026-07-08 baseline]

**Change.** Carry bounded, labelled tails of **both** streams instead of stderr-precedence
(T13b), and cut at a line boundary, never mid-token (T28a). One restructuring of
`interface/gate_runner.py::_red_detail`.

**Status.** **Shipped** in 0.8.0. `_red_detail` now carries a bounded, labelled
tail of each stream that said anything, under one budget split so neither crowds the other
out, cut at a line boundary and marked `...`. The selection rule changed, not the pollutant
list — which is what the two earlier fixes at this layer did not do.

**Effort** S · **Source** [triage] · **Rows** T13b, T28a

### CONV-B04 — The shipped manual contradicts the shipped engine, and nothing compares a documented claim to the code.

**Cause / evidence.** `skills/convoy/SKILL.md:369` still states "there is no resume — a
halted run does not check-point-and-continue" and `:382` that a re-run "re-spends it in
full", while `--resume` shipped in 0.4.0 and is documented in the same file at `:64`;
§Cost & latency still says `convoy_run` is synchronous and cannot be polled, false since
`convoy_status` (0.5.0) and `detach` (0.6.0); `convoy clean` (0.4.0) appears zero times in
the file. Beyond the skill: `interface/mcp/server.py`'s module docstring and
`docs/design/03-serving.md` both say "two tools" while three are registered, and
`.claude-plugin/marketplace.json` advertises only `convoy_run` + `convoy_init`, so
`convoy_status` has shipped unadvertised for three releases; `docs/design/00-overview.md`
§7 claims convoy's CI gate includes an independent check over convoy itself, which
`ci.yml` (lint, format, type-check, pytest) does not. Measured cost: two operators
hand-deleted a halted PR's zero-unique-commit branch, work `headless.py:348-360` already
does. This is the third occurrence of the class and the first two fixes were both prose —
a PR-template line and an AGENTS.md rule — which is the escalation trigger. AGENTS.md
already carries the right rule ("if docs and code diverge, code wins"); what is missing is
a mechanism. [triage: 2026-07-09 governance-cycle, 2026-07-26 front-page, 2026-07-30
multi-wave, 2026-08-01 wave-B core; review]

**Change.** (a) Delete the false claims, name `clean`, and state what resume does to a
leftover PR branch; correct the tool count in the server docstring, `03-serving.md` and
`marketplace.json`, and the CI claim in `00-overview.md` §7 (T30a). (b) Build a doc-claims
test in the shape of `test_versions_are_locked`, pinning the small set of claims that have
actually drifted — the MCP tool count, the CLI verb list, and the presence of
`resume`/`clean` — against the code providing them (T30b). Deliberately narrow, not a
prose linter.

**Status.** **Shipped** in 0.8.0, both halves. (a) The false resume/synchronous
claims are gone, `clean` is named as the recovery verb and `--resume`'s branch handling is
stated, the tool count is corrected in the server docstring, `03-serving.md` and
`marketplace.json`, and `00-overview.md` §7 now records the CI claim as unbuilt rather than
repeating it. (b) `tests/test_doc_claims.py` pins tool names, a stated tool count, CLI verbs
and the `convoy_run` arguments against the registries that provide them, with a non-vacuity
guard; the guardrail names it as the enforcer. CONV-B25's restamp is untouched — only the
false CI claim rode along, as that row says.

**Effort** S for (a), M for (b) · **Source** [triage] + [review] · **Rows** T30a, T30b

### CONV-B05 — Phase scoping made subset gates possible and convoy says nothing about how to scope one; a wave can gate 16/16 green with repository-wide guards red.

**Cause / evidence.** Two opposite failure modes recur. The gate fails hollow: a
path-scoped test subset inherits a repository-global `--cov-fail-under`, so it exits
nonzero with every test green — a red that no code change to the PR can clear. That cost
two fix spawns ($2.44 and $1.35) aimed at a non-bug followed by a `blocked` halt, and a
separate run killed at gate 1 by an operator who saw the loop was about to "repair" it by
mutating the repository's coverage settings. And the gate passes hollow: a subtree-scoped
suite cannot see the repository-wide registries a PR mutates — a 16-PR wave gated 16/16
green while two repository-wide guards were red, found only by running the full suite by
hand after the run reported `completed`, so the series' own quality claim was stronger than
the tree warranted. [triage: 2026-07-31 wave-A close (two findings), 2026-07-17 (two),
2026-07-30 multi-wave, 2026-08-01 wave-C close; review]

**Change.** A `gate-scope` advisory on the existing non-blocking channel: convoy already
holds the gate commands and the workspace, so "the gate does not run N test files present
in the workspace" is answerable for free at `dry_run` (T31b). Same shape as the two
`kind='gate'` advisories already in `core/preflight.py`, and unlike the held path-detector
rows it needs no heuristic — it compares a command's declared paths against the tree, which
is the no-false-positive-budget property. It would have fired on the wave above before a
dollar was spent. The two authoring-side halves — the gate-scope rule (T31a) and the
gate-hygiene note (T31c) — land in CONV-B08's reference; T31a is already validated in the
field, with three consecutive waves closing with no post-run surprises after it was
adopted.

**Status.** **Shipped** in 0.8.0 — the T31b half. A third `kind='gate'` advisory
names the test files no blocking check's declared paths cover, silent whenever the answer
would be a guess (a check naming no path runs the whole tree; a check naming only out-of-tree
paths is an oracle and is passed over). T31a and T31c still ride CONV-B08.

**Confirmed in production, and repaired (2026-08-28 delta).** The advisory named a check as
too narrow before a series ran; the check was widened on that advice and later caught a real
breakage — the clearest instance in the corpus of a pre-flight advisory paying for itself.
It was also, in two other workspaces, unreadable: 526 and 474 uncovered test files, all of
them inside a virtualenv or a build directory the workspace's own rules ignore. Repaired in
`[Unreleased]` — the scan now consults `git check-ignore` and names directories rather than
three arbitrary files. An advisory nobody reads is worth less than one that does not exist,
because it also discredits the ones that are right. T31a and T31c still ride CONV-B08.

**Effort** M · **Source** [triage] + [review] · **Rows** T31b (T31a, T31c ride in CONV-B08)

### CONV-B06 — `effort` is an unvalidated free-form string the CLI silently ignores when it is wrong, and convoy records it nowhere.

**Cause / evidence.** Verified against the installed CLI: `--effort lo` prints
`Warning: Unknown --effort value 'lo' — ignoring it and using the default effort` on
stderr and runs anyway, exit 0. convoy passes `effort` through unvalidated — unlike
`permission_mode`, which is allow-listed at load — and records only `effective_model` on
the spawn line, so a typo runs at the CLI default while both the series file and the ledger
claim the pinned value. For a tool whose product is reproducible, comparable measurement
that is the worst failure shape available: silent, undetectable downstream, and it corrupts
exactly the comparison the ledger exists to support. Separately, `PERMISSION_MODES` has
drifted: the installed CLI accepts `acceptEdits, auto, bypassPermissions, manual, dontAsk,
plan` plus legacy `default`, so convoy's four-value list rejects three modes the CLI
supports. [review; operator observation of the current CLI flags]

**Change.** Validate `effort` against the known levels at spec load, the same treatment
`permission_mode` already gets; refresh `PERMISSION_MODES` against the current CLI set; and
record the requested `effort` on `spawn_complete` beside `effective_model`, so a divergence
is at least visible after the fact. `core/spec.py::_parse_governance`,
`core/governance.py`, `core/telemetry.py`. **(consumer-affecting: a new telemetry field)**

**Disagreement.** Triage held this at `watch` as a cheap singleton (T35b). The review
escalates it on a measurement-integrity argument triage did not make, and adds the
recording half. Ordered here on the review's reasoning; if the recording half proves
awkward, the validation half alone still closes the silent case.

**Status.** **Shipped** in 0.8.0, both halves. `effort` is allow-listed at load
(`low`/`medium`/`high`/`xhigh`/`max`) on `[governance]` and per PR, `PERMISSION_MODES` is
refreshed to the CLI's six plus legacy `default`, and the resolved `effort` is recorded on
`spawn_complete`. The accepted sets were read from the installed CLI's own flag help, not
inferred.

**Effort** S · **Source** [review] · **Row** T35b, escalated

### CONV-B07 — A spawn the agent CLI refuses at argument parse is scored as a clean result with zero economy, and the seat probe passes it.

**Cause / evidence.** `_classify` regex-matches the vendor CLI's prose on stderr and
returns `'ok'` for any non-success spawn carrying no auth, usage or retry signature. So a
spawn refused at argument parse — a flag renamed upstream, a value dropped from a choice
list — is scored as a clean task result with $0 economy, and the seat probe, which blocks
only on `'infrastructure'`, passes. The operator then sees a `blocked` run with $0 spend
and no diagnosis. The adjacent half is confirmed live: an unknown `--effort` value warns on
stderr and runs anyway, and convoy discards that warning because `output_tail` is recorded
only for non-ok spawns. Matching a vendor CLI's prose is a permanent tax with a silent
failure mode. [review, by inspection plus a live CLI check]

**Change.** Prefer the CLI's structured signals over its prose wherever one exists
(`result.subtype`, `is_error`, exit code), and treat "nonzero exit with no `result` event
at all" as `infrastructure` rather than `ok` — that single change closes the argv-rejection
hole and makes the seat probe's claim mean what it says. Add a test that fails on an
unrecognised `result.subtype`. `interface/headless_spawn.py`. Do this regardless of
CONV-B35, which considers replacing the parser entirely.

**Status.** **Shipped** in 0.8.0. A nonzero exit with no `result` event is now
`infrastructure` and carries a diagnosis; the `result` subtypes convoy has a decision for
are named in one table, and a non-success spawn carrying anything else is not scored. A
seat-probe test composes the real adapter with a stub CLI that refuses at argument parse.
The adjacent `--effort` half of this row's evidence is closed at the other end by CONV-B06,
which rejects an unknown level at load. Independent of CONV-B35 as the row asks.

**Effort** M · **Source** [review]

---

### CONV-B38 — A series pins the spec it came from and can say nothing about whether that spec was ever certified, so a deviated design executes to completion with every gate green.

**Cause / evidence.** The costliest failure in this corpus is not a defect convoy has: a
programme's spec said its sources would be reached through a configuration layer, that
mechanism was silently replaced by bespoke readers, and the substitution then propagated
across later waves *because* they were disciplined enough to mirror the proven sibling. Four
blind pre-mortems audited that spec — about 70 real findings between them — and none caught
it, because they audited the spec against the code and the data contracts, and the owner's
order existed in no artifact a blind reviewer could open. The corrective wave that repaired
it is the single-PR series recorded in this corpus: $1.83, two fix spawns spent against an
unreachable check, finished by hand. CONV-B36 shipped the anchor this row needs —
`[series].spec_path` + `spec_sha256`, resolved and hashed at pre-flight before the first
spawn is purchased — and it is already load-bearing in production, having answered "which
revision produced this run" for a spec that moved between authoring and launch. What it
cannot say is whether the thing it pinned was ever *ready*. [triage: 2026-08-24 corrective
wave; routed in from a cross-project pass with its analysis already reinforced]

**Change.** A pre-series readiness gate, and the load-bearing half is **who owns the
definition**. convoy must not learn a readiness grammar — not a certification block, not a
requirements ledger, not an order-id format. Each of those belongs to whichever planning
discipline produced the spec, is under active development there, and would diverge from a
copy held here within a release. Instead `[series]` accepts an optional readiness command
that convoy runs **once, before the first spawn, against the pinned spec**, treating a
nonzero exit as a blocking pre-flight `Problem` of a new `kind='readiness'`. convoy owns
when it runs and that it blocks; the operator's own gate owns what "ready" means. That is
reuse rather than duplication, it keeps this repository self-contained (the command is data
in the operator's series file, never a name in this tree), and it generalizes past any one
method: a schema validator, a sign-off script and a spec linter are the same shape.

**Opt-in and silent when undeclared**, exactly as the spec pin is — every series authored
before the key existed keeps running unchanged, which is what keeps this from blocking flows
that work today. Needs an ADR: executing an operator-supplied command at pre-flight is a new
class of thing for the engine (working directory, environment, timeout, and its relationship
to `[[checks]]`, which gate produced work in a worktree and cannot serve this).
**(consumer-affecting: a new series.toml key, a new `problems[].kind`)**

**Effort** L · **Source** [triage] + routed · **Rows** T40a

### CONV-B39 — The gate answers "are the checks green", never "did this task do what it was asked", so a task can satisfy every check and still not satisfy its requirement.

**Cause / evidence.** The second half of the same routed finding. convoy's gate is
deterministic by charter (ADR-0002) and reads exit codes; the acceptance criteria a task was
written against, and the orders the series is meant to serve, are read by nobody at gate
time. In the deviation above, every check would have passed on the deviated design — and the
report that routed this says so plainly: a Definition-of-Done gate inherits garbage-in and
sees only what the requirements artifact hands it. That is why this row is second and not
first: **the artifact has to exist and be enforced upstream before a conformance answer
means anything.** [triage: 2026-08-24 corrective wave; routed]

**Change.** Two layers on the existing per-PR gate, both additive to the result envelope and
neither displacing the deterministic verdict, which stays the sole merge arbiter. (a) The
task's own acceptance criteria evaluated against what the task produced. (b) A conformance
answer per declared requirement id — advanced, violated, or does not touch — folded into a
task × requirement matrix on the series result. Held behind CONV-B38: without the upstream
gate the matrix reports over an artifact nothing guarantees exists, which is the shape that
produces confident green on a wrong design. **(consumer-affecting: new result-envelope
fields)**

**Effort** L · **Source** [triage] + routed · **Gate** CONV-B38 · **Rows** T40b

### CONV-B40 — The engine runs a check without ever establishing what that check observes, so it cannot tell a red it caused from a red it inherited, or a green that means something from a green that means nothing.

**Cause / evidence.** One cause, three measured faces, all in this corpus. (a) **Red the
work cannot reach.** A pytest check inherited its repository's `--cov … fail_under=80`
addopts; a subset run measures the whole tree, exits 1 with every test passing, and the
series halted `blocked` after two fix spawns ($1.22) changed nothing meaningful twice. The
failing text even said "Required test coverage of 80% not reached". On the *base* branch
that check already exits 1 — the gate measured something no PR could influence, and one
execution against the unmodified base would have proved it before a cent was spent. The next
series in the corpus opens by recording that the operator probed all three checks green on
base **by hand** before authoring, which is the engine's job being done by a person. (b)
**Green that observes nothing.** A gate-sufficiency audit found a docs-only PR gated by a
code-only suite — structurally incapable of going red for that diff — integrating with the
same green as a tested PR. The existing ungated-PR advisory does not fire, because *some*
blocking check exists. (c) **A check that repairs what it validates.** Audited as a BLOCKER:
drift gates regenerated their corpus in place after validating it, so a red on attempt 0
self-healed by attempt 1 — `max_fix_attempts` re-runs the gate, and the re-run validates
what the first run rewrote, whether or not the fix spawn committed anything. Gate authoring
is the root cause and belongs upstream; the engine is the amplifier, and the only party
positioned to notice. [triage: 2026-08-24 corrective wave; 2026-08-24 wave-c, the operator
applying the fix by hand; 2026-08-25 gate audit, two findings]

**Change.** Three mechanisms, and (a) is the one with money behind it. (a) Execute each
blocking check once against the unmodified base at pre-flight. Red on base is a `usage`
problem — "this gate cannot pass in this repository" — not a spawn trigger; green on base
**and** untouched by the PR is the symmetric hazard and reads as an advisory. The cost is
real and belongs in the ADR: pre-flight stops being free, which is the property `dry_run` is
valued for, so this likely wants its own opt-in rather than riding `dry_run`. (b) Refine the
ungated-PR advisory: warn when a PR's changed paths plausibly intersect no blocking check's
observed surface, docs-only-diff against code-only-checks being the canonical case. (c)
Record whether the worktree is dirty after a check ran — an advisory at minimum, a
`gate_complete` field ideally. A dirty tree after a read-only claim is exactly the
self-healing-oracle signature, and the engine already refuses in-tree `outputs` on the same
instinct. **(consumer-affecting: a new `problems[].kind`, and a `gate_complete` field for
(c))**

**Effort** M for (a), with an ADR · S for (b) and (c) · **Source** [triage] · **Rows** T41a, T41b, T41c

### CONV-B41 — An expired on-disk credential kills the seat probe while the operator's live session goes on working, so convoy is unavailable at exactly the moment an operator reaches for it.

**Cause / evidence.** Two reports, three dead launches, and one hypothesis eliminated
between them. The seat probe fails with "OAuth session expired and could not be refreshed"
against a credential the interactive session beside it is refreshing continuously — the live
session rotates the refresh token, and the point-in-time copy convoy took cannot. The first
report saw it on two `resume` launches and reasonably suspected `config_isolation`'s
credential copy. The second killed that hypothesis: a bare probe under the **operator's own
config** fails identically, so `config_isolation = false` is not a mitigation, and the kill
hit a *first* run of a new series rather than a resumption — the exposed surface is any
long-lived interactive session, not a rare recovery path. Spend cost is approximately zero,
which is the engine failing closed correctly. The cost is availability: both series
completed by hand under the same gates, so convoy's ledger records no integration for
content that integrated — the second occasion in this corpus where a run's ledger and the
repository disagree about what happened.

Recorded as an availability defect only. A session that could not start convoy is not
evidence about whether convoy would have been chosen, and this pass keeps the two apart
deliberately. [triage: 2026-08-24 corrective wave #2, 2026-08-24 wave-c #1]

**Change.** Validate — or refresh — the operator credential *before* copying it, and when it
cannot be refreshed, fail with the sentence that ends the investigation: the on-disk
credential is expired, an interactive session alive beside it is not evidence of health, and
re-authenticating interactively then re-launching is the fix. Run the probe at `dry_run` and
at detach pre-flight too, so an operator learns the seat is dead before designing a series
around it rather than after. The fail-closed behaviour is correct and stays; what changes is
when it speaks and what it says.

**Status (2026-10-08).** The open rest waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** M · **Source** [triage] · **Rows** T42a · **Status** partially shipped in
0.14.0 — the pre-spawn credential-expiry read and its located message (`interface/seat_probe.py`,
T60a in the 2026-09-13 delta triage) ship; refreshing the credential before copying it, and
running the probe at `dry_run` and detach pre-flight, remain open.

## Next

### CONV-B08 — Authoring doctrine gets a home, and the skill gets shorter.

**Cause / evidence.** `skills/convoy/SKILL.md` (~490 lines) is the default sink for every
doctrine promotion, and seven promotable authoring lessons arrived in one triage round —
each of which would otherwise become another paragraph in the file CONV-B04 shows is
already dense enough to hide a stale section for four releases. The series.toml schema is
also stated three times: `docs/design/02-formats.md` (authoritative), the skill (a full
table plus prose), and partially again in the MCP `Field(description=...)` blocks, which
load into every session that installs the plugin and are used in almost none. [triage:
2026-07-11 corpus, 2026-07-14 run-execution, 2026-08-01 wave-C close, 2026-08-02 close;
review; research on context economy]

**Change.** Ship `docs/authoring-series.md` with the plugin, as the design docs already
are, carrying: the gate-scope rule (T31a), gate hygiene (T31c — a subset-suite check must
neutralize repository-global coverage floors, and any check whose failure can be
environmental needs a `repair_hint` that does not point the fix spawn at repository
config), budget sizing to the wave's named-heaviest PR rather than the previous wave's
maximum, prompts-as-pointers, reference tables as sibling prompt files, prompts reading
read-only inputs outside the workspace, verify-then-act sweeps over an aged backlog, and
the caveat that `independent = true` asserts implementer-unreachability, **not** oracle
correctness — an out-of-tree oracle that silently no-ops passes green, which is exactly
what 14 green firings cannot distinguish from a working oracle. The skill links it and
**loses** the inline authoring guidance and the duplicated schema table, leaving trigger,
result envelope, and when-not-to-use. The review extends the row to the MCP `Field`
descriptions: one line each, pointing at the reference.

**Cross-review.** `docs/authoring-series.md` is being created as the sink for seven
promotions with no cap on it, which is the same shape as the SKILL.md problem it exists to
relieve, one level down and one release later. Give it a word budget on the day it lands,
not on the day it is too long: the sibling planning tool's row KEEL-B06 records the
budget-at-birth rule and calls it the highest-leverage process change available, on the
reasoning that a document only acquires a cap while someone still remembers what it is
for. State the budget in the file's own header, and require the next promotion into it to
name what it displaces. [cross-review]

**Delta pass, 2026-08-28.** Three more findings arrived that would each have been a
paragraph appended to `SKILL.md`, and are folded here instead — which is what this row is
for, and the reason it is worth building before the next one lands. (1) `[[checks]].phases`
displaces failure attribution silently: a defect introduced in an unscoped phase first goes
red at the next scoped one, attributed to the wrong PR and billed to its fix budget. (2)
Gate-scope authoring doctrine from a blind gate-sufficiency audit of seven series — the
vacuous shapes it catalogued live in check *content*, which the engine does not read, so the
only place they can be addressed here is authoring guidance. (3) Series-sizing calibration
from the first out-of-estate production night: an in-to-out token ratio near 178:1, cost
tracking cached input while wall-clock tracks output generation. Two adjacent findings from
the same reports did **not** come here: describing mid-series gate repair and the
driven-workspace hazard is documenting engine behaviour the manual owes a reader, not advice,
and both shipped in `[Unreleased]`.

**2026-10-06.** The guide gained one section ahead of this fold, by relocation rather than
addition: the smallest-unit gate doctrine (CONV-B69) moved out of CONV-B53's Status with its
limits, and the header's scope line names it. T31a and T31c are not built alone: alone, each
is a prose append to a budgeted file with nothing displaced, so they land with this row, in
the change that shortens SKILL.md and rewrites the guide's scope line.

**Effort** L · **Source** [triage] + [review] + [cross-review] · **Row** T38a (absorbs
T31a, T31c, and three 2026-08-28 documentation findings)

### CONV-B09 — The release discipline was mechanized without re-reading its reasoning, and the stated rationale is false.

**Cause / evidence.** `CONTRIBUTING.md:44` and `:75` both state that the plugin marketplace
serves tags, so anything sitting in `[Unreleased]` is invisible to installed consumers.
Measured false from installed plugin state in July: `git`/`github` marketplace sources
serve the **default branch** — one installed plugin comes from a repository with zero tags,
which is decisive, and a second is installed from an untagged merge commit despite the
repository having tags. The real consequence is the opposite and more damaging: unreleased
consumer-affecting work is not withheld, it reaches consumers under the **previous version
label**, so a consumer pinned to a version silently receives a contract change. The 0.7.0
work that mechanized the tag cited the report carrying this measurement and repeated the
falsified claim a third time, so the correction did not happen by being adjacent to the
fix. [triage: 2026-07-15 release-discipline (two findings), 2026-07-25 ledger drain §5]

**Change.** (a) Replace the rationale in both places; practice and cadence are unchanged,
only the reasoning moves (T34a). (b) Add a version-label check that fails when
`[Unreleased]` holds a `(consumer-affecting)` entry while the version sites have not moved
against the newest released section — distinct from `test_versions_are_locked`, which
asserts the sites *agree*, not that the label *moved* when consumer-affecting content did.
A green build, a shipped build and a correctly-labelled build are three claims and only the
first is checked today (T34b).

**Status.** (a) Shipped in 0.16.0, as T71a, which re-grounds this row's cause instead of
repeating it. The July measurement and the old rationale each saw one path of two: an install
takes the default branch's tip, and an existing install refreshes only when the manifest
version changes. On 2026-10-06 an existing install still ran the v0.15.0 tag's commit while
the marketplace's checkout of the default branch had moved past it. That is one observation,
consistent with this reading rather than proof of it. So unreleased consumer-affecting work
reaches new installs under the old label,
and reaches existing installs not at all until the cut. `CONTRIBUTING.md` §Release
discipline now states both paths in place of the one-path sentences; the practice, the
cadence and the `release-tag` workflow's rationale are unchanged. T71a supersedes T34a's
wording. (b), T34b, is open: no check compares the version sites against a
`(consumer-affecting)` entry.

**Effort** S for (a), M for (b) · **Source** [triage] · **Rows** T34a (superseded by T71a), T34b

### CONV-B10 — `convoy_run` blocks by default on a transport that cannot hold it, and pays schema in every session that installs the plugin.

**Cause / evidence.** The tool blocks for minutes to hours, while convoy's own skill tells
the caller not to use it that way ("do not hold a blocking `convoy_run` open — pass
`detach: true`"), and MCP progress notifications were declined precisely because `detach`
plus `convoy_status` closed the idle-timeout class. Meanwhile the docstring is about 45
lines of prose plus six `Field(description=...)` blocks, all duplicated in SKILL.md and
loaded into every session that installs the plugin. Tool-context economy is now a
first-class concern in the harness itself, which withholds most schemas until requested.
[review; research]

**Change.** Make `detach: true` the default and blocking the opt-in; cut the docstring and
each `Field` description to one line pointing at the reference from CONV-B08; fix the
module docstring's "two tools" (also listed under CONV-B04). **(consumer-affecting: the
default return shape changes)**

**Cross-review.** The run envelope has a live consumer outside this repository that no row
here names. A sibling evaluation harness runs convoy as one arm of a scored comparison: it
reads the run envelope and holds its own copy of the engine contract spec. Flipping the
default return shape is therefore a contract change for a program, not only a convenience
change for a human caller — the `(consumer-affecting)` marker above is necessary and not
sufficient, and the release entry should say plainly that the *default* moved rather than
that an option was added. The other direction is worth knowing before anyone treats the
envelope as internal: that harness's row FATH-B36 may retire the arm outright. Establish
which way it goes rather than assuming either. [cross-review]

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** M · **Source** [review] + [research] + [cross-review]

### CONV-B11 — A scaffolded series is non-portable by construction and leads with the lane that has never gone red.

**Cause / evidence.** `convoy init` writes machine-absolute `[paths]`, so a series
directory that travels by copy — the expected transport, since that directory is untracked
by the consuming project — keeps pointing at the authoring machine, and the same file needs
opposite values on two machines. One such series validated clean and would have burned two
PRs of budget before hard-failing on a path that does not exist on the executing machine.
The starter also leads with a blocking `independent` check and an out-of-tree oracle — the
lane that went red zero times in 14 production firings and that convoy's own trial measures
null at the tier 75 of 76 production spawns use — and hardcodes a starter model, a fourth
copy of the lineup. [triage: 2026-07-13 series-portability (two findings); review]

**Change.** Default `[paths].prompts` to the series file's own directory when unset (an
explicit value still wins), or accept a `${SERIES_DIR}` token usable in `[paths]`, and have
the scaffold emit that form (T33a). Demote the starter's independent oracle to a
commented-out example and make its blocking check a plain suite (see CONV-B32). Read the
starter model from the one tier table (see CONV-B14). T33a is the constructive dual of the
held path detectors in CONV-B24 — it removes the need for the machine-absolute path rather
than detecting one, with no regex, stat, platform branch or false-positive budget — and
would retire all three of them. **(consumer-affecting if the key becomes optional)**

**Correction (2026-08-28 delta).** The heading read "the lane that has never fired". It has
now fired, twice over: a second series declared `independent = true`, its out-of-tree oracle
ran end to end across every gate attempt, and its isolation contract was satisfiable from the
skill document alone on a machine that had never run convoy. What the lane has never done is
go **red** — `independent_red` is still 0 everywhere it has run. The precise claim is the
weaker one, and it is the one CONV-B32 and CONV-B33 actually rest on; the imprecise version
would have been read as evidence the mechanism does not work, which is not what the field
says.

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** M · **Source** [triage] + [review] · **Row** T33a

### CONV-B12 — `[governance]` carries model, effort, permissions, budgets and tools, so every other standing rule has exactly one carrier: the per-prompt brief.

**Cause / evidence.** The commit-message policy was restated in all nine briefs of one
series, and again across four consecutive series. [triage: 2026-07-11 v2, 2026-07-30
multi-wave, 2026-07-24 bakeoff, 2026-07-14 model-selection design]

**Change.** A series-level commit-message policy field under `[governance]`, appended to
every spawn's brief, so a standing rule is stated once per series rather than once per PR.
Settle in the same change which path produces the `<pr-id>: <title>` subjects seen in
repository history — the residual sweep commits only when the agent left work uncommitted,
so that subject is diagnostic of a brief that did not mandate committing, which is worth
stating rather than leaving to inference. **(consumer-affecting: a new series.toml key)**

**Cross-review.** CONV-B37 rides this mechanism with a second standing rule. Shape the
field here as a general standing directive with the commit-message policy as its first
instance, rather than a single-purpose key that has to be widened one release later.
[cross-review]

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** M · **Source** [triage] + [cross-review] · **Row** T35a

### CONV-B13 — The no-real-spawn guardrail is a convention, and the guardrail document states it as though it were a mechanism.

**Cause / evidence.** `tests/conftest.py` autouses a guard for the seat probe only; the
spawn path is stubbed per test by hand, so one forgotten stub re-opens the leaked-spawn
class that already cost real money once. `docs/GUARDRAILS.md` names this a mechanization
candidate while phrasing the property as though it held. Confirmed unbuilt in the current
tree. [triage: 2026-07-09 governance-cycle, 2026-07-06 baseline arc; review]

**Change.** An autouse fixture that stubs — or hard-fails against — the spawn path by
default, with an explicit opt-out for wiring tests, making the guardrail document's
existing claim true. `tests/conftest.py`.

**Status.** **Shipped** in 0.10.0 (built 2026-08-29). `tests/conftest.py` autouses a second
guard: a `HeadlessSpawn` left on the default `claude` binary raises instead of launching,
with the red proof in `tests/test_headless_spawn.py`; subprocess-path tests point the
spawn at a stub executable, which the guard passes through. `docs/GUARDRAILS.md` now
names the fixture instead of the convention.

**Effort** S · **Source** [triage] + [review] · **Row** T36a

### CONV-B14 — The model lineup is mirrored in four places with no age tripwire.

**Cause / evidence.** `core/governance.py::DEFAULT_TIER_MODELS`, `core/pricing.py::_FAMILY_RATES`,
the scaffold's starter model, and the skill's governance and cost sections. All four are
correct today; none carries a sync date, so a stale lineup is invisible until a run fails
at the seat probe. Self-containment is the right charter — it is what makes convoy
installable by a stranger — and it is exactly why the freshness discipline has to be
reproduced locally rather than inherited by reference. Assembling the list currently takes
an adversarial review pass, and the first attempt missed two sites. [triage: singleton;
review]

**Change.** Stamp the tier table with a sync date and add a test that fails once it is
older than about three months, the same shape as `test_versions_are_locked`. Accept an
optional `[governance.tier_models]` block in series.toml so an operator can correct a stale
lineup without waiting for a release. Write the maintainer note enumerating the mirror
sites so a lineup change touches them in one pass (T39a). CONV-B29 removes one of the four
sites outright.

**Cross-review.** Two amendments, and the first is a contradiction to settle before either
side builds. (a) This row records all four mirrors as **correct today**; the sibling
collection's row CRAF-B06 records the canonical tier data those mirrors copy from as
**stale**. Both cannot hold. Reconcile them before either row lands, because the order
matters: stamping a sync date on a lineup that is already behind dates the wrong thing,
and the age tripwire then certifies it for another three months — the tripwire would be
measuring the stamp, not the lineup. (b) Scope the maintainer note (T39a) to convoy's own
mirror sites, and separately register convoy in the collection's bindings file that the
lineup-refresh walk reads (CRAF-B13). Self-containment means convoy **carries the copy**;
it does not mean convoy is invisible to the walk that has to visit it. A mirror nobody
knows to visit is precisely the stale-lineup failure this row exists to prevent, and the
registration costs one line in a file outside this repository. [cross-review]

**Status.** **Settled by [ADR-0010](adr/0010-the-artefact-carries-the-lineup.md) in
0.13.0, by a different shape from the age tripwire this row asked for.** The row's problem —
a stale lineup that stays invisible until a run fails — is closed by making the lineup travel
in the run's own artefact. `[governance.tier_models]` lets the series file carry its
resolved tier table; `DEFAULT_TIER_MODELS` is documented as the floor it always was and
stamped `LINEUP_RECONCILED` with the date the upstream lineup was reconciled, not the date
the file was edited, as cross-review point (a) warned; and any tier resolved through the
floor raises an `Advisory(kind='lineup')` naming the model and that date. ADR-0010 records
why a dated copy with an age test was not enough: a date measures maintenance, not drift, and
on 2026-09-05 both freshness tripwires upstream were green while the lineup was stale.
CONV-B29 removed the price-table mirror in the same release.

Against the row's own asks: the `[governance.tier_models]` override shipped; the sync stamp
shipped as `LINEUP_RECONCILED`, feeding the advisory rather than a failing age test; the
maintainer note (T39a) is declined as superseded (see Declined); and point (b) is settled
outside this repository — the three mirror sites that remained (`core/governance.py`,
`skills/convoy/SKILL.md`, `interface/scaffold.py`) were registered with the lineup-refresh
walk. **The skill is no longer a mirror site** (2026-10-08, shipped 0.17.0): `SKILL.md` names no
model id, the example series uses `tier = "weak"`, and the manual points at the resolution
chain and the `lineup` advisory instead; `tests/test_doc_claims.py` fails if an id returns.
Two sites remain, `core/governance.py` and `interface/scaffold.py`; the scaffold still
emits `model = "<id>"`, so the README's example series, which shows `tier = "weak"`, is
introduced as a close variant of the `convoy init` output until that half lands. The
2026-09-26 lineup change (`strong` → `claude-opus-5-5`, served by 0.16.0) touched
the floor table, its stamp, its test and the CHANGELOG, and missed no site. The 2026-10-08
lineup change (`weak` → `claude-haiku-5-5`, `mid` → `claude-sonnet-5-5`, stamp 2026-10-08, the two
ids having become legacy) touched the floor table, its stamp, the scaffold's starter model, the
formats doc's example series, their tests and the CHANGELOG, and missed no site. Earlier history:
point (a) was resolved on 2026-08-11, when the canonical lineup was reconciled and convoy's
mirrors re-synced against it, shipping in 0.9.0 as the `strong` tier resolving to
`claude-opus-5`.

**Effort** S–M · **Source** [triage] + [review] + [cross-review] · **Row** T39a, escalated
from `watch` by the review (declined as superseded, 2026-10-06)

### CONV-B15 — The four gate commands run in CI and by hand, never at commit time.

**Cause / evidence.** There is no `.pre-commit-config.yaml`. For a repository whose own
history records four separate version fields drifting apart, and whose release discipline
had to be mechanized twice, a commit-time layer is the missing rung. [operator observation;
review]

**Change.** Add `.pre-commit-config.yaml` running the same four commands plus
`uv lock --check`, preserving `ci.yml`'s ordering constraint — the lock check must precede
anything that would silently repair the lock.

**Cross-review.** Installed in the default form this will not run at all on the machine
convoy is developed on: the bare `pre-commit` shim is blocked by that machine's
application-control policy, while hooks git invokes itself run normally. So the default
install produces a config that looks present, never fires, and quietly returns the
repository to the CI-and-by-hand state this row exists to close — a worse outcome than not
adding it. Install it in the `core.hooksPath` script form recorded in the sibling row
MANT-B11 — a checked-in hooks directory holding a script git executes — and cite the
exemption list in CRAF-B26 from the contributor docs, so the next person does not diagnose
this from scratch. The four commands and the ordering constraint are unchanged; only the
installation form moves. [operator observation; cross-review]

**Status.** **Shipped** in 0.10.0 (built 2026-08-29), in the `core.hooksPath` form the
cross-review prescribes: tracked wrapper scripts under `scripts/git-hooks/` invoke
`uv run python -m pre_commit`, so the lane runs on a machine that blocks bare executable
shims. The config mirrors the fast half of the gate in CI's order (`uv lock --check`
first; ty and pytest stay CI-owned), adds a commit-message lane (conventional subject, no
attribution trailers), and `tests/test_doc_claims.py` pins the hook commands to
`ci.yml`'s, in CI's order, so the mirror cannot drift.

**Effort** S · **Source** [review] + [cross-review]

### CONV-B16 — A mid-run git failure leaves telemetry dangling after `run_start`.

**Cause / evidence.** Same class as the two runs with no terminal record: an exception path
that never writes a terminal line, so the ledger cannot answer for the run afterwards.
[triage; review, which asks to promote it from `watch` alongside CONV-B02]

**Change.** Classify it as a halt, reusing the infrastructure-halt pattern (`_skip_remaining`
plus `RunComplete` with a distinct outcome). `interface/drivers/headless.py:235-243`,
`core/telemetry.py`. **(consumer-affecting)**

**Status (2026-10-08).** Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md), unless the owner classifies it as a fix for a defect that corrupts a workspace.

**Effort** S · **Source** [triage] + [review] · **Row** T15b

### CONV-B17 — The CLI rejects the argument name the MCP tool just taught the operator.

**Cause / evidence.** The MCP tool takes `series_file` and `workspace` as named arguments
while the CLI takes the series file positionally and rejects `--series`, so the natural
transcription from a just-used MCP call fails — and it is attempted precisely when a
detached run has died and the operator is already recovering. Third member of the CLI/MCP
drift family after `--workspace`, which shipped in 0.4.0. [triage: 2026-07-31 remediation
wave A, 2026-07-08 baseline, 2026-07-09 v1; review]

**Change.** Accept `--series` as an alias for the positional argument, or at minimum name
the positional in the usage error ("pass the series file positionally"). The error-text
half is cheaper and probably sufficient. `interface/cli.py`.

**Status.** Shipped in 0.16.0 (T37a), as the error-text half, widened to every verb that
takes the series file positionally — `validate`, `gate`, `run`, `clean`, `unlock` and
`status` — since this row's evidence is the recovery verbs. Each declares `--series` and
`--series-file` (the MCP tools teach `series_file=`) as a hidden option that exits 2, the
code it exited with before, with `the series file is positional, not a flag: convoy <verb>
<series.toml>`. No alias; the flags stay out of `--help`.

**Effort** S · **Source** [triage] + [review] · **Row** T37a

### CONV-B36 — A run records nowhere which spec it was decomposed from, so the planning ledger and the run ledger have no join key.

**Cause / evidence.** The sibling planning tool specifies a spec pin in its row KEEL-B16:
the content hash of the spec a series was decomposed from, plus that spec's repo-relative
path, resolved and matched **before any paid run**. convoy is the half that has to carry
it, and today it carries nothing. `[series]` holds `id` and `version` and no spec
reference; `run_start` records `run_id`, `series_id` and advisories, so the pin — however
carefully computed on the planning side — stops at the series file and never reaches the
run record. The consequence is that no one can afterwards answer "which version of which
spec produced this run", which is the same silent-measurement shape as CONV-B06: nothing
fails at run time, and the comparison the ledger exists to support is simply unavailable
later. [cross-review, receiving KEEL-B16]

**Change.** (a) Accept a series-level spec pin under `[series]` — the spec's repo-relative
path and its content hash — and record both on the `run_start` line, so the pin reaches
the run record rather than stopping at the file. (b) Add a pre-flight check that resolves
the path and compares the hash, and fails the run before the first spawn is purchased,
which is what "before any paid run" means. Blocking, not advisory: the point is that no
paid run executes against a spec that has moved since decomposition. Unlike the held
detectors in CONV-B24 this needs no heuristic and has no false-positive budget — a hash
matches or it does not. Path resolution is repo-relative by construction, so it does not
reintroduce the machine-absolute problem CONV-B11 removes. `core/spec.py`,
`core/preflight.py`, `core/telemetry.py`, `interface/drivers/headless.py`.
**(consumer-affecting: a new series.toml key and new `run_start` fields)**

**Status.** **Shipped** in 0.8.0, confirmed load-bearing in production (2026-08-28 delta):
two series in one night carried the pin, the spec moved between authoring and launch on one
of them, and the pin is what made "which revision produced this run" answerable without
archaeology. **CONV-B38 builds directly on it** — the pin resolves and hashes the spec before
the first spawn is purchased, which is exactly the moment a readiness gate has to run, so
that row adds a question at a seam that already exists rather than a new one. Both halves.
`[series]` takes optional
`spec_path` + `spec_sha256` (set together, path rejected if absolute, hash validated as a
SHA-256 digest at load); a blocking `kind='spec_pin'` pre-flight check resolves and compares
before any spawn; and the matched pin is recorded on `run_start`. Deliberately **not** added
to the run envelope: the row asks for the ledger's `run_start` line, and the envelope has an
external consumer, so widening it is a separate decision.

**Effort** M · **Source** [cross-review] · **Receives** KEEL-B16

### CONV-B37 — A verification directive is a standing rule with no carrier, and its measured lift is discipline-dependent rather than general.

**Cause / evidence.** Routed here by the cross-project pass. A series-level standing
directive — one short instruction appended to every spawn's brief, the motivating case
being a verification directive that tells the agent to check its own claim before
reporting done — is the same shape as the commit-message policy in CONV-B12 and wants the
same carrier rather than a second one. What the routing also carries is the measurement,
and the figures this row first recorded were **wrong**. They are corrected below against
the source runs (2026-08-12).

The corrected numbers — the promoted gate's lift over its own bare baseline, on a
leave-a-check-behind proxy:

| Discipline | Weak tier | Mid tier | Strong tier |
|---|---|---|---|
| Verification | **+0.22** | **+0.56** | **+0.44**, 90% CI [+0.11, +0.78] |
| Debugging | +0.11 | +0.22 | not measured |
| Data verification | +0.00 | +0.00 | not measured |

Four corrections, because each one changes what an author would conclude:

- **The +0.56/+0.56 pair cited for verification was not the promoted arm's.** It belonged
  to a **prescriptive** wording of the same gate that the same run **rejected**: it won the
  primary metric outright and then performed the behaviour on 58% of trivial edits in the
  paired null banks, and the pre-registered false-positive constraint killed it. The arm
  that was promoted is the discipline-worded one, and its verification lift is +0.22 at the
  weak tier, not +0.56. The source run's own findings say so in as many words; the
  misattribution entered downstream, in the one-line summary this row copied.
- **Each pair is two tiers, not two runs.** This row read "+0.11 and +0.22" as one figure
  reproduced across two studies. They are the weak- and mid-tier cells of a single one.
- **There is no tier collapse.** A later 72-trial run measured the same gate at the strong
  tier at +0.44, 90% CI [+0.11, +0.78] — excluding zero, at zero false-positive cost. The
  pre-registered risk that a strong model would leave no headroom did not materialise: the
  bare strong-tier arm still skipped verification on 44% of delegated tasks.
- **The claimed replication over 165 pre-registered trials never happened for
  verification.** That 165-trial run was a separate pre-registered study of **debugging and
  data verification** — it is where the +0.11/+0.22 and +0.00/+0.00 figures come from — not
  a re-run of the verification bank. The verification figures rest on one 648-trial run plus
  the 72-trial strong-tier run.

The row's headline survives all four: the lift is discipline-dependent rather than general,
so the field is worth having and a default-on directive is not. The corrections move it in
one direction — at the weak tier the promoted gate buys half what this row claimed, while
data verification stays a measured null on both tiers it ran on. One operational rule
travels with the correction and belongs beside the field: a **paired null bank is mandatory**
for anything gate-shaped, because without it the run would have shipped the arm that
over-triggers. [cross-review]

**Change.** Generalize CONV-B12's mechanism instead of adding a parallel one: a single
`[governance]` standing-directive field appended to every spawn's brief, with the
commit-message policy as its first instance. Build it with or after CONV-B12, never
before, so there is one carrier and not two. Record the corrected per-tier table above
beside the field's documentation — including the two zeroes and the rejected prescriptive
arm — so an author deciding whether to set it meets the null cases and the over-trigger
case rather than a general endorsement.
**(consumer-affecting: a new series.toml key)**

**Status.** **Corrected, not built** (2026-08-12). The measurement half of this row was
imported from another project's evidence and carried a figure that belonged to a rejected
arm; the table above replaces it. The change itself is unbuilt and still gated on CONV-B12.
No convoy behaviour depended on the wrong number — the row had not been built — but it was
the row's whole argument for how strongly to recommend the field, which is why the
correction is recorded rather than quietly overwritten.

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** S–M on top of CONV-B12 · **Source** [cross-review] · **Gate** CONV-B12

### CONV-B42 — The remedy a dead run advertises is heavier than the situation needs, and the branch that blocks a restart still has to be deleted by hand.

**Cause / evidence.** CONV-B02 shipped and works — `dead` was claimed correctly twice in one
night, on the positive evidence of a lock whose owner is gone, and an operator called it
exactly what was asked for. What shipped with it is a `message` that says to run `convoy
clean`, and `clean` discards uncommitted changes and deletes branches. After a spawn killed
mid-implementation that is precisely the work an operator may still want to inspect. What
was actually needed both times was the *safe half*: verify the owner pid is gone, remove
`.git/convoy-run.lock`, resume with the partial work intact — done by hand, twice.

The second half is the same night's other manual step: a PR branch sitting at exactly the
integration tip, zero unique commits, blocking a clean restart. Four instances across the
two 2026-08-25 reports, on top of the two the campaign already recorded — and the check that
would clear them safely is the one an earlier finding already proposed for `resume`
pre-flight. Both are cheap, both are decidable from positive evidence, and both are
currently a procedure an operator has to know. [triage: 2026-08-25 seven-series #4/#5,
2026-08-25 gate audit #5; extends the lock lineage and CONV-B02 post-ship]

**Change.** Split the remedy. A lock release that is safe by construction — confirm the
owner process is gone, remove the lock, log that it did — named *first* in the `dead`
message, with `clean` kept for the case where a wipe is what the operator wants. Then have
`resume` pre-flight compare each PR branch against the integration tip and self-clear the
zero-unique-commit case with a logged note, which is the state that already cannot lose
work. **(consumer-affecting: a new recovery verb or flag)**

**Effort** M · **Source** [triage] · **Rows** T43a, T43b · **Status** shipped in full in
0.14.0. T43a (the lock half — `convoy unlock`, `interface/cli.py`; the `dead` message now
names it instead of `clean`; T56a/T56b in the 2026-09-13 delta triage) confirms the owner
process is gone before it acts: `workspace_lock.lock_ownership` composes `lock_owner_pid`
with `process_is_alive` — the same predicate `convoy status` derives its `dead`/`running`
split from — and `unlock` refuses, naming the pid, when the owner is still alive;
`--force` overrides for a reused pid or a distrusted check. (An initial build of this row
called `remove_stale_lock` unconditionally, exactly as `clean` does, and shipped without
that confirmation; caught in review before merge and closed in the same PR.) T43b (`resume`
pre-flight self-clearing a zero-unique-commit PR branch) shipped earlier and was
field-confirmed 2026-09-13 (five branches skipped, $0 re-spent).

### CONV-B43 — A run can be over while `convoy_status` still says `running`, and the result file exists from launch, so neither the state nor the file answers "is it finished?".

**Cause / evidence.** Two shapes of the same gap, from the first multi-series night driven
entirely through detach and polling. (a) A spawn died, the engine's own `git commit` failed,
and `result_path` received a terminal envelope — `{"ok": false, "outcome": "usage",
"error_kind": "git"}` — while `convoy_status` went on answering `running` with `in_flight:
"implementation"`, because no `run_complete` line ever reached the ledger. The documented
fallback covers a run that died *before* writing to the ledger; this one wrote, then failed
terminally without closing. A poller that trusts `state` waits forever on a run that is
already over, and it was caught only because a file watcher noticed the result JSON gaining
bytes. (b) That result file is created empty at launch, so existence is not completion — a
watcher testing for the file fired instantly at launch. A third, smaller face: `economy`
advances only when a spawn completes, so a 94-minute spawn reports an unchanged cost for 94
minutes and status cannot distinguish progress from a hang. [triage: 2026-08-25
seven-series #1, #2, #6]

**Change.** (a) Have the status fold read `result_path` whenever the ledger lacks a terminal
line **and** the file is non-empty, not only in the never-wrote-to-the-ledger case, and
report `finished` with that envelope. (b) Either create the result file at terminal time, or
write a `{"state": "running", "run_id": …}` stub at launch so a reader can branch on content
rather than existence — and document whichever. (c) Add `in_flight_since` to the `prs[]`
entry so monitoring does not require tailing a log.

**This touches the MCP surface, so the burden of proof sits here.** That surface recorded
146 calls with zero errors in the telemetry window and the detach-plus-poll shape is why;
nothing in this row changes it. (a) and (c) make the same poll answer correctly and add a
field to an envelope callers already read. (b) is different: it changes what a documented
file contains, and a consumer parser is known to read that contract. **Hold (b) until the
consumer-notification step of CONV-B46 exists, then ship the two together** — shipping a
contract change through the exact gap another row in this pass describes would be a poor way
to learn the lesson. **(consumer-affecting: a `state` reachable by a new route, a new
`prs[]` field, and for (b) a change to the result file's contract)**

**Second report for (b) (2026-10-06 triage).** A three-PR run on 2026-09-26 met the same
contract: the result file is created empty at launch and filled at the end, so a background
waiter that tested for existence fired at once and had to test for a non-empty file instead,
and a reader of the outputs directory cannot tell started from finished by the file alone.
(b) stays gated on CONV-B46. [triage: 2026-09-26 three-PR run, §Friction]

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** S for (a) and (c) · S for (b), gated · **Source** [triage] · **Gate** CONV-B46 for (b) · **Rows** T44a, T44b, T44c

### CONV-B44 — After a halt caused by a mis-authored check, `resume` deletes a branch that the corrected checks pass on.

**Cause / evidence.** `resume` treats an unmerged PR branch as a partial or gate-failed
attempt and deletes it, which is right when the *work* was what failed. It is wrong in the
one case this corpus produced: the halt was caused by a check that could not pass (CONV-B40),
the operator fixed the check, and the branch the corrected gate would have passed was
destroyed by the recovery. The series was finished outside convoy to keep the verified commit
— so, again, the ledger records no integration for content that integrated. [triage:
2026-08-24 corrective wave #3]

**Change.** When `resume` finds an unmerged PR branch **and** the series diff since the
halted run touches only `[[checks]]`, re-gate the existing branch before deleting it, and
integrate on green. The condition is narrow on purpose: a series edit that touched prompts
or PR definitions means the branch was built against different instructions and the current
delete-and-re-implement behaviour is correct.

**Status (2026-10-08).** Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md), unless the owner classifies it as a fix for a defect that corrupts a workspace.

**Effort** M · **Source** [triage] · **Rows** T44d

---

### CONV-B60 — On the Agent tool's default dispatch, a residual red after the judge's repair round reaches nobody.

**Cause / evidence.** The Agent tool dispatches asynchronously when `run_in_background`
is unset (observed in a real `claude -p` session, CLI 2.1.258; not documented). The hook's
messenger leg fires at the tool call with `async_launched` and gates nothing; the judge leg
blocks the subagent's stop once with the repair brief and, on the retry, records a residual
red and lets it stop. That red then lives in `.convoy/hook.log` and in whatever the subagent
chose to say — the orchestrator is never told by the hook. On a synchronous dispatch the
messenger tells it. Review S15 on the 0.12.0 candidate; documented in the skill and
the CHANGELOG as the limit it is.

**Change.** Measure first: Part 2's hook arms count how often the judge's one round leaves
a residual red (`hook.log`, `blocked_stop: false` records). If it is common, add an
orchestrator-side `Stop` leg: when the session's own turn ends with a judge record still red
for a subagent of this session, exit 2 once with the brief — behind the same trust switch,
bounded by `stop_hook_active` like the judge. If it is rare, the documented limit stands.

**Effort** M · **Source** [review] · **Gate** the Part 2 hook arms

### CONV-B61 — The hook's timeout and the gate's per-check timeouts are unrelated numbers, and the only path on which the hook says nothing is the one where they collide.

**Cause / evidence.** `hooks/hooks.json` gives Claude Code 1800 s per firing; each check is
bounded by the spec's `timeout_seconds` (default 300) and a scaffolded Python gate has five
checks. A gate whose checks together outrun the hook is killed by Claude Code: no log line,
no exit 2, indistinguishable from green — against the "never a silent green" claim the
hook otherwise keeps. Review D6; the docs now say so, the code does nothing about it.

**Change.** `convoy gate --init` writes a `timeout_seconds` whose sum over the scaffolded
checks stays under the shipped hook timeout, and `convoy validate` warns when a project
spec's sum exceeds it; the hook's own record could carry the budget it ran under so a killed
firing is at least reconstructible from the previous one.

**Status.** Shipped in 0.16.0. A gate spec carries one `timeout_seconds` applied to each
check, so the sum is the check count times that value. `HOOK_TIMEOUT_SECONDS` (1800) is a
package constant, pinned to `hooks/hooks.json` by CONV-B64's test. A gate's worst case may
use `GATE_BUDGET_SECONDS` (1500) of it, which keeps 30 s for the hook itself and at least
270 s for a firing waiting on CONV-B62's judge lock; the bare timeout was the first
threshold, and a blind review measured what it left: the six-check scaffold filled it, so a
second firing could not wait at all. `convoy gate --init`
lowers `timeout_seconds` until the scaffolded checks fit the budget (five checks keep the
default 300 s, the six-check `--independent` scaffold gets 250 s), and `convoy validate` on a
gate-only file warns on stderr when checks × `timeout_seconds` exceeds the budget, with the
exit code and stdout unchanged. The third clause — the hook's record carrying the budget it
ran under — is not built.

**Effort** S · **Source** [review]

### CONV-B62 — Concurrent judge firings run the suite concurrently in one tree and append to one log without a lock.

**Cause / evidence.** Several subagents stopping at once each fire `SubagentStop`; each runs
the full check suite in the same workspace (shared `.pytest_cache`, `__pycache__`, build
output — spurious reds) and appends to `.convoy/hook.log` with a plain `open('a')`, which
is not atomic across processes on Windows; an interleaved line degrades to a re-run, not to
a false green. Review S12, second half; the first half (refuse a workspace a `convoy run`
holds the lock on) shipped in 0.12.0.

**Change.** Two cases, two remedies. Concurrent *judges* reading one tree: an advisory lock
of the hook's own around the gate run and the log append, with a bounded wait and a loud
exit 2 on contention, so two judges never grade one tree at once and no two log lines
interleave. It is not `workspace_lock`, which has no wait loop, is the run lock that
`status`, `unlock` and `clean` read, and lives in `.git`, which a tree outside a repository
lacks and a worktree has as a file. Concurrent *writers* in one tree are a different case,
and no lock fixes it: each subagent's gate judges whatever the others have half-written,
so a green can belong to a neighbour's edit. Writers need separation, a worktree per agent,
which the operator arranges; the lock only orders the judging.

**Status.** Shipped in 0.16.0 (T61c). A firing that runs a gate holds `.convoy/judge.lock`
until its log line is written, and every append holds `.convoy/hook.log.lock`. One that
waits out its bound exits 2 like a gate that could not run, recorded with the new outcome
`busy`. The bound is at most 600 s and shrinks so that the wait plus the gate's worst case
fits the 1800 s hook timeout with a 30 s margin; a gate inside CONV-B61's 1500 s budget
waits at least 270 s, and a gate whose worst case fills the timeout does not wait. On the
judge's retry a lock still held lets the subagent stop, as for any gate that could not run,
recorded as `busy` with its own reason, so the stops that
carried no verdict are counted rather than read as `usage`. Blocking that retry again was
weighed and not built: it would break the one-repair-round bound, and under a gate that
leaves no time to wait it would spin. A lock naming a process that is gone is taken over,
and so is one naming no pid after ten seconds, or a leftover `judge.lock.break` file. The
busy error advises removing a lock by hand only when its holder is gone; for one that may
still run it says another firing is at work and, on a first stop, that stopping again
retries. The scaffold's `.convoy/.gitignore` covers both locks. The writers case is documented in the
skill, not built.

**Effort** S · **Source** [review] · **Row** T61c

### CONV-B68 — The skill's description names two dispatch cases, and the case where isolation is the whole need — several agents writing to one checkout — is not one of them.

**Cause / evidence.** A hand-rolled fan-out launched write-capable agents in parallel into
shared checkouts: one ran `git stash -u` over another's in-flight edits, another checked out
a branch under a third, and a commit landed on a branch an agent was rewriting. About an
hour of recovery and one change redone, and nothing saw it, because each agent's own commands
succeeded. convoy's runner never lets two writers share a checkout — it drives one spawn at a
time, each on its own branch, under a run lock — yet the skill's description, where the
dispatch decision is made, names a settled plan and the standalone gate, never concurrent
writers. A second report, from the hook build, met the same cause on
the judge side, which is CONV-B62. [triage: 2026-09-05 hand-rolled fan-out (three findings
and a HIGH dispatch miss), 2026-09-02 hook build #4]

**Change.** A third dispatch case in the description, in the sentence structure the two
capabilities already use: two or more agents that will write to the same checkout, whatever
the plan looks like — with the boundary in the same breath (not for concurrent readers, which
need no isolation). It extends the description's existing enumeration rather than adding a
section. The sibling row T61b (watch) would document the worktree-per-agent pattern for a
hand-rolled fan-out to copy.

**Status.** Proposed. The description in `skills/convoy/SKILL.md` still names two
capabilities and no concurrent-writers case. Since CONV-B62's change the skill's hook section
says that subagents editing at the same time need a tree each, which reaches a reader only
after the dispatch decision.

**Effort** S · **Source** [triage] · **Row** T61a

### CONV-B75 — A worktree-isolated subagent is judged against the main checkout, not the worktree that holds its changes.

**Cause / evidence.** The 2026-10-08 probe ([the note](notes/2026-10-08-subagentstop-under-workflow.md))
ran two agents the Workflow tool started, one with `isolation: 'worktree'`. The isolated agent's
`SubagentStop` payload carried its own worktree as `cwd`
(`<project>\.claude\worktrees\wf_7edbbf40-6d1-2`), yet the hook log records `spec`
`<project>\.convoy\gate.toml` and `workspace` `<project>`, and the check ran with `check_cwd`
`<project>`. The cause is the discovery order in `gate_service.find_gate_spec`:
`$CLAUDE_PROJECT_DIR/.convoy/gate.toml` is tried before the walk up from the payload `cwd`.
With a committed spec and no `$CONVOY_GATE_SPEC`, the worktree's own tree is therefore not the
one judged (read from the code; the probe observed the untracked case). A check that reads the
working tree therefore passes or fails on the main checkout's files, not on the edits the
isolated agent made. The probe's agents wrote
outside their worktrees, so the note shows the tree the gate ran in, not a missed red; no red
was observed. [probe 2026-10-08]

**Change.** Not chosen. The options on the table: (a) discovery prefers the walk from the
payload `cwd` when that `cwd` is a git worktree of the `$CLAUDE_PROJECT_DIR` project, so the
gate runs in the worktree that holds the agent's changes (this changes which tree a check
executes in, and needs the trust rule to say whether a worktree inherits its main checkout's
entry); (b) the hook names the judged tree in the repair brief and on stderr (the record already
carries `cwd` and `workspace`), so a mismatch between the agent's `cwd` and the judged
`workspace` is visible without changing what runs; (c) both. The skill's advice to give each
concurrent writing subagent a worktree (`skills/convoy/SKILL.md`, the paragraph on the judge
lock) assumes each gate judges that agent's own tree, so the chosen fix must revisit it.

**Status.** Proposed, not built. `find_gate_spec` still orders `$CLAUDE_PROJECT_DIR` before the
payload `cwd`, and `hook.log` already records both `cwd` and `workspace`, which is how the
probe saw the difference. Trust is keyed on the project root and the spec's hash
(`gate_service.trust_status`), so the trust rule needs reading before option (a) is chosen.

**Effort** M · **Source** [probe 2026-10-08]

## Later

### CONV-B18 — Measure whether per-PR governance overrides are used, before keeping the machinery that serves them.

**Cause / evidence.** ADR-0007 has a real motivating argument (over-provisioning: a
strong-tier series where every PR passed first attempt) and superseded ADR-0005 on
production evidence, and triage retired the model-selection family as closed. The ledgers
say the feature is nearly unused: 75 of 76 spawns ran on one strong-tier model and exactly
one on another. The override is correctly implemented — the model/tier pair replaces
wholesale rather than merging, which would silently pick the wrong model — and cheap to
parse, but it costs pre-flight complexity, per-model seat-probe fan-out and the
`effective_model` folding. Either the operator never mixes tiers, or the sibling planning
tool that is supposed to emit per-PR tiers is not doing so — a seam this backlog has
recorded since T5a. **Disagreement:** triage treats the family as closed on production
evidence; the review treats the closure as unearned until the feature is actually
exercised. [review; triage row T5a]

**Change.** Measure before touching anything: over the next campaign, count PRs whose
resolved model differs from `[governance]`, and compare realised spend against a
same-series all-strong counterfactual. If the count stays near zero, keep the parser
support and retire the fan-out — see CONV-B33.

**A data point (2026-10-06 triage).** The 2026-09-26 three-PR run set `tier` and `effort` on
every PR under a series `[governance]` of `strong` / `high`: one PR ran the mid-tier model at
`low`, one the strong model at `xhigh`, and one at the series values. One PR of three
resolved to a model other than `[governance]`'s, and it cost $0.32 of the run's $18.60; the
two strong-tier PRs carried 98.26% of the spend. By the count this row names, the override
is in use. The other half — realised spend against an all-strong run of the same series — is
still unmeasured, and one run is not a campaign, so CONV-B33 stays gated. [triage:
2026-09-26 three-PR run; economy re-derived from its ledger]

**Status (2026-10-08).** Excepted from the runner freeze of [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md), as the measurement that gates the CONV-B33 retirement.

**Effort** S to measure · **Source** [review]

### CONV-B19 — Measure the three isolation arms before keeping the credential copy.

**Cause / evidence.** The goal is more clearly right than ever: a bare one-word prompt run
under the full operator config cost $0.0247 and about 35k input tokens, because plugins,
skills and MCP schemas load before the agent does anything — a scored spawn must neither
pay for nor be influenced by the operator's toolkit. The implementation is the problem: it
copies a hardcoded credentials file into a temporary config directory and hopes nothing
else in that directory was load-bearing — a dependency on a private, undocumented format.
Flags that did not exist when it was written now do. Neither `--safe-mode` (it also
suppresses the *workspace's* own CLAUDE.md, which convoy deliberately keeps) nor `--bare`
(API-key auth only, so it cannot serve a subscription seat) is a drop-in, but
`--setting-sources` plus `--strict-mcp-config` might be. [review; research]

**Change.** Run one spawn per arm on a subscription seat — current temp-directory copy;
`--setting-sources project,local --strict-mcp-config`; `--safe-mode` — and record three
booleans each: does it authenticate, do operator hooks/plugins/skills load, does the
workspace's own CLAUDE.md load. Keep `_ENV_STRIP` regardless: billing and routing diversion
is a separate concern and no flag covers it. Feeds CONV-B34.

**Status (2026-10-08).** Excepted from the runner freeze of [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md), as the measurement that gates the CONV-B34 retirement.

**Effort** S to measure, M to act · **Source** [review] + [research]

### CONV-B20 — Nothing counts how often an advisory fires, so no producer's calibration can be revisited on evidence.

**Cause / evidence.** The channel is well-shaped: a distinct type so advice can never reach
the list that decides runnability, carried on the `run_start` line since 0.7.0 so one
mechanism serves the CLI reporter, both envelopes and `convoy_status`. But neither existing
producer has a recorded firing rate, and the channel invites detectors — a three-design
panel measured **zero** actionable firings over 324 real files for the first one proposed.
[triage rows T23a, T25a; review]

**Change.** Count advisory firings per run in the ledger, then hold every new detector
behind a measured base rate.

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** S · **Source** [review] + [triage]

### CONV-B21 — Terminal (whole-series) checks that run once after the final PR integrates.

**Cause / evidence.** T19b, held at `watch` with a reason: the gap that motivated it — a
subset gate cannot see a full-suite-only regression — was closed in practice by the
gate-scope rule at the cost of one line per series, and three consecutive waves then closed
with no post-run surprises. The mechanism is still distinct from phase scoping (pay an
expensive whole-series check once rather than per-PR) but its remaining yield is now
unmeasured. Needs a new position in the run loop, after the PR walk. [triage]

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** M · **Source** [triage] · **Row** T19b

### CONV-B22 — A per-PR `budget` override, gated on an ADR rather than a parser change.

**Cause / evidence.** The asymmetry is the odd one out: model, tier and effort became
per-PR in 0.2.0 while budget stayed per-role, so the one governance axis that halts a run
is the only one that cannot vary. Real cost of the workaround: one chain ran
$16.07/$17.57/$30.72 per PR against $6–14 for the rest of the wave, so the operator raised
the implementation cap for everyone. Held deliberately — per-PR `budget`/`budgets` are
rejected by an explicit decision documented in three places, so reversing it needs an ADR
answering what a per-PR scalar binds to when a PR spawns twice, once to implement and once
to repair. Both inputs agree it should be re-opened after CONV-B01 lands, and that
CONV-B01 plus the sizing rule in CONV-B08 is the cheaper half of the cluster. [triage;
review]

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** L · **Source** [triage] + [review] · **Row** T32b

### CONV-B23 — Per-role `effort` under `[governance]`.

**Cause / evidence.** The same shape as the existing per-role `budgets`/`tools` tables, and
`resolve_spawn` already keys on role, so the seam exists. `effort` is series-global today
and applies to implementation and repair alike, though a fix spawn repairing a small gate
red plausibly wants a different level. Distinct axis from the per-PR override. Singleton.
**(consumer-affecting)** [triage]

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** S · **Source** [triage] · **Row** T22a

### CONV-B24 — Path-portability detectors, held behind a measured base rate.

**Cause / evidence.** T23a, T27a and T27b all propose detecting unportable absolute paths.
A three-design panel re-implemented each rule and ran it over 324 real files: **zero
actionable firings**, every hit a placeholder, a deliberate remote reference, or a token
the scanner had truncated mid-path. Two findings must survive into any future attempt: a
truncated token must never be reported (`C:\Users\alice\My Documents\spec.md` fires as
`...\My`, naming a string the author never wrote, and it fails in exactly the cross-machine
case the row exists for), and a foreign-flavour token must never be stat-ed (a POSIX root
resolves drive-relative on Windows, and a UNC or dead mapped drive blocks for up to 21
seconds). CONV-B11 addresses the same problem constructively and would retire all three.
[triage]

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** M if ever built · **Source** [triage] · **Rows** T23a, T27a, T27b

### CONV-B25 — Restamp or scope the design documents.

**Cause / evidence.** All four design documents are dated drafts from 2026-07-03/09 and now
under-describe a system four releases ahead of them. [review]

**Change.** Either restamp them, or add a line stating that the shipped contract is the
skill plus `02-formats.md` and the design docs record the reasoning at the time. The false
CI claim in `00-overview.md` §7 rides with CONV-B04.

**Effort** S · **Source** [review]

### CONV-B26 — Decide whether independent DAG branches should execute concurrently.

**Cause / evidence.** v1 is strictly sequential, so today the DAG buys ordering and halt
propagation — 21 truthful `pr_skipped` lines in production — not throughput. That is worth
stating plainly in the docs either way. Native fan-out covers *independent* subtasks and
explicitly does not find hidden dependencies, so the ordered-integration case stays
unserved; the open question is whether convoy should run independent branches concurrently
or stay sequential and cheap. Needs a design before a build: concurrent checkouts against
one workspace is precisely what the workspace lock forbids, so parallelism implies
per-branch worktrees and a different isolation story. [research; review]

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** L · **Source** [research] + [review]

### CONV-B27 — Record the thin-governed-layer position as an ADR.

**Cause / evidence.** The landscape brief's central finding is that every orchestration
mechanism convoy was originally built for is now native: spawning, fan-out, per-agent model
and effort, worktree isolation, a session budget, resume, structured returns. The
independent review reaches the same split from the other direction — roughly 40%
infrastructure the harness has absorbed, wrapped around 60% the harness still does not do:
a deterministic shell-command gate as the sole merge arbiter, a bounded repair loop
re-briefed with the failing check's own output, branch-per-PR merge-into-integration with
resume-by-ancestry, and an append-only per-spawn economy ledger a third process can read.
Both note that the strongest published account in this category is a repository-specific
control plane over a commodity harness, not a from-scratch engine, and that an
openly-published orchestration spec its vendor declined to productise is the strongest
single input to any build-versus-adopt verdict. [research; review]

**Change.** Write it down as an ADR: what convoy is (a thin governed layer over a
commodity harness), what it will keep (gate, ledger, per-role caps, branch/integrate/resume),
and what it will stop maintaining (a hand-rolled adapter, a private credential-copy trick,
a tier table, a price table). The retire list below then has a stated principle behind it
rather than case-by-case judgement.

**Cross-review.** Two things this row treats as established are not. (a) The ADR's central
claim — that the residue is a deterministic gate, a bounded repair loop, branch-per-PR
with resume-by-ancestry, and an economy ledger — is exactly what a sibling evaluation
harness's row FATH-B17 proposes to *measure*: the governed arm against a bare arm at the
weak tier, the tier where the bare arm actually fails, which is the only place the
comparison can discriminate. Sequence the ADR after that measurement, or write the claim
as unmeasured and name FATH-B17 as what would settle it. An ADR that reads as settled
while its measurement is outstanding is the shape of the release rationale in CONV-B09 — a
claim mechanized before anyone checked it, then repeated a third time because the fix sat
next to it. (b) Record in the ADR whether the published orchestration spec the landscape
brief calls the strongest single input to a build-versus-adopt verdict has actually been
read, and by whom. The brief instructs a reviewer to read it before defending or retiring
an in-house engine; this row cites its existence rather than its contents, and a
build-versus-adopt ADR resting on an unread decisive input should say so on its face.
[cross-review]

**Status.** **Settled as a deferral** in 0.9.0 —
[ADR-0009](adr/0009-thin-governed-layer-position-deferred.md), taking the second of the
two options the cross-review note offered. The position is *not* recorded as convoy's
identity, because the measurement that would license it was designed, reviewed, repaired
and then stopped on cost: a dry-run priced it at $152.00 (16 control cells $32.00, 8
treatment cells $120.00) against a $30 rail and an original $4–16 estimate — about $15 per
cell, since one cell buys a whole governed series where a control cell buys one session.
The ADR records what is known without it, names what would license adopting or rejecting
the position, and answers note (b) plainly: the published orchestration spec has not been
read by anyone. Two consequences land back here. The retire rows below keep standing on
their own evidence rather than on a principle — none of them needs the ADR. And the
weak-tier ablation's 9/10 strengthened-gate figure is **quarantined as unattributable**
(the committed scenario shipped a placeholder probe command; no preimage of its ledger
`config_hash` was found while all fourteen other arms reconstruct exactly), so the
comparison that survives is 3/8 bare against 3/8 with a blind gate — which does not support
the position and is why deferring, rather than hedging, was the honest status.

**Effort** M — a decision, not a build · **Source** [research] + [review] + [cross-review]

### CONV-B28 — Measure the skill itself.

**Cause / evidence.** The published evidence on skill injection is unflattering by default:
the modal skill produces no improvement, the harmful tail is real, software engineering is
the domain where skills help least, and self-authored skills are the worst-performing
category. convoy's skill is unmeasured — no trigger-calibration numbers and no with/without
arm — while the engine underneath it is one of the better-measured things in the corpus.
The skill's negative space ("not for a single quick edit… not for interactive review… not
for deciding what to build") is well-calibrated on inspection, and that is exactly the
property a trigger eval can confirm cheaply. [research]

**Change.** Cheap version: trigger recall and specificity over a small labelled prompt set,
including near-misses. Fuller version: a blind with/without arm on a held-out task. Do this
after CONV-B08, so what is measured is the shortened skill.

**Cross-review.** Gate this row on the collection's row CRAF-B29, or cite it — do not tune
convoy's skill description independently of it. CRAF-B29 owns the same measurement one
level up, and its sealed-holdout data already answers the recall half: that is the part of
the spend proposed here which will not pay. Take the recall number from CRAF-B29 rather
than re-purchasing it, and keep the specificity half and the with/without arm, which is
where this row's own argument points anyway — the negative space is the property that is
cheap to confirm, and the with/without arm is the one thing a sibling's measurement cannot
answer for convoy's own skill. [cross-review]

**Effort** M · **Source** [research] + [cross-review] · **Gate** CRAF-B29

### CONV-B46 — A consumer learns that the stream vocabulary changed by reading the changelog on purpose, and nothing routes the marker that exists.

**Cause / evidence.** The versioned stream contract met its first external consumer and held:
that consumer's parser sync against 0.8.0 found `run_abandoned` — a terminal line a later
`convoy clean` writes for a run whose driver died — unmapped on its side, which would have
scored a killed run as completed. A written spec with a synced test turned that into a
fifteen-minute fix instead of a silent scoring bias, and it is the clearest evidence in the
corpus that the engine-agnostic contract earns its keep. But the discovery was pull-only: the
consumer found it by choosing to read the 0.8.0 changelog during a sync, not from any signal
the stream or the release emits. The `(consumer-affecting)` marker exists and nothing routes
it, which works while there is one attentive consumer and stops working at two. Singleton,
and the immediate risk for the one known consumer is closed — it now pins the 0.8.0
vocabulary with its own test. [triage: 2026-08-11 release and contract sync #1]

**Change.** Held at `watch` pending a second report or a second consumer, whichever comes
first. Two candidate shapes, and the cheap one is probably right: a release-checklist step
that fires on a changed stream vocabulary — name the known consumers, confirm each has
synced — versus emitting a contract-version line consumers can assert on mechanically. The
second is more machinery than one consumer justifies. **CONV-B43(b) is gated on this row**,
because it changes a documented file's contract and would otherwise ship through exactly the
gap described here.

**Status (2026-10-08).** Waits for the next phase: the runner is frozen by [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md).

**Effort** S for the checklist shape · M for a version line · **Source** [triage] · **Status** watch · **Rows** T46a

### CONV-B51 — The manual's two newest behavioural claims have no mechanism pinning them.

**Cause / evidence.** The 2026-08-28 delta pass put two engine behaviours into the manual
(CONV-B49: `resume` re-reads the series file; a driven workspace is unsafe to write to)
as prose only. `tests/test_doc_claims.py` deliberately gates names and counts, not
meaning, so the next change to resume semantics can strand the sentences silently — the
one addition of that wave that fixed an instance while leaving its class ungated.
[cross-project review pass, 2026-08-29]

**Change.** Pin the mechanical half of the claim: drive the stubbed run service across a
series file mutated between two PRs and assert the added check gates the remaining PR
while the integrated PR is not re-gated; cross-reference the test from the SKILL.md
section. First check whether the resume section of `tests/test_headless_driver.py`
already covers the re-gate half — if it does, the build is the cross-reference.

**Status.** **Deferred** by the 2026-08-29 cross-project review pass that minted it —
lower leverage than the guardrail wave built in its place; recorded so the deferral is a
decision rather than an omission.

**Effort** M · **Source** [cross-review]

### CONV-B53 — Partial composition with an external orchestrator has never been measured, so a partial-use decision is made blind.

**Cause / evidence.** Every external measurement in the corpus compared convoy **as a whole
engine** against other whole engines. No arm has ever measured convoy composed *partially*
with an orchestrator that is not convoy — which is exactly the comparison a production
session needed and could not make: it evaluated the package as all-or-nothing, rejected the
runner on its merits, and discarded the gate with it, shipping 11 externally orchestrated
PRs verified only by the agents that implemented them. CONV-B52 removed the reason the
choice was all-or-nothing; nothing yet says which composition is worth paying for.
[triage: 2026-09-01, owner mandate]

**Change.** A measured comparison at the weak tier, where the corpus records headroom and
the causal precedent (blind implementer, gate present: 3/3 reds caught and repaired; gate
absent: 3/3 "broken as done"). Three arms over one task shape, single-factor between each
adjacent pair: (a) probe-direct — an independent oracle wired by hand into a harness gate;
(b) probe-through-convoy — the same oracle content carried by `convoy gate`, isolating the
framework's marginal contribution at equal oracle; (c) agent-driven — the implementing
agent runs `convoy gate` itself in a loop, at the naive arm's oracle, reading adoption
rather than oracle strength. Report the mechanics-only cost (invocation overhead) beside
any quality delta, so plumbing is never mistaken for lift.

**Self-containment.** The measurement harness is not named in this repository (`AGENTS.md`
self-containment). The row states the arms and the metrics; whoever runs it supplies the
instrument.

**The honest-advocate rule this row is run under.** The intent is for convoy to win. The
licensed way to get there is to improve convoy until it wins — arms stay symmetric in
model, effort, prompts and budget, the blind oracle is identical across arms, and a convoy
change made to win ships through this repo's own process (PR, CHANGELOG, tag) and is then
measured as a **new arm**, never as a silent mutation of a running one. An arm convoy loses
is a finding, not a defect in the instrument.

**Status.** **Measured, 2026-09-03** (iteration 1; 128 trials on the 0.11.0 standalone gate,
the v1 bank having been at ceiling). Four arms — control (the project's own suite only), a
ceremony placebo (a gate that reddens once and carries no information), the gate after each
PR with the envelope's `repair_brief` handed to a fix subagent, and the gate once after the
session with a bounded fix loop — at Haiku and Sonnet implementer tiers under a Sonnet
orchestrator, n = 16 per cell, held-out-clean as the primary endpoint, four pre-registered
one-sided contrasts per tier-set with Holm correction, two blind reviewers and an adversarial
verification pass on the readout. **The per-PR gate is supported at both tiers:** 16/16 and
14/16 held-out-clean against control 4/16 and 2/16 and placebo 6/16 and 5/16; the decisive
gate-vs-placebo contrast clears Holm (0.0004, 0.0048) under every sensitivity the review ran,
and the arms are matched on iteration dose (about one gate red and one repair round per
trial in both, though the treatment still runs about one dispatch and 10% of spend more), so
the gain is not the extra iteration. Cost per trial +20% to +25%; cost per correct trial a
third (Haiku) to a sixth (Sonnet) of control's. **The post-session form is not the feature
to sell:** 12/16 and 9/16; it loses significance against control on the main passes alone,
does not beat the placebo once one exposed trial's disposition varies, and ran with an
uncontained gate command. **What the measurement does not show,** by the review's
verdict: the endpoint is one defect class — the type rule the briefs withheld, which the
gate's probes assert with different literals — so the result is the gate restoring a withheld
rule through a repair brief consumed by a fresh subagent, not benefit on work independent of
the rule it teaches; the placebo does not match the repair actor or the brief's content; four
counted trials reached the task directory before a harness repair and are retained with the
sensitivity. The findings, the typed record and the pre-registration with its dated
corrections live with the instrument. Iteration 2 measures the 0.12.0 hook on the same
bank and needs a held-out group with a second defect class before it can claim more. The
doctrine this measurement supports is stated, with these limits, in
`docs/authoring-series.md` §Gate granularity (CONV-B69); this row keeps the measurement.

**Effort** M (the arms exist; the cost is wall-clock and analysis) · **Source** [triage] ·
**Rows** T53a

### Carried-forward watch rows

Anchored, awaiting a second report or a clear trigger. Each stays valid; none has cleared
the promotion gate.

| Row | Substance | Home |
|---|---|---|
| T3a | DAG-aware continuation past a halt (continue PRs whose dependency closure excludes the halted PR). Economics largely subsumed by `--resume`. Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `interface/drivers/headless.py`, `core/dag.py` |
| T4b | Commit-provenance telemetry: agent-authored vs engine-synthesized. **(consumer-affecting)** Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `core/telemetry.py` |
| T5a | Mixed-tier design decision, resolved by ADR-0007. Propagation to the sibling planning tool that emits per-PR tiers is still outstanding; see CONV-B18. | `core/spec.py`, `docs/design/02-formats.md` |
| T6a | `files touched: N (+A/-B)` in per-PR implementation narration — a reasonable cheap addition if narration is ever revisited. Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `interface/reporter.py` |
| T6b | Per-PR integration state in telemetry. Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `core/telemetry.py` |
| T15c | Bounded auto-retry of the branch-setup step before halting (observed environmental `checkout -b` flake). Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `interface/drivers/headless.py` |
| T17 | MAX_PATH detection plus a "scaffold into a shorter directory" hint in `convoy_init`; the `_error_kind` classifier exists and only `_run_impl` uses it. Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `interface/scaffold.py`, `interface/mcp/server.py` |
| T18 | Meter the seat probe as a `role: "preflight"` spawn line, if a consumer ever needs to-the-cent totals. **(consumer-affecting)** Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `core/telemetry.py`, `interface/seat_probe.py` |
| T30c | Name `docs/plans/*` as historical (append-only, not edited by feature work) in AGENTS.md's living-doc set. Singleton. | `AGENTS.md` |
| T34c | An ADR-template line naming the surfaces on which a rationale's named reader actually meets it — ADR-0008 promised an operator an advisory and delivered it on the dry-run envelope only, which cost three releases. Singleton. | `docs/adr/` template |
| T54a | A declared **red window** — a check that must be red until a later PR, by design, with going green early or staying red late as the failure. `phases` displaces which PR a check gates and `blocking = false` makes it permanently advisory; neither expresses "red now, green from PR04". Design-only, no priced instance. **(consumer-affecting)** if built. | `core/spec.py`, `core/gate.py` |
| T54b | Halt for human adjudication and resume with the conversation preserved, rather than a fresh spawn. `resume` re-reads the series file but restarts the spawn. Design-only, singleton. Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `interface/drivers/headless.py` |
| T58c | When `docs/design/02-formats.md` documents a telemetry or schema field, it names what reads it, so the next removal costs a read rather than a grep. Folds into each field's entry, not a new section. Pending a second report outside the authoring and build pair that raised it. | `docs/design/02-formats.md` |
| T59c | A best-effort "a newer release exists" advisory on `--version` and at MCP startup, compared against the newest reachable tag. Never blocks. No incident since it was raised. | `interface/cli.py`, `interface/mcp/__main__.py` |
| T60b | One sentence in the skill's setup section: the seat probe is a point-in-time check, not a lease, so a paid run's seat can expire between a green pre-flight and the first spawn. Displaces the part of §Cost & latency's seat-probe bullet that implies the probe covers the run. Pending a second report from another operator or machine. Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `skills/convoy/SKILL.md` §Setup |
| T61b | Document, for a hand-rolled fan-out, the one thing it needs to copy: a worktree per writing agent, with reviewers read-only in a scratch worktree. Displaces part of the separability preamble in a guide under a word budget. Sibling of CONV-B68; pending a second instance. | `docs/authoring-series.md` |
| T62b | The per-correct-trial framing in §Cost & latency: the gate costs +20% to +25% per trial and a third (weak tier) to a sixth (mid tier) of control's cost per correct trial (CONV-B53). Displaces the stale per-spawn figure. One measured wave; waits on CONV-B53's iteration 2, a paid run. | `skills/convoy/SKILL.md` §Cost & latency |
| T64a | A declared-absent `[branches].base` — nullable with a note, or a documented sentinel — so a series generated for a workspace that does not exist yet is valid and unrunnable rather than valid and wrong. `base` is a required string today. **(consumer-affecting)** if built. Pending a second report or a priced instance. | `core/spec.py` |
| T64b | A schema stamp in `[series]` (for example `schema = "convoy/1"`), written and checked. An engine older than 0.13.0 reading a file that carries `[governance.tier_models]` drops it in silence; 0.13.0's allow-list stops unknown keys from then on, but nothing stamps a file's schema generation. Makes the next skew loud, not the shipped ones. **(consumer-affecting)** if built. A hazard, not an incident. | `core/spec.py` |
| T65a | The schema documentation for `[governance] effort` says the knob is inert for models with no effort dimension, naming the weak tier's floor model as the case a default lineup produces. Singleton, LOW. | `docs/design/02-formats.md`, `skills/convoy/SKILL.md` schema table |
| T66b | An `--allow-dirty` override that records the paths already dirty before the first spawn and keeps them out of every commit the run makes, so a deliberate dirty start never sweeps them. Only if a legitimate dirty-start case appears; CONV-B70 ships the refusal with no override, the smaller shape. Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `interface/git.py::commit_all`, `interface/drivers/headless.py` |
| T68a | Each `prs[]` entry carries `cost_usd`, `num_turns`, `input_tokens` and `output_tokens`, summed over its spawns in the fold that already computes the run totals; co-lands with CONV-B43(c). Today a per-PR economy table needs a second parse of `spawns.jsonl`. **(consumer-affecting)** if built. Singleton, LOW. Waits for the next phase under [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md). | `interface/run_summary.py` |

---

### CONV-B63 — `.convoy/hook.log` grows one line per firing and nothing rotates it.

**Cause / evidence.** Every judge and messenger firing appends a record; the messenger reads
the whole file back to find the judge's verdict. A project that runs the hook for weeks
carries a log the scaffold gitignores and nothing trims. No priced instance yet.

**Change.** A size cap or a per-session file, decided when one real project has run the hook
for a week and the readout says what a useful window is.

**Effort** S · **Source** [review]

### CONV-B64 — Integrating with a host protocol from its documentation instead of its default payload cost a design.

**Cause / evidence.** The hook's first design (PR #75) assumed a synchronous subagent
dispatch because the documentation describes `PostToolUse` around a completed tool call;
the default call shape is asynchronous, which no document says and a five-minute probe with
the default call would have shown. The captured event fixtures under `tests/fixtures/hooks/`
are what made the rewrite (PR #77) a day's work rather than a week's; a probe of the
*default* interaction before the design would have made it no work at all.

**Change.** The authoring doctrine gets the rule for shell surfaces: an integration with a
host protocol starts from a captured payload of the default interaction, committed as a
fixture, before a line of the mechanism is designed — the fixtures directory is the evidence
the rule was followed. `tests/test_manifest.py` asserts `hooks/hooks.json` parses and names
the shipped command, so the plugin's hook wiring is locked the way its version is.

**Status.** Test half shipped in 0.16.0: `tests/test_manifest.py` asserts that
`hooks/hooks.json` parses, wires `convoy hook` on both `SubagentStop` and `PostToolUse`,
and gives every hook the timeout `HOOK_TIMEOUT_SECONDS` names — the number CONV-B61
compares against. The doctrine line is held. It is maintainer doctrine, not series-author
doctrine, so it stays out of the budgeted authoring guide; if it
is wanted, it folds into `docs/GUARDRAILS.md` and names what it displaces.

**Effort** S · **Source** [review] + [report]

### CONV-B65 — Every PR in a build round writes under the same `[Unreleased]` heading, so PRs built in parallel collide in `CHANGELOG.md`, and the workaround moves the cost into merge order.

**Cause / evidence.** Every notable change adds its entry under the one `## [Unreleased]`
heading, and the changelog gate makes an entry certain for any PR touching `src/`, so the
PRs of a build round all edit the same lines. The 2026-09-01 pass held this at `watch` until
the next multi-PR build round. Two have landed since — the gate-only build round and the
hook round (#72–#80) — and the first priced the workaround: avoiding the conflicts meant
stacking one PR on another and fixing the merge order of the whole round, which makes the
stacked PR unreviewable alone and works against one concern per PR. The cost moved from
conflict resolution to merge order; it did not go away. The 2026-09-13 pass moved the row
from `watch` to `proposed` on that replication. [triage: 2026-09-01 gate-only build #4 and
§Friction]

**Change.** Per-PR changelog fragments — `changelog.d/<pr>.md` — assembled into the release
section at the cut, which removes the shared heading. Needs an ADR: it changes where every
contributor records a change, adds an assembly step to the release checklist, and has to
settle what `scripts/changelog_gate.py` accepts as a record, since today it reads the
`CHANGELOG.md` diff. The documentation-only alternative — record that build-round conflicts
in `CHANGELOG.md` are expected and additive — prices the conflict without removing it, and
is a prose append with nothing displaced.

**Status.** Proposed. No `changelog.d/` exists. This row was listed under CONV-B54's
lineage at `watch` until this reconciliation.

**Effort** M, with an ADR · **Source** [triage] · **Row** T55a

## Retire / fold candidates

Each names its replacement. The two conditional rows name the measurement that decides them.

### CONV-B29 — Retire `core/pricing.py`. Replacement: the provider's reported cost, with `cost_estimated` kept as a permanently-false schema field.

**Cause / evidence.** Measured dead: `cost_estimated` was true zero times across 76
production spawns, and a direct check against the installed CLI on a subscription seat
confirms the terminal `result` event carries a real `total_cost_usd`, not `0.0`. The
module's entire premise — that the provider reports zero under subscription auth — no
longer holds. It is also internally inconsistent: the docstring promises a conservative
fallback so an unknown model is over-counted, while `DEFAULT_RATE` is opus-tier (5/25) and
the table's own frontier family is 10/50, so an unknown frontier-priced model is
undercounted 2×. And it is a second unowned price mirror to re-sync on every lineup change.
[review]

**Change.** Delete `core/pricing.py` and `apply_cost_fallback`. Keep `cost_estimated` in
the telemetry schema as permanently false — the schema is a public contract and removing a
key a consumer reads is worse than leaving it. If a zero-cost provider ever reappears, the
right answer is `cost_usd: null` and let the consumer decide, not a price table convoy has
to maintain. Removes two of the four model-mirror sites in one change, with CONV-B14.

**Status.** **Shipped** in 0.13.0, as the row asks. `core/pricing.py` and
`apply_cost_fallback` are deleted and `cost_usd` is always the provider's number;
`cost_estimated` stays in the telemetry schema, permanently `false`
**(consumer-affecting)**. A re-count on 2026-09-05 found it true for 0 of 22 further spawns.
It shipped with ADR-0010, which settled CONV-B14.

**Effort** S · **Source** [review]

### CONV-B30 — Retire the reserved `[review]` lane. Replacement: the deterministic gate (ADR-0002), plus the harness-native review surfaces.

**Cause / evidence.** `[review].blocking`, `[governance.budgets].review` and
`[governance.tools].review` are required-or-parsed fields that no v1 code path reads: an
author must fill placeholders for a spawn role the headless driver never creates, and
`blocking` is documented in four places as reserved-and-inert. ADR-0002 already settled
that the deterministic gate is the sole merge arbiter and that an LLM verdict cannot be
audited, so the lane is reserved for something the project has decided against. The ground
has also moved: review, security-review and fresh-context review panels now ship natively
and do LLM review better than convoy would ever justify building. This is the only place
convoy overlaps something the harness does better. [review; research]

**Change.** Make the three fields optional-and-ignored, document them as removed rather
than reserved, delete the `'review'` branch from `_ROLES`/`resolve_spawn`, and close the
lane in a short ADR citing ADR-0002 and the native surfaces. Every series file in existence
gets shorter and one confusing paragraph leaves the skill. Drop `review` from the required
trio in `[governance.tools]` at the same time. **(consumer-affecting: required keys become
optional)**

**Status (2026-10-08).** Excepted from the runner freeze of [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md): it retires part of the runner.

**Effort** M · **Source** [review] + [research]

### CONV-B31 — Fold `--fresh` into `convoy clean`. Replacement: `clean` then `run`, or `--fresh` reusing clean's tree-restoring steps.

**Cause / evidence.** Two destructive paths with overlapping names and a gap between them.
`--fresh` touches branches only, while by convoy's own documentation a `budget` or
`infrastructure` halt returns *before* the truncated spawn's work is committed — so it
leaves exactly the uncommitted changes and untracked files `--fresh` cannot remove and that
can abort its own checkout. The documented recovery is therefore "run `clean` by hand, then
run `--fresh`", which means the flag does not do what its name implies in the case that
most needs it. Budget halts were 20% of terminal runs, so this is the common path, not the
corner. [review]

**Change.** Either have `--fresh` reuse `clean`'s tree-restoring steps before deleting
branches, or remove `--fresh` in favour of `clean && run`, with `run` failing on a leftover
branch and naming `clean` in the message. One destructive path, one mental model.

**Status.** **Shipped** in 0.8.0, taking the first of the two options: `--fresh`
reuses `clean`'s tree-restoring steps before deleting branches. The flag was kept rather
than removed — `clean` still owns restoring a workspace *without* starting a run (no lock,
no seat probe, and it closes the killed run's ledger entry), which is a different job. The
escalation is stated plainly rather than smuggled: `--fresh` now discards uncommitted work,
and with the flag off nothing in the tree is touched.

**Effort** M · **Source** [review]

### CONV-B32 — Demote the independent-check lane. Keep the mechanism; retire its prominence. Replacement: one usage condition plus the measured table.

**Cause / evidence.** convoy is already the most honest source on this feature and the
production data closes the argument. `docs/design/01-gate.md` reports the in-house trial
plainly: the lane fires at the weak tier with a blind implementer (3/3 red, 3 fix spawns),
is **null at the strong tier** (0/3 red, no fix spawn), and is redundant when the
acceptance tests are visible in the workspace. The field confirms it: exactly one series
ever declared `independent = true`, its two out-of-tree oracles ran 14 times and went red
**zero** times, `independent_red` is 0 across all 73 gates, and 75 of 76 spawns ran at the
strong tier — the tier where convoy's own experiment says the lane does nothing. The
mechanism is cheap and correctly fail-closed, and the docs are candid that asset isolation
is a leaky proxy for epistemic independence. The problem is prominence: it is the scaffold's
headline check, it owns a design-doc section, and it carries a large share of the skill.
[review; triage]

**Change.** Take it out of the starter template's blocking check (CONV-B11), compress the
`01-gate.md` independence section to the usage condition plus the measured table, and state
the condition where an author actually meets it — an independent check adds correctness only
when the implementer cannot see the acceptance criteria it is judged against. Carry the
caveat that `independent = true` asserts implementer-unreachability, not oracle correctness,
into CONV-B08's reference.

**Effort** S · **Source** [review] + [triage]

### CONV-B33 — Retire the per-model seat-probe fan-out and the `effective_model` folding, if CONV-B18 measures near-zero use. Replacement: series-level `[governance]` resolution, with per-PR parser support kept.

**Cause / evidence.** One divergent spawn in 76. The parser support costs little and can
stay; the fan-out, the pre-flight complexity and the folding exist only to serve it. Gated
on the measurement, not on the argument — the feature superseded an ADR on production
evidence and should not be unwound on a single window. [review]

**Status (2026-10-08).** Excepted from the runner freeze of [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md): it retires part of the runner.

**Effort** M · **Source** [review] · **Gate** CONV-B18

### CONV-B34 — Replace the credential-copy isolation with native flags, if CONV-B19 finds a matching arm. Replacement: `--setting-sources` plus `--strict-mcp-config`; keep `_ENV_STRIP` either way.

**Cause / evidence.** The isolation goal is sound and measured (about 35k input tokens of
operator toolkit load before a bare prompt does anything). The implementation depends on a
private, undocumented credentials file name. If an arm authenticates, keeps operator
hooks/plugins/skills out, and still loads the workspace's own CLAUDE.md, the copy can go.
[review; research]

**Status (2026-10-08).** Excepted from the runner freeze of [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md): it retires part of the runner.

**Effort** M · **Source** [review] + [research] · **Gate** CONV-B19

### CONV-B35 — Evaluate replacing the hand-rolled stream parser with native background agents or structured output. Replacement: the harness's own background-agent JSON or schema-constrained output, if either can carry the invariants.

**Cause / evidence.** This is the layer most exposed to native displacement: background
agents, structured output and per-agent budgets are all first-class now. Four invariants
are hard-won and must survive any replacement — whole-process-tree kill so a timeout does
not orphan tool grandchildren into the scored tree, partial-stream economy recovery,
folding cache-read and cache-creation tokens into the input count so a cache-heavy run is
not undercounted, and the environment strip against billing and routing overrides. Do
CONV-B07 first regardless: it is a correctness fix on the parser convoy has today and it is
cheap. [review; research]

**Cross-review.** The same external consumer named under CONV-B10 applies here, and it
makes this a fifth invariant rather than a footnote: a sibling evaluation harness runs
convoy as a scored arm, reading the run envelope and holding its own copy of the engine
contract spec, so replacing the parser is a contract question for a program outside this
repository and not only an internal re-plumbing. Either carry "the envelope's shape
survives the replacement" as an explicit invariant alongside the four above, or schedule
the work after that harness's row FATH-B36 settles whether the consumer still exists —
the one thing not to do is discover the answer from a broken scored arm. [cross-review]

**Status (2026-10-08).** Excepted from the runner freeze of [ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md): it retires part of the runner.

**Effort** L · **Source** [review] + [research] + [cross-review]

---

## Shipped

### Built in the 2026-10-08 follow-up (unreleased; served by the next tag)

Built from the owner's written decisions of 2026-10-08, on one branch per concern.

| Row | Promotion | Shipped by |
|---|---|---|
| CONV-B14 (lineup 5.5) | The floor lineup moved to the 5.5 models: `DEFAULT_TIER_MODELS` resolves `weak` to `claude-haiku-5-5` and `mid` to `claude-sonnet-5-5` (`strong` and `frontier` unchanged), stamped `LINEUP_RECONCILED = '2026-10-08'`, because `claude-haiku-4-5` and `claude-sonnet-5` are listed as legacy by the platform model page. The `convoy init` starter model is `claude-haiku-5-5` and the formats doc's example series follows. `tests/test_governance.py` and `tests/test_scaffold.py` pin the new values. A series that reaches the floor for `weak` or `mid` now runs a different model; an explicit `model` or a series `[governance.tier_models]` is unaffected. | unreleased |
| CONV-B76 | ADR-0011 accepted: the runner is frozen and the gate is the product ([ADR-0011](adr/0011-the-runner-is-frozen-the-gate-is-the-product.md)). The runner takes only security fixes, fixes for defects that corrupt data or a workspace, and rows that retire parts of it; a floor model id the platform retires is such a defect. The gate recipe lives in a native Workflow, with `convoy gate` armed by a hash-pinned `.convoy/gate.toml` as one possible judge; the private-names sweep belongs in CI (not built: it needs the list as a repository secret); the US$152 runner measurement is declined for good. The runner is retired only after an end-to-end run in which the judge fires for Workflow agents; the 2026-10-08 probe is not that run. The freeze is text only, with no CI check. Fifteen waiting rows and eleven watch rows carry a status line pointing at the ADR; the six measure-then-retire rows (CONV-B18, CONV-B19, CONV-B30, CONV-B33, CONV-B34, CONV-B35) carry one saying they are excepted. ADR-0009 points at it, and `AGENTS.md`, `README.md` and `skills/convoy/SKILL.md` say which half is developed. Docs only. | unreleased |

### Built in the 2026-10-08 round (served by 0.17.0)

Built from the 2026-10-07 review rather than from a triage pass, on one branch per row.

| Row | Promotion | Shipped by |
|---|---|---|
| CONV-B72 | The plugin hook exits early when no gate can be found. Cause: `hooks/hooks.json` started `uv run --project ... convoy hook` on every `SubagentStop` and every `Agent`/`Task` `PostToolUse`, so every installing session paid uv's environment check, an interpreter and the whole CLI import per firing, although the hook does nothing without a trusted `.convoy/gate.toml`. Change: both handlers run `src/convoy/interface/hook_guard.py` first (standard library only, `uv run --frozen --no-sync`, still shell form), which exits 0 without starting `convoy` when no spec is found or its project is untrusted, and delegates everything else to `convoy hook` with the same stdin. `tests/test_hook_guard.py` holds every skip against `hook.decide`. No-gate firing over five back-to-back pairs on one Windows 11 machine (10 runs each after one warm-up): median 173-233 ms after, 501-687 ms at v0.16.1 (`scripts/hook_latency.py`). | 0.17.0 |
| CONV-B73 (T67a) | The run result records the remote refs and PRs a spawn created. A pure scanner (`core/external_writes.py`) reads each spawn's own stream-json — the `tool_use` blocks whose `input.command` is a string, paired by id with their `tool_result` — and reports `git ... push` (`git_push`), `gh pr create` (`gh_pr_create`) and a writing `gh` verb against a repository named with `-R` / `--repo` (`gh_repo_write`), each as `{kind, command, target, failed}`. The driver scans every implementation and fix spawn and writes the findings on its `spawn_complete` line as `external_writes`; the result envelope lifts them to a top-level `external_writes` list with `pr_id`, `role` and `attempt`, and adds one `external_write` advisory per finding after the pre-flight ones; the run prints one stderr line per finding and `convoy status` shows a count. Report, not enforce: no outcome, exit code or integration changes. It cannot see a push made by a script the agent ran. **(consumer-affecting: a new telemetry field, a new envelope field, a new advisory kind)** | 0.17.0 |
| CONV-B14 (skill half) | `skills/convoy/SKILL.md` names no model id: the resolution-order bullet says "an explicit `model` (an API model id)" and points at `convoy validate` / `dry_run`, the `lineup` advisory and `effective_model`; the example series uses `tier = "weak"`; the cost figure keeps its provenance as the `weak` tier at v0.1.0. `tests/test_doc_claims.py::test_the_skill_names_no_model_id` fails if an id returns. The skill's advisory paragraph also lists the `lineup` kind and the two producers it had omitted. Two mirror sites remain (`core/governance.py`, `interface/scaffold.py`); the README's example series is introduced as a close variant of the `convoy init` output until the scaffold half lands. | 0.17.0 |
| CONV-B74 | A dated note, `docs/notes/2026-10-08-subagentstop-under-workflow.md`, records how the hook behaves under the Workflow tool: `SubagentStop` fires for its agents with and without worktree isolation (`agent_type` `workflow-subagent`); the judge found the project spec at `$CLAUDE_PROJECT_DIR/.convoy/gate.toml` and ran the gate in the session project root for both, so a worktree-isolated agent was judged against the main checkout; the messenger leg left no record. `docs/notes/` is new (append-only, dated). Docs only. The finding it produced is CONV-B75, proposed. | 0.17.0 |

### Built in the 2026-10-06 maintenance round (served by 0.16.0)

Built on the 2026-10-06 maintenance branch from the open rows of the 2026-10-06 triage and
served by the 0.16.0 release tagged v0.16.0. CONV-B70 is **(consumer-affecting)**, so by
release step 0 in `CONTRIBUTING.md` the cut to 0.16.0 is a minor. The same tag serves the
`strong`-tier floor moving to `claude-opus-5-5` (see CONV-B14) and the isolation fix of PR #109
(a scored spawn no longer reads the operator's own CLAUDE.md from above its working
directory), not rows.

| Row | Promotion | Shipped by |
|---|---|---|
| CONV-B70 (T66a) | A run refuses to start on a working tree with uncommitted changes. A run commits each PR with `git add -A`, so a modified tracked file, a staged file or an untracked file the repository does not ignore went into the first PR's commit. The start pre-flight now reads `git status --porcelain` and raises a `workspace` problem naming up to three paths and counting the rest: `convoy run` exits 3 and `convoy_run` answers `outcome: "usage"`. `reset` / `--fresh` skips it, since it discards those changes; a workspace that is not a repository is not read; there is no override flag (T66b, watch). Under `resume` the message names the tree-only cleanup `git reset --hard` and then `git clean -fd` (two commands: PowerShell 5.1 does not parse `&&`), which keeps every branch and every ignored file — never `convoy clean`, which deletes the integration branch the resume continues from — and the `dead` message gains that step between `convoy unlock` and `--resume`. `convoy_run` with `dry_run: true` now runs the same start pre-flight, so it also reports the problems of the `reset` / `resume` options as passed. **(consumer-affecting: runs that used to start now refuse; a new problem kind; a changed `dead` message)** | 0.16.0 |
| CONV-B17 (T37a) | All six verbs that take the series file positionally answer `--series` and `--series-file` with a usage error (exit 2, unchanged) naming `convoy <verb> <series.toml>`, instead of Click's bare "No such option". | 0.16.0 |
| CONV-B62 (T61c) | Hook firings that gate one tree take turns on `.convoy/judge.lock`, and every log append holds `.convoy/hook.log.lock`; a firing that waits out its bound (at most 600 s, and short enough that the wait plus its gate's worst case fits the hook timeout; at least 270 s for a gate inside CONV-B61's budget) exits 2 like a gate that could not run, recorded as `busy`, and a lock naming a process that is gone, or none for ten seconds, is taken over. A lock still held on the judge's retry lets the subagent stop, recorded as `busy` with its own reason. **(consumer-affecting: a new `hook.log` outcome, `busy`)** The row's Change now names the second remedy: concurrent writers need a worktree each, which no lock gives. | 0.16.0 |
| CONV-B61 | `HOOK_TIMEOUT_SECONDS` (1800) is a package constant, and a gate's worst case may use `GATE_BUDGET_SECONDS` (1500) of it, leaving 30 s for the hook and at least 270 s for a firing waiting on the judge lock; `convoy gate --init` lowers `timeout_seconds` until the scaffolded checks fit the budget, and `convoy validate` on a gate-only file warns on stderr when checks × `timeout_seconds` exceeds it. | 0.16.0 |
| CONV-B64 (test half) | `tests/test_manifest.py` pins `hooks/hooks.json`: it parses, wires `convoy hook` on both events, and carries the timeout `HOOK_TIMEOUT_SECONDS` names. The doctrine line is held. | 0.16.0 |
| CONV-B09 (a) (T71a) | `CONTRIBUTING.md` §Release discipline states both install paths — an install takes the default branch's tip, an existing install refreshes only on a version change — in place of the one-path rationale. Supersedes T34a's wording. | 0.16.0 |
| CONV-B66 (T57b) | `docs/GUARDRAILS.md`'s hook-trust rule names the autouse fixture `_no_real_convoy_home` in its *Enforced by:* line. The fixture existed; its attestation did not, and the failure it prevents was real: three `--init` tests had written live trust entries into a developer's real `~/.convoy/hook-trust.toml`. | 0.16.0 |
| CONV-B67 (T58b) | Release checklist step 1a: the release section's framing paragraph is written at cut time, once its contents are final, and is never carried under `[Unreleased]`. Removes the class (a framing sentence that went false as later entries landed under it) where a gate on one phrase would catch one instance. | 0.16.0 |
| CONV-B69 (T62a) | The smallest-unit gate doctrine — run the gate at the smallest unit the workflow has; a repair brief that names one PR's reds beats one that names several — moves out of CONV-B53's Status into `docs/authoring-series.md` §Gate granularity with its limits (one measured wave, one defect class, iteration 2 pending). A relocation that asserts nothing the repository did not already assert; the figures stay in CONV-B53. | 0.16.0 |
| CONV-B71 (T70a) | This reconciliation: the ledger re-read against the 2026-10-06 and 2026-09-13 triage passes and the 0.13.0–0.15.0 CHANGELOG sections. CONV-B14 and CONV-B29 re-statused, the 0.13.0 and 0.14.0 sections added, CONV-B65 to CONV-B71 minted, the watch table and the row-ID map extended. Docs only. | 0.16.0 |

**Why CONV-B70 was built on one report.** In the 2026-09-26 run an untracked file of
private strings sat in the workspace root and would have entered the first PR's commit; a
reviewer's chance `git status` caught it. One report, rated HIGH, promoted as a stated
singleton so a later pass can overturn it: the near-miss was on private data, nothing but
chance stood between the file and the commit, the cause is reachable at the pre-flight layer
that already refuses the run's own writes (`check_outputs` refuses an outputs directory
inside the workspace), and the change is a refusal, not new behaviour inside a run. The
resume half is what keeps it safe to ship: a `budget` or `infrastructure` halt returns before
the truncated spawn's work is committed, so a tree is dirty after the common halt, and a
refusal that pointed at `convoy clean` would have destroyed the branch `--resume` needs.

**What CONV-B70 left open.** Two things, recorded here so neither is lost. The first is still open:
`convoy_run` with `dry_run: true` is the only rehearsal of the refusal. The CLI has no
`run --dry-run`, and `convoy validate` stays tree-blind on purpose: it takes no `--fresh` or
`--resume`, so it cannot know whether the run it precedes reads the tree at all (`--fresh`
skips the check) or which remedy applies (`--resume` names a different one), and its answer
is about the series file and the paths it names. A CLI user who gets `ok` from validate can
still get exit 3 from `convoy run` on a dirty tree; `git status --porcelain` in the workspace
is the rehearsal. The second is done: `docs/design/03-serving.md` said that `convoy validate`
and the tool's `dry_run` both call `preflight`, and its verb table called them the same
pre-flight. They differ: `dry_run` calls `start_report`, which adds the tree read and the option
checks like the run's own start pre-flight, while `convoy validate` calls only `preflight` and
stays tree-blind. The sentence, the run lifecycle's pre-flight stage and the verb table row were
corrected in the docs pass after 0.16.0.

### Served by 0.15.0 (2026-09-13): no row, and the install requirement versioned

0.15.0 built no ledger row. It moved the MCP server to mcp 2.x (`mcp>=2.2.0,<3`): mcp 2.0
removed the module `FastMCP` lived in, so a fresh resolve of the old `>=1.28.1` floor built a
convoy whose serving surface could not import. The four tools' descriptors and envelopes,
dumped under mcp 1.28.1 and 2.2.0, are byte-identical, so by the emitted-surface test alone
the release was a patch. It was cut as a minor under a rule it added to
`docs/design/02-formats.md`: what convoy requires of the environment it is installed into is
versioned too, and a dependency's major version or a swap in the runtime closure is a minor
even when every envelope is unchanged. Release step 0 in `CONTRIBUTING.md` states only the
`(consumer-affecting)` test; the install-requirement test lives in `02-formats.md`, which
step 0 cites.

### Built in the 2026-09-13 delta pass (served by 0.14.0)

The 2026-09-13 triage pass read 13 reports. The four that sourced this round found no bad PR
reaching integration; what had drifted was what convoy says about itself. The clearest
instance: a dead run's recovery
message recommended `convoy clean`, the one command that deletes the branches `--resume`
needs. The rows it promoted and built in the same round:

| Row | Promotion | Shipped by |
|---|---|---|
| CONV-B42 (T56a, T56b) | `convoy unlock <series.toml>` releases a stale run lock and nothing else, closes the killed run's ledger entry with `run_abandoned`, and refuses while the lock's owner is alive unless `--force`; the `dead` message names it instead of `clean`, whose two clauses could not both hold. **(consumer-affecting: a new verb)** | 0.14.0 |
| T59a | `convoy_run` and `convoy_status` envelopes carry `convoy_version`, as the gate envelope already did, so a run's engine is reconstructible from its own artefact. **(consumer-affecting)** | 0.14.0 |
| T59b | `skills/convoy/SKILL.md` states its own version, locked to `.claude-plugin/plugin.json` by `test_versions_are_locked`, so a served-versus-installed skew costs a glance. | 0.14.0 |
| CONV-B41 (T60a, in part) | The seat probe reads the on-disk credential's `expiresAt` and `refreshTokenExpiresAt` (never the token) before spending a spawn, and names the state: re-authenticate, or log in again. The rest of CONV-B41 is open. | 0.14.0 |
| T58a | `scripts/changelog_gate.py --explain` prints the watched prefixes, the trailer opt-out and the merge policy from the constants, and a test checks the prefixes against `CONTRIBUTING.md` in both directions. | 0.14.0 |
| T57a | `docs/GUARDRAILS.md`'s test-doctrine rule: a fail-closed guard's tests assert the wrong-answer case rather than the degenerate one, a "these two surfaces agree" test invokes both, and a fixture cited as proof of a boundary sits on the hard side of it. One rule for three failure modes, not one append per finding. | 0.14.0 |

### Built in the 2026-09-05 lineup round (served by 0.13.0)

Not a triage pass: a design and build round over convoy's dependency on a model lineup it
does not own, recorded as ADR-0010. It settled CONV-B14 by a different shape from the one
the row asked for, and shipped CONV-B29 with it. The 2026-09-13 pass confirmed both against
the source.

| Row | Promotion | Shipped by |
|---|---|---|
| CONV-B14 | Settled by ADR-0010. `[governance.tier_models]` lets a series carry its own tier table **(consumer-affecting)**; `DEFAULT_TIER_MODELS` is the documented floor, stamped `LINEUP_RECONCILED`; a tier resolved through the floor raises `Advisory(kind='lineup')`; `implementation_model_sources` reports an origin (`explicit` / `series-table` / `floor`). No age tripwire. | 0.13.0 |
| CONV-B29 | `core/pricing.py` and `apply_cost_fallback` deleted; `cost_estimated` kept in the schema, permanently `false`. **(consumer-affecting)** | 0.13.0 |
| — | `[governance]` rejects an unknown key and names the near-miss, so a series written for a newer convoy fails at load instead of running every PR on the floor — ADR-0010's precondition. **(consumer-affecting)** | 0.13.0 |
| — | The changelog gate judges record-or-declare per commit rather than per range, refuses a `CHANGELOG.md` diff that adds no real line, and charges a merge commit with its conflict resolution only. | 0.13.0 |

### Built in the 2026-09-02 hook round (served by 0.12.0)

Five rows minted from the program-2 design and shipped in one day across PRs #72–#80, with
two blind reviews between the last feature PR and the cut. The reviews' 31 findings closed
in #79; the residuals are CONV-B60 through CONV-B63 above.

| Row | Promotion | Shipped by |
|---|---|---|
| CONV-B55 | The gate as a Claude Code hook. `convoy hook` runs the project gate on two events: `SubagentStop` is the judge (a blocking red is handed to the subagent as the reason it may not stop yet, one repair round, read-only subagents skipped) and `PostToolUse` on `Agent` is the messenger for synchronous dispatch (a residual red reaches the orchestrator as feedback, reusing the judge's verdict). The plugin ships both hooks. Attestation: one JSON line per firing in `.convoy/hook.log`. **(consumer-affecting)** | 0.12.0 |
| CONV-B56 | A project carries its own gate. `.convoy/gate.toml` is the per-project spec — scaffolded by `convoy gate --init` from the toolchain it finds (a red placeholder when it finds none), an independent oracle by `--independent`, discovered by `convoy gate` and `convoy_gate` with no argument — and executed by the hooks only where the machine trusted it with `convoy gate --trust`, which pins the spec's hash; an untrusted project executes nothing and gets no file, a changed spec is refused loudly. **(consumer-affecting)** | 0.12.0 |
| CONV-B57 | Held-out oracles live out-of-tree by convention: `${CONVOY_*}` expands in `[[checks]]` `run` and `asset` at load (`CONVOY_ORACLES` the conventional home), an unset name or a value carrying shell syntax is refused, and the authoring guide states the doctrine — the judge is appointed before the defendant. **(consumer-affecting)** | 0.12.0 |
| CONV-B58 | The compact envelope: `convoy gate --brief` / `convoy_gate(brief=true)` return `{ok, outcome, repair_brief, convoy_version}` for a caller that reads the verdict inside a model turn. **(consumer-affecting)** | 0.12.0 |
| CONV-B59 | A harness keeps the gate outside the tree it judges: `$CONVOY_GATE_SPEC` names the spec, `CONVOY_TRUSTED_ROOTS` vouches for the staged workspace, and the spec found outside `.convoy/` governs the workspace for trust, the log and the oracles default. **(consumer-affecting)** | 0.12.0 |

### Built in the 2026-09-01 delta pass (served by 0.10.0)

The pass minted CONV-B52 and CONV-B54 and closed both in the same round, plus the two
guardrail rows the 2026-08-29 build had left at `[Unreleased]` (CONV-B13, CONV-B15).
CONV-B52 is the only BLOCKER this corpus has carried, and it needed no new gate
semantics — the primitive existed with one production call site, so the row was wiring
and doctrine.

| Row | Promotion | Shipped by |
|---|---|---|
| CONV-B52 | The gate is reachable without the run. `convoy gate` (CLI) and `convoy_gate` (MCP) run a series' `[[checks]]` against a workspace once — same runner, same fail-closed independence guard, same verdict rules — with no spawn, branch, merge, lock or telemetry, both surfaces emitting one envelope from one fold (`interface/gate_service.py`) including the failure paths. Four invocations that cannot answer are refused as `usage` rather than answered green or red: an unknown phase tag, a selection with no blocking check, an empty selection, and unbacked isolation on a blocking independent check. `load_gate_spec` accepts a full series.toml or a minimal `[series] id` + `[[checks]]` file. **(consumer-affecting)** | 0.10.0 |
| CONV-B52 (doctrine half) | The skill's trigger names two separately-dispatched capabilities instead of one package — the framing under which a production dispatch decision rejected the runner and discarded the gate with it (11 PRs, judge = defendant). `docs/authoring-series.md` seeded with the separability doctrine and the one-PR-series pattern, under a word budget set at its birth. Folded into CONV-B08's home rather than growing SKILL.md. | 0.10.0 |
| CONV-B54 | CHANGELOG discipline asserts shape, not only values: the changelog gate fails an added `### ` heading outside the Keep a Changelog vocabulary, and the release checklist opens with a step 0 making the patch-vs-minor call mechanical (any `(consumer-affecting)` entry ⇒ minor), citing the enumeration it was previously silent about. | 0.10.0 |
| CONV-B13 | The no-real-spawn guardrail became a mechanism: an autouse `tests/conftest.py` guard raises on a `HeadlessSpawn` left on the default `claude` binary. | 0.10.0 |
| CONV-B15 | The commit-time lane, in the `core.hooksPath` script form (the bare `pre-commit` shim never runs on this machine), pinned to `ci.yml`'s command set and order by `test_doc_claims.py`. | 0.10.0 |

**What CONV-B52 cost to get right.** The first implementation passed the full gate, the
doc-claims suite and a red-green TDD pass, and still shipped four defects that two
fresh-context adversarial reviewers found before merge: a typo'd `--phase` tag reported
**green** with the named check never run; an uncaught `OSError` exited 1, which is
`EXIT_BLOCKED`; the MCP tool raised instead of returning an envelope on the most likely
caller mistake; and an unbacked isolation asset was reported as a red carrying
`independent_red`, the signal an auto-repair loop keys on. One cause: the fail-closed
guard tested *cardinality* (is the selection empty?) rather than the *question the caller
asked*. Recorded because the corpus now has a clean instance of what the deterministic
gate cannot reach — intent — on the round that made the gate a product surface.

### Built in the 2026-08-28 delta pass (served by 0.9.1)

Four rows minted and closed in the same pass — each was small, each had its evidence
already, and none needed a design decision first. They are listed here rather than as open
rows because there is nothing left to build. Retargeted at the tag that serves them when
0.9.1 was cut — none of it reached an installed consumer until then, which is the whole
reason the status names a tag rather than a branch state.

| Row | Promotion | Shipped by |
|---|---|---|
| CONV-B45 | The skill's trigger stated as the **pre-condition** — a plan, spec or PR manifest already naming two or more PR-sized changes — instead of "when running a convoy series.toml", which is a condition only true after someone has chosen convoy. Both the tool-first opener and the self-referential trigger are displaced, not appended to. | 0.9.1 |
| CONV-B47 | The uncovered-test advisory skips the files the workspace's own ignore rules exclude (`git check-ignore`) and names directories once the list is too long to read. Two workspaces had turned it into 526 and 474 lines of noise. Silent fallback where there is no repository or no `git`. | 0.9.1 |
| CONV-B48 | `CONTRIBUTING.md` and the PR template list every command CI runs, in CI's order — they listed four of six and called it "the same set", omitting `uv lock --check`. `tests/test_doc_claims.py` now reads the workflow and fails on a documented gate that drops a step or reorders one. Fourth recurrence of that class; the first three fixes were prose. | 0.9.1 |
| CONV-B50 | `GitError` read git's stderr and, finding it empty, substituted `exited 1` — while the diagnosis for the commonest of these failures (`git commit` with nothing staged) is on **stdout**. The docstring named that exact case and the code discarded it. Now the stderr tail, then the stdout tail, then the exit code. Same stream-precedence defect as CONV-B03, in the engine's own subprocess calls rather than the gate's. | 0.9.1 |
| CONV-B49 | Two engine behaviours the manual was silent about: mid-series gate repair (`resume` re-reads the series file, so checks edited at a PR boundary govern the remaining PRs while integrated ones are skipped), and that writing to a driven workspace is unsafe because the engine moves `HEAD` between branches. | 0.9.1 |

**Why CONV-B45 was a trigger rewrite and not a removal.** The measurement alone is
ambiguous: a periodic post-hoc telemetry pass over agent transcripts for 2026-06-26..08-25
recorded convoy reached in 16 of 129 sessions, with 271 engine invocations against 3 skill
entries. That gap reads either as a trigger that does not fire or as a skill the operator
routes around. The corpus settles it: more than half the feedback reports cite the skill
document as what a series was authored from — including one that authored a correct,
first-try series from it alone on a machine that had never run convoy — and every session in
the corpus that actually drove a governed series went through the MCP surface, while the
CLI-heavy sessions are maintainer and measurement work inside this repository, which needs no
manual. A redundant skill would show the inverse. The content is load-bearing and the
trigger was not reaching it.


### Since the last reconciliation (0.2.0 – 0.8.0)

Reconciled against the campaign window; each row is closed on production evidence, not on
the merge alone.

| Row | Promotion | Shipped by |
|---|---|---|
| T19a | Phase-scoped `[[checks]]` with a non-blocking advisory channel; ADR-0008. Without it an incremental series is effectively unrunnable, because a full-suite gate is red until the last PR. Three of six declared checks in production are phase-scoped. **(consumer-affecting)** | 0.3.0 |
| — | `docs/design/01-gate.md` citing the in-house blind-implementer measurement, including the null result at the strong tier | 0.3.0 |
| T5a | Per-PR `model`/`tier`/`effort` with `effective_model` in the envelope; ADR-0007 supersedes ADR-0005 | 0.2.0 |
| T10a | `convoy clean <series.toml>` with `--dry-run`; manual recovery was needed about five times in one campaign | 0.4.0 |
| T11a | `--resume`: strict-ancestor containment, distinct skip reasons, `resume`+`fresh` refused at pre-flight. 16 PRs across the corpus recorded as already integrated — 16 implementation spawns not re-purchased at a median $8.79. **(consumer-affecting)** | 0.4.0 |
| T16a | `--workspace <dir>` on `run`/`validate` | 0.4.0 |
| T12b | Self-describing budget halt: halted PR, phase and spend-vs-cap on the terminal record. **(consumer-affecting)** | 0.5.0 |
| T13a | Gate-check env sanitization stripping `VIRTUAL_ENV` and uv siblings; the warning does not recur in any later report | 0.5.0 |
| T14b | `convoy status` / `convoy_status`, holding no server state. **(consumer-affecting)** | 0.5.0 |
| T20a | `convoy run --json`, emitting the same envelope from the same fold as the MCP surface. **(consumer-affecting)** | 0.5.0 |
| T14c | `convoy_run(detach=true)`: the child is convoy's own CLI under `--json`, the parent pins the `run_id`, the child records its own verdict. **(consumer-affecting)** | 0.6.0 |
| T15a | Subcommand context on `GitError` at the `_run_checked` choke point | 0.6.0 |
| T4a | Real commit subjects on the residual sweep | 0.6.0 |
| T21a | Seat-probe diagnosis extracted at the source, as `SpawnResult.diagnosis` | 0.7.0 |
| T24a | Release-tag workflow, scheduled rather than push-triggered, checking tag and release page separately | 0.7.0 |
| T25a | Advisories carried on the `run_start` line, so one mechanism serves the reporter, both envelopes and `convoy_status`. **(consumer-affecting)** | 0.7.0 |
| T26a | Advisory naming which flag an inert `[[checks]].asset` is missing | 0.8.0 |
| — | README MCP tool count corrected | PR #48 |
| — | `--durations` guidance in GUARDRAILS.md | — |

### Served by the 0.1.2 tag (2026-07-09)

| Row | Promotion | Shipped by |
|---|---|---|
| T9a | Cut 0.1.2 and re-tag the plugin so an install serves the fixed engine | release 0.1.2 |
| T1a–c | UTF-8 pinned at every text boundary, with regression tests and entry-point streams | PR #11 |
| T2a | `output_tail` on non-ok `spawn_complete` lines | PR #14 |
| T2b | Seat probe before staging | PR #14 |
| T3b | Truthful skip reason | PR #13 |
| T8a | Per-check `repair_hint` briefed to the fix spawn | PR #12 |
| T7a | "Adopting convoy in an existing project" section | PR #16 |
| T7b | Deliberate non-features documented | PR #16 |
| T9b | Release discipline in contributor docs | PR #16 |
| T12a | Budget-calibration guidance | PR #16 |
| T14a | Long-run pattern documented (CLI in a background shell) | PR #16 |

---

## Declined

Recorded with reasons so they are not relitigated.

- **Retiring convoy in favour of native orchestration.** The independent review and the
  landscape brief agree that the mechanical layer — spawning, fan-out, per-agent model and
  effort, worktree isolation, a session budget, resume, structured returns — is now
  commodity. They also agree on the residue: no native surface offers a deterministic
  shell-command gate as the sole merge arbiter, a bounded repair loop re-briefed with the
  failing check's own output, branch-per-PR integration with resume-by-ancestry, or an
  append-only per-spawn economy ledger a third process can read. Production supports the
  residue rather than the wrapper: the gate rejected a "done" claim five times in 73 events
  with every red repaired, and the per-role cap halted two of ten terminal runs. The move
  is to shrink toward that residue — CONV-B27 and the retire list — not to retire the tool.
- **MCP progress notifications per spawn or gate event**, to keep a long run inside a
  host's idle window. The underlying cause — a blocking call that cannot outlive the
  caller's idle timeout or a session restart — was closed by `convoy_status` (0.5.0) and
  `detach` (0.6.0), and confirmed closed in production three weeks later. A second
  mechanism for a solved problem is a surface to maintain for no remaining yield.
- **A documented salvage recipe for re-running only the tail after a mid-series halt.**
  Superseded rather than declined on merit: `--resume` replaced the procedure it would have
  described. The residual documentation need is CONV-B04.
- **Series sizing against mid-wave design drift.** A decision taken while a later PR is in
  flight cannot reach an already-integrated one. Nothing the engine can do; the observed
  recovery was a post-wave refactor at zero spawn cost. Recorded as calibration for wave
  sizing, not a defect.
- **Fix budget drawn from the series budget** — superseded by validated recalibration, and
  it weakens the runaway backstop.
- **`SpawnResult.output` as a structured stderr accessor** — a low-severity singleton,
  acceptable as-is; revisit only if a structured consumer appears.
- **Stale-lock auto-reclaim (T10b).** Superseded by CONV-B02, which asks for the same PID
  read on the surface that actually needs it — a status reader that reports `dead`, rather
  than a reclaim on the recovery path, which is the one caller already asserting the run is
  gone.
- **A release-checklist step that "names a hook run which cannot happen"** (2026-08-12).
  Re-grounded and not reproduced: no checklist in the tree names a hook run, so that claim
  resolves against nothing. The operator friction behind it is real and did have a cause —
  five gate commands run by hand against a checklist listing four — which is CONV-B48,
  shipped. CONV-B15 stays open on its own terms and is unaffected either way.
- **A fix-brief hint teaching the repair spawn to suspect the check** ("if the suite passes
  and only an environmental floor fails, report rather than patch", 2026-08-24). Declined as
  a separate row on two grounds. It arrives one layer too late: CONV-B40(a) refuses the
  series before a fix spawn is ever purchased, and a hint that asks a spawn to overrule its
  own gate is the weaker instrument at twice the price. And a standing rule appended to the
  per-prompt brief is exactly the carrier problem CONV-B12 exists to fix, so if it is ever
  wanted it is a CONV-B12 directive, not prose bolted onto the fix prompt.
- **A maintainer note listing convoy's model-mirror sites (T39a)** (2026-10-06). Declined as
  superseded, not for want of a home. The age tripwire it complemented gave way to
  ADR-0010's floor stamp and lineup advisory in 0.13.0, CONV-B29 removed the price table, and
  the three sites that remain (`core/governance.py`, `skills/convoy/SKILL.md`,
  `interface/scaffold.py`) are registered with the lineup-refresh walk outside this
  repository, which is where a lineup change starts. The 2026-09-26 lineup change touched the
  floor table, its test and the CHANGELOG, and missed no site.

### Routed out — the fix lands outside convoy

Recorded here so they are not re-filed as convoy rows. Routed by where the fix lands, not
where the artifact lives.

- A repository-agnostic orchestration rule imposing commit-subject scopes on a repository
  that already has a settled convention — belongs in the orchestration prompt that emits
  the rule, not in the engine that carries it. The convoy-local half is CONV-B12.
- A migration-parity checklist dropped when a predecessor's doctrine was superseded with no
  successor named — belongs in the method documentation of the planning tool that owns
  decomposition.
- "A document is not evidence of runtime behaviour" — belongs in the feedback-report
  discipline that produced the citation.
- "A check on a file the toolchain repairs cannot be a test", and "measure a base rate
  before building a detector" — general engineering lessons, belonging to the
  process-discipline reference that owns them. The second is already applied here, in
  CONV-B20 and CONV-B24.

---

## Row-ID map

Triage-minted `T` rows resolve to `CONV-B` items as follows. Rows not listed are either
shipped (see above) or carried forward unchanged in the watch table.

| T row | Lands in |
|---|---|
| T13b, T28a | CONV-B03 |
| T29a, T29b, T29c | CONV-B02 |
| T30a, T30b | CONV-B04 |
| T31a, T31c | CONV-B08 |
| T31b | CONV-B05 |
| T32a | CONV-B01 |
| T32b | CONV-B22 |
| T33a | CONV-B11 |
| T34a, T34b | CONV-B09 (T34a superseded by T71a; T34b open) |
| T35a | CONV-B12 |
| T35b | CONV-B06 |
| T36a | CONV-B13 |
| T37a | CONV-B17 (shipped 0.16.0) |
| T38a | CONV-B08 |
| T39a | declined, superseded (CONV-B14 settled by ADR-0010) |
| T15b | CONV-B16 |
| T19b | CONV-B21 |
| T22a | CONV-B23 |
| T23a, T27a, T27b | CONV-B24 |
| T26a | shipped 0.8.0 |
| T10b | declined, superseded by CONV-B02 |
| T40a | CONV-B38 |
| T40b | CONV-B39 |
| T41a, T41b, T41c | CONV-B40 |
| T42a | CONV-B41 |
| T43a, T43b | CONV-B42 |
| T44a, T44b, T44c | CONV-B43 |
| T44d | CONV-B44 |
| T45a | CONV-B45 (shipped) |
| T46a | CONV-B46 (watch) |
| T47a | CONV-B47 (shipped) |
| T48a | CONV-B48 (shipped) |
| T49a, T49b | CONV-B49 (shipped) |
| T50a | CONV-B50 (shipped) |
| T52a, T52b | CONV-B52 (shipped 0.10.0; T52b's doctrine folded into CONV-B08's home) |
| T53a | CONV-B53 (measured 2026-09-03) |
| T54a, T54b | watch table (declared red windows; halt-for-adjudication resume) |
| T55b, T55c | CONV-B54 (shipped 0.10.0) |
| T55a | CONV-B65, `proposed` since the 2026-09-13 pass — per-PR changelog fragments (listed under CONV-B54 at `watch` until 2026-10-06) |
| T56a, T56b | CONV-B42 (shipped 0.14.0) |
| T57a | shipped 0.14.0 (the `docs/GUARDRAILS.md` test-doctrine rule) |
| T57b | CONV-B66 (shipped 0.16.0) |
| T58a | shipped 0.14.0 (`changelog_gate.py --explain`) |
| T58b | CONV-B67 (shipped 0.16.0) |
| T59a, T59b | shipped 0.14.0 (`convoy_version` on the run and status envelopes; the skill states its version) |
| T60a | CONV-B41 (partially shipped 0.14.0) |
| T61a | CONV-B68 (proposed) |
| T61c | CONV-B62 (shipped 0.16.0) |
| T62a | CONV-B69 (shipped 0.16.0; relocates CONV-B53's doctrine sentence) |
| T66a | CONV-B70 (shipped 0.16.0) |
| T70a | CONV-B71 (this reconciliation) |
| T71a | CONV-B09 (a) (shipped 0.16.0; supersedes T34a's wording) |
| T67a | CONV-B73 (shipped 0.17.0) |
| T58c, T59c, T60b, T61b, T62b, T64a, T64b, T65a, T66b, T68a | watch table |

Rows received from the 2026-08-11 cross-project pass resolve as **KEEL-B16 → CONV-B36**
(the spec pin). CONV-B37 was routed here from the collection's review with no foreign row
ID attached; it is recorded against CONV-B12, whose mechanism it generalizes. The
remaining cross-review citations — CRAF-B06 and CRAF-B13 (CONV-B14), CRAF-B26 and MANT-B11
(CONV-B15), CRAF-B29 (CONV-B28), FATH-B17 (CONV-B27), FATH-B36 (CONV-B10 and CONV-B35),
KEEL-B06 (CONV-B08) — are notes on existing rows, not rows of their own.
