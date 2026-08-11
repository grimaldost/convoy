# convoy — C2: the gate

> Draft, 2026-07-03 (rev. after a blind panel). Read
> [00-overview.md](00-overview.md) first. This revises an earlier draft that
> over-claimed oracle independence as the product's centerpiece; the panel
> (and the evidence) demoted it to a bounded, opt-in property. This doc reflects
> that.

## What the gate does

A series declares `[[checks]]` — each a `name`, a `run` command, and a `blocking`
flag. After a PR is implemented, convoy runs that PR's checks against the workspace
— every check by default, or the subset a check's optional `phases` selects
(`core.gate.checks_for`; see [02-formats.md](02-formats.md) and ADR-0008). Scoping
decides *which* checks run and nothing else; everything below applies unchanged to
whatever is selected.
**A blocking check that is red blocks the merge — full stop, and fail-loud**
(nonzero exit, the PR is not integrated). convoy never emits a green exit over a
red. That is the whole safety contract, and it holds regardless of anything
below.

## Independence — a bounded, opt-in property

A gate made only of the implementer's own tests can pass the implementer's own
defective code: the agent that wrote the code also wrote the check, and shares
its blind spots. So a check may be marked `independent = true`, meaning it was
supplied by the series author, not by the implementing agent, and the
implementing agent cannot reach it.

This is worth **offering**, but convoy is deliberately honest about its weight:

- The evidence for independence mattering is narrow — one task family, a weak
  model, a confounded magnitude — and it is **null at the strong/default tier**,
  where a capable model self-verifies. On a normal project with a default model,
  an independent check is a backstop, not a quality lever.
- "Independence" as convoy can enforce it is **best-effort**, not a guarantee
  (see "What convoy does not guarantee"). It is one optional lane, not a
  taxonomy: a single boolean, no `provenance × lane` matrix. If you want lane
  labels for reporting, they are free-form telemetry tags, not types the verdict
  branches on.

### What convoy's own measurement shows

The claim above was inherited from an external study. convoy has since measured
it in-house, and the result agrees on every count. The setup: a blind-implementer
trial on one multi-module task — the implementing agent sees only the spec, and a
held-out acceptance suite it cannot reach is the gate — run at two model tiers
and against a no-gate control, three trials per cell.

| condition | gate red | `fix` spawns | no-gate control |
|---|---|---|---|
| weak tier, blind implementer | 3/3 | 3 | 0/3 green — shipped failing trees as done |
| strong tier, blind implementer | 0/3 | 0 | 2/3 green |
| acceptance tests visible in the workspace | 0/3 | 0 | 3/3 green |

convoy reached green in all three cells. Three things follow, and the third is
the one this doc did not previously state:

1. **At the weak tier the mechanism is real and observable.** The ledger shows
   exactly three `fix`-role spawns, all in that cell, so the repair is visible as
   spend rather than inferred from an outcome difference. It cost about $0.04 per
   trial.
2. **At the strong tier the gate never fired.** No red, no fix spawn. The
   arm-level difference against the control in that row has **no gate mechanism
   behind it** and must not be cited as evidence for the lane. "Null at the
   strong/default tier" stands.
3. **With the tests visible, the gate is *redundant* — not vacuous.** The
   implementer runs the suite itself and self-corrects, and so does the control.
   The gate is still correct and still blocking; it is simply not adding
   correctness anyone else was going to miss.

So the usage condition, plainly: **an independent check earns its correctness
value when the implementer cannot see the acceptance criteria it is judged
against.** Give the implementer the tests and the lane degrades to a backstop
against a spawn that skips running them — worth keeping, not a quality lever.

Three trials per cell is enough to watch a mechanism fire or stay silent, and not
enough to size an effect. Read the table as mechanism evidence, not effect size.

The `independent` marker changes exactly two things — **which failures are safe
to auto-repair against**, and **telemetry legibility**. It never changes whether
a red blocks the merge.

## Interface — pure verdict, shell execution and probing

```python
# src/convoy/core/spec.py — pure, no I/O
@dataclass(frozen=True)
class Check:
    name: str
    run: str                    # the shell command run against the workspace
    blocking: bool
    independent: bool = False   # supplied by the author, unreachable by the implementer
    asset: str = ''             # out-of-tree oracle path; isolation verified fail-closed at gate time
```

```python
# src/convoy/core/gate.py — pure, no I/O
from dataclasses import dataclass
from collections.abc import Sequence

@dataclass(frozen=True)
class CheckResult:
    check: Check
    passed: bool
    detail: str

@dataclass(frozen=True)
class GateVerdict:
    results: tuple[CheckResult, ...]

    @property
    def blocking_red(self) -> bool:
        'Any blocking check failed. A red is a red — this drives the merge/exit.'
        return any(not r.passed and r.check.blocking for r in self.results)

    @property
    def independent_red(self) -> bool:
        'A blocking *independent* check failed — a trustworthy signal to auto-fix.'
        return any(
            not r.passed and r.check.blocking and r.check.independent
            for r in self.results
        )

def decide(results: Sequence[CheckResult]) -> GateVerdict:
    return GateVerdict(results=tuple(results))
```

```python
# src/convoy/interface/gate_runner.py — shell
class GateRunner(Protocol):
    def run(self, workspace: Path, checks: Sequence[Check]) -> tuple[CheckResult, ...]: ...

# src/convoy/interface/fs_probe.py — shell (a free function, not a Protocol)
def isolation_result(workspace: Path, check: Check) -> CheckResult | None:
    'For a blocking independent check, verify its asset is outside the scored '
    'workspace and exists. convoy checks workspace containment and existence; '
    'it does NOT verify write permissions. On violation (no asset, in-tree '
    'asset, or missing asset), return a synthetic FAILING CheckResult so the '
    'pure verdict fails closed; otherwise return None. I/O lives here, never '
    'in gate.decide.'
    ...
```

The pure `decide` receives independence and isolation status **as data**. All
filesystem work — running commands, resolving paths, writability probes — is
shell. `gate.decide` can never accidentally reach the filesystem.

`detail` on a red carries a bounded, labelled tail of **each** stream the command wrote to,
never one stream chosen ahead of the other: choosing by channel meant any content at all on
stderr discarded stdout, and a subset-scoped suite reports its coverage-floor failure on
stdout while stderr carries only a launcher warning. One budget covers both, split so
neither crowds the other out and a short stream donates its unused share. The cut lands on a
line boundary and is marked `...`, because a tail that begins mid-word reads as though the
fragment were the failure — and `detail` is what the fix loop below re-briefs a paid spawn
with, so a misleading one is expensive.

## Repair — fix-on-red, provenance routes the repair only

- **Green** → integrate.
- **`blocking_red`** → the merge is blocked, always. Then:
  - **`independent_red`** (a blocking independent check failed) → the signal is
    trustworthy (the implementer can't have gamed a check it can't reach) → run
    the bounded fix loop: re-brief with the failing check's `detail` (plus its
    declared `repair_hint`, when the series provides one — the repo's own repair
    recipe beats inference from failure text), re-run the gate, up to
    `max_fix_attempts`.
  - **red only on implementer checks** → still blocked (fail-loud), but
    auto-fixing against a self-authored red risks chasing the blind spot that
    produced it. convoy attempts the bounded fix if configured, and **surfaces**
    the run as needing judgment rather than silently converging. It never exits
    green.
- **No dynamic model escalation.** If ever added, it triggers on repeated
  independent-red after fix exhaustion — never a first red, never a self-authored
  red.

The correction from the earlier draft: provenance decides *how to repair*, not
*whether to block*. A red always blocks. (The earlier "advisory / low-independence
gate that surfaces reds without blocking" was a foot-gun that could ship
known-failing code.)

## What convoy does *not* guarantee

Independence enforced by asset isolation is a proxy for the property that
actually matters (the implementer's code cannot influence the check's judgment),
and the proxy leaks. State this plainly rather than imply a guarantee:

- **Asset-independence ≠ input-independence.** convoy checks where the check
  *lives* (out-of-tree and present — containment and existence, not write
  permissions). A check whose `run` reads an in-tree
  fixture, or imports the implementer's module, is reachable through its inputs
  even though its asset is isolated. convoy isolates the asset; it does not
  isolate everything the asset reads.
- **Shared fixtures / monorepos.** When the independent check and the suite share
  a `conftest.py`, factories, or golden files, the implementer editing a shared
  fixture changes what the "independent" check sees. Path isolation passes;
  independence is gone.
- **Semantic independence is unverifiable.** convoy cannot know whether the
  implementer's training or context already contained the check's logic. It
  verifies filesystem isolation, not epistemic independence.

So the honest name for what convoy enforces is **workspace isolation of a
check's assets** — valuable, cheap, and worth having, but not a guarantee of
true independence.

## Guarding isolation (fail-closed)

For a **blocking** independent check, isolation must hold or the gate degrades
silently to self-grading — the exact thing the marker was for. So `isolation_result`
runs before execution and, if a blocking independent check declares no asset, or
its asset resolves inside the scored workspace, or its asset does not exist,
injects a failing `CheckResult` — the gate **fails closed** rather than running a
check whose independence it cannot back. (Non-blocking or non-independent checks
run normally.) convoy verifies workspace containment and existence, not write
permissions. This is cheap and it protects the one property the marker claims.

## Escape telemetry — a research direction, not a v1 mechanism

An earlier draft framed "the gate improves over time" as a mechanism: record when
an independent check catches a defect the suite missed, and use it to strengthen
checks. That loop needs a **downstream source of ground-truth escapes** (CI
failures, human review, field bugs) to know the suite missed something — and the
headless walk-away flow has no such later signal. So this is an **untested
research direction**, explicitly not a v1 feature: at most an optional
`gate_escape` event, off by default, useful only when convoy is wired to ingest a
downstream escape signal it does not model today.

## Testing the gate

- **Mutation testing as a wiring / regression check** (not thesis validation):
  seed known defect classes into a fixture and assert each check catches what it
  should — with an explicit per-check baseline (the class it MUST catch, and for
  an independent check the class the suite MUST miss) so the test discriminates
  rather than passing vacuously. This proves the checks are wired correctly, not
  that independence generalizes; that is an external, blind, interleaved
  replication, not convoy's own fixture.
- **Property tests** for `decide`: a blocking failure always implies
  `blocking_red`; an independent blocking failure implies both `blocking_red` and
  `independent_red`; independence never suppresses `blocking_red`.
- **Isolation fail-closed** gets its own tests, including the negative: a blocking
  independent check placed in-tree must fail closed.

## Open decisions

1. **Committable isolation** — *resolved*: the committable `oracles/` convention
   under the series root shipped (scaffold + skill); isolation remains
   containment+existence fail-closed, not a permission/read-only mount.
   Resolution note in [02-formats.md](02-formats.md). (Overview open-decision 2.)
2. **On-ramp checks** — ship a small library of ready-made generic independent
   checks (by defect class) a user opts into by name, so first value needs no
   check authoring and there is a concrete exemplar. (Overview open-decision 4.)
