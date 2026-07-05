# convoy — C2: the gate

> Draft, 2026-07-03 (rev. after a blind panel). Read
> [00-overview.md](00-overview.md) first. This revises an earlier draft that
> over-claimed oracle independence as the product's centerpiece; the panel
> (and the evidence) demoted it to a bounded, opt-in property. This doc reflects
> that.

## What the gate does

A series declares `[[checks]]` — each a `name`, a `run` command, and a `blocking`
flag. After a PR is implemented, convoy runs the checks against the workspace.
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

## Repair — fix-on-red, provenance routes the repair only

- **Green** → integrate.
- **`blocking_red`** → the merge is blocked, always. Then:
  - **`independent_red`** (a blocking independent check failed) → the signal is
    trustworthy (the implementer can't have gamed a check it can't reach) → run
    the bounded fix loop: re-brief with the failing check's `detail`, re-run the
    gate, up to `max_fix_attempts`.
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

1. **Committable isolation** — enforce "implementer can't reach it" by permission
   / read-only mount of a committable `oracles/` convention, rather than by
   out-of-tree absolute paths that don't travel. (Overview open-decision 2.)
2. **On-ramp checks** — ship a small library of ready-made generic independent
   checks (by defect class) a user opts into by name, so first value needs no
   check authoring and there is a concrete exemplar. (Overview open-decision 4.)
