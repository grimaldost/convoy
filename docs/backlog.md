# Backlog — the durable improvement ledger

This is the canonical, tracked record of convoy's improvement backlog. It is fed
by triage passes over dogfooding feedback and by periodic feature reviews; the raw
feedback reports and the triage documents themselves are session artifacts and stay
local-only in [docs/feedback/](feedback/) (see the `.gitignore` there). A row here is
written so a maintainer can build it without the source reports.

**Last reconciled: 2026-09-01.** Three inputs were merged in this pass:

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

## Reading this backlog

- **ID.** `CONV-Bnn` is the stable build ID used from this pass forward. `T<cluster><letter>`
  IDs are minted by triage passes and remain valid; the [row-ID map](#row-id-map) resolves
  them to `CONV-B` items so older reports and triage documents stay readable.
- **Effort.** `S` — one file, no contract change. `M` — several files, usually a
  CHANGELOG entry and tests. `L` — needs an ADR, a new document, or a design first.
- **Source.** `[triage]` (dogfooding evidence), `[review]` (the 2026-08-11 feature review),
  `[research]` (the landscape and ecosystem briefs), `[cross-review]` (the 2026-08-11
  cross-project consistency pass), `operator observation` for a direct report with no
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

**Effort** M · **Source** [triage] · **Rows** T42a

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

**Effort** S for (a), M for (b) · **Source** [triage] · **Rows** T34a, T34b

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

**Status.** **Partly settled; the row is unbuilt.** Cross-review point (a) — the
contradiction between "all four mirrors are correct today" and the sibling collection's
claim that the canonical lineup they copy from is stale — is resolved: the canonical lineup
was reconciled on 2026-08-11 and convoy's mirrors were re-synced against it, which shipped
in 0.9.0 as the `strong` tier resolving to `claude-opus-5` (`DEFAULT_TIER_MODELS` and the
skill's tier map; family-keyed pricing needed no change). The lineup was in fact behind, so
the ordering warning in (a) held — and it holds for the *next* pass too: the sync date to
stamp is the reconciliation's, not this row's build date. Everything the row actually asks
for remains unbuilt: no sync-date stamp, no age tripwire, no `[governance.tier_models]`
override, no maintainer note (T39a), and no registration in the collection's bindings file
(point (b)). This cycle's fix was manual, which is exactly the state the row exists to end.

**Effort** S–M · **Source** [triage] + [review] + [cross-review] · **Row** T39a, escalated
from `watch` by the review

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

**Effort** M · **Source** [triage] · **Rows** T43a, T43b

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

**Effort** M · **Source** [triage] · **Rows** T44d

---

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

**Effort** S · **Source** [review] + [triage]

### CONV-B21 — Terminal (whole-series) checks that run once after the final PR integrates.

**Cause / evidence.** T19b, held at `watch` with a reason: the gap that motivated it — a
subset gate cannot see a full-suite-only regression — was closed in practice by the
gate-scope rule at the cost of one line per series, and three consecutive waves then closed
with no post-run surprises. The mechanism is still distinct from phase scoping (pay an
expensive whole-series check once rather than per-PR) but its remaining yield is now
unmeasured. Needs a new position in the run loop, after the PR walk. [triage]

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

**Effort** L · **Source** [triage] + [review] · **Row** T32b

### CONV-B23 — Per-role `effort` under `[governance]`.

**Cause / evidence.** The same shape as the existing per-role `budgets`/`tools` tables, and
`resolve_spawn` already keys on role, so the seam exists. `effort` is series-global today
and applies to implementation and repair alike, though a fix spawn repairing a small gate
red plausibly wants a different level. Distinct axis from the per-PR override. Singleton.
**(consumer-affecting)** [triage]

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

**Status.** **Measured once, headline retracted, question open** (2026-09-01). 24 trials
at the weak tier, $9.11. The composed arm read 8/8 on the target criterion against the
naive arm's 4/8 — and a blind two-reviewer validity pass found that seven of those eight
implementations were already correct before the gate ran, that the criterion's grading
items are string-identical to the probe's assertions, and that nothing survives
multiple-comparison correction; the arms were also contiguous blocks against comparators
bought two months earlier. What the round *does* establish, within-arm and without a
cross-arm comparator: an implementer-unreachable probe plus a bounded fix loop repairs the
class it asserts (4/8 → 7/8), and a self-oracle gate goes green while a held-out oracle
fails in roughly fifteen of twenty-six trials across three batches. As engineering, the
standalone gate composed cleanly with a non-convoy harness on every invocation and cost no
more per completed task than a hand-wired probe. The retracted claim was the advocate's;
the retraction was the rule working. Next: the placebo-gate, batch-randomized replication
the report specifies, and — separately — the experiment this row actually asks for, which
none of these arms was: multi-agent dispatch on PR-sized real-repo tasks at the tier
actually dispatched.

**Effort** M (the arms exist; the cost is wall-clock and analysis) · **Source** [triage] ·
**Rows** T53a

### Carried-forward watch rows

Anchored, awaiting a second report or a clear trigger. Each stays valid; none has cleared
the promotion gate.

| Row | Substance | Home |
|---|---|---|
| T3a | DAG-aware continuation past a halt (continue PRs whose dependency closure excludes the halted PR). Economics largely subsumed by `--resume`. | `interface/drivers/headless.py`, `core/dag.py` |
| T4b | Commit-provenance telemetry: agent-authored vs engine-synthesized. **(consumer-affecting)** | `core/telemetry.py` |
| T5a | Mixed-tier design decision, resolved by ADR-0007. Propagation to the sibling planning tool that emits per-PR tiers is still outstanding; see CONV-B18. | `core/spec.py`, `docs/design/02-formats.md` |
| T6a | `files touched: N (+A/-B)` in per-PR implementation narration — a reasonable cheap addition if narration is ever revisited. | `interface/reporter.py` |
| T6b | Per-PR integration state in telemetry. | `core/telemetry.py` |
| T15c | Bounded auto-retry of the branch-setup step before halting (observed environmental `checkout -b` flake). | `interface/drivers/headless.py` |
| T17 | MAX_PATH detection plus a "scaffold into a shorter directory" hint in `convoy_init`; the `_error_kind` classifier exists and only `_run_impl` uses it. | `interface/scaffold.py`, `interface/mcp/server.py` |
| T18 | Meter the seat probe as a `role: "preflight"` spawn line, if a consumer ever needs to-the-cent totals. **(consumer-affecting)** | `core/telemetry.py`, `interface/seat_probe.py` |
| T30c | Name `docs/plans/*` as historical (append-only, not edited by feature work) in AGENTS.md's living-doc set. Singleton. | `AGENTS.md` |
| T34c | An ADR-template line naming the surfaces on which a rationale's named reader actually meets it — ADR-0008 promised an operator an advisory and delivered it on the dry-run envelope only, which cost three releases. Singleton. | `docs/adr/` template |
| T54a | A declared **red window** — a check that must be red until a later PR, by design, with going green early or staying red late as the failure. `phases` displaces which PR a check gates and `blocking = false` makes it permanently advisory; neither expresses "red now, green from PR04". Design-only, no priced instance. **(consumer-affecting)** if built. | `core/spec.py`, `core/gate.py` |
| T54b | Halt for human adjudication and resume with the conversation preserved, rather than a fresh spawn. `resume` re-reads the series file but restarts the spawn. Design-only, singleton. | `interface/drivers/headless.py` |

---

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

**Effort** M · **Source** [review] · **Gate** CONV-B18

### CONV-B34 — Replace the credential-copy isolation with native flags, if CONV-B19 finds a matching arm. Replacement: `--setting-sources` plus `--strict-mcp-config`; keep `_ENV_STRIP` either way.

**Cause / evidence.** The isolation goal is sound and measured (about 35k input tokens of
operator toolkit load before a bare prompt does anything). The implementation depends on a
private, undocumented credentials file name. If an arm authenticates, keeps operator
hooks/plugins/skills out, and still loads the workspace's own CLAUDE.md, the copy can go.
[review; research]

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

**Effort** L · **Source** [review] + [research] + [cross-review]

---

## Shipped

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
| T34a, T34b | CONV-B09 |
| T35a | CONV-B12 |
| T35b | CONV-B06 |
| T36a | CONV-B13 |
| T37a | CONV-B17 |
| T38a | CONV-B08 |
| T39a | CONV-B14 |
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
| T53a | CONV-B53 (in flight) |
| T54a, T54b | watch table (declared red windows; halt-for-adjudication resume) |
| T55b, T55c | CONV-B54 (shipped 0.10.0) |
| T55a | CONV-B54, held at `watch` — per-PR changelog fragments |

Rows received from the 2026-08-11 cross-project pass resolve as **KEEL-B16 → CONV-B36**
(the spec pin). CONV-B37 was routed here from the collection's review with no foreign row
ID attached; it is recorded against CONV-B12, whose mechanism it generalizes. The
remaining cross-review citations — CRAF-B06 and CRAF-B13 (CONV-B14), CRAF-B26 and MANT-B11
(CONV-B15), CRAF-B29 (CONV-B28), FATH-B17 (CONV-B27), FATH-B36 (CONV-B10 and CONV-B35),
KEEL-B06 (CONV-B08) — are notes on existing rows, not rows of their own.
