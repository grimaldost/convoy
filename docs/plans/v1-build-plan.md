# convoy v1 — build plan

> Draft, 2026-07-03 (rev. after a fresh-eyes pre-mortem). The v1 (headless MVE)
> build, decomposed into a governed PR series. This is the plan to **build
> convoy**; it is distinct from convoy's own series format
> ([02-formats.md](../design/02-formats.md)), which is convoy's product. The
> series references no other tool and can be executed by any governed-execution
> driver, or by hand.

## Definition of Ready

- Design pinned: [00-overview](../design/00-overview.md), [01-gate](../design/01-gate.md), [02-formats](../design/02-formats.md).
- Scope: v1 = headless MVE (C1 spec/DAG, C2 gate, C3 telemetry, C5 spawn, C6 driver). C7 in-session and C8 authoring are v2.
- Stack: Python 3.14, uv / ruff / ty, application layout (functional core / imperative shell), `typing.Protocol` at the spawn seam.

**Resolved (pre-mortem FM-1) — resume is v2, not v1.** Given the aggressive v1
rescope, full resume (run-state, per-PR checkpoint, `--from/--to/--only`,
idempotent skip of merged PRs) is deferred to v2. v1 still **halts cleanly** on
an infra failure with a distinct exit code — it just does not auto-resume — and
the driver keeps the **checkpoint seam** (records which PRs integrated) so v2
adds resume without reopening the fail-loud loop. **B5 is dropped from the v1
series** (moved to v2); the DAG and table below mark it accordingly.

## The gate — every build-PR must pass

```
uv run ruff check src && uv run ruff format --check src
uv run ty check src
uv run pytest -q                     # the PR's own tests + all prior
```

Plus each PR's specific acceptance tests. A red blocks the PR.

## Milestone A — the MVE (thinnest end-to-end path)

Goal: `convoy run <series.toml>` on a **one-PR** series produces an integrated
working tree + a `spawns.jsonl` telemetry file, with a correct exit code. The
de-risking milestone is **A8**.

| PR | delivers | key files | acceptance test | depends_on |
|----|----------|-----------|-----------------|------------|
| **A0** | project scaffold | `pyproject.toml`, `src/convoy/`, CI, `CLAUDE.md` | `convoy --version` runs; gate green | — |
| **A1** | series spec (pure) | `core/spec.py` | round-trip property (`dump∘load==id`); validation rejects a per-PR `model`, unresolved `depends_on`, **and `independent=true` on a blocking check** (guard until B4 lands — FM-11) | A0 |
| **A2** | DAG ordering (pure) | `core/dag.py` | property: a valid order respects every `depends_on`; cycle detected; `order([one_pr])==[one_pr]` (the seam A8 calls even at length 1 — FM-5) | A1 |
| **A3** | telemetry + writer + **pricing** | `core/telemetry.py`, `core/pricing.py`, `interface/telemetry_writer.py` | snapshot **all three** events (`run_start`/`spawn_complete`/`run_complete`) with required-field assertions (FM-9); pricing: family substring match, unknown model → named default rate (FM-3); `cost_usd==0` → estimate via pricing + `cost_estimated:true` | A0 |
| **A4** | gate verdict + runner | `core/gate.py`, `interface/gate_runner.py` | `decide` properties (blocking⇒`blocking_red`; independent-blocking⇒`independent_red`; independence never suppresses `blocking_red`); runner runs a check **under a bounded timeout**; a hung/crashed check → `CheckResult(passed=False)` (FM-10) | A1 |
| **A5** | spawn port + fake | `interface/spawn.py` (Protocol + `FakeSpawn`) | `FakeSpawn` satisfies `AgentSpawn`; scripted `SpawnResult` + economy + a scriptable infra-classification | A0 |
| **A6** | headless spawn impl | `interface/spawn.py` (headless) | stub-`claude` for classification/timeout-routing; **plus a real-process integration test** (parent spawns a real grandchild; assert its sentinel stops growing after tree-kill — a stub can't fork the grandchild the kill must reap — FM-2); partial-stream cost recovery | A5 |
| **A7** | git adapter | `interface/git.py` | stage on base / branch / integrate-one onto integration / leave checked out; its own e2e on a temp repo (FM-4 split) | A0 |
| **A8** | driver + CLI — **MVE** | `interface/drivers/headless.py`, `interface/cli.py` | e2e (FakeSpawn + `git` + temp repo): (a) green → integrated + telemetry; (b) **red → fail-loud** (blocking-red exit code, not integrated); (c) **infra classification → halt with the infra exit code + `outcome=infrastructure`, not a task exit** (FM-8). Driver iterates `dag.order(prs)` even at len 1 (FM-5). MVE spawn governance is **fixed as literals** read from `[governance]` (permission/effort/budget/tools/timeout); B2 adds parity (FM-6). Exit-code taxonomy asserted: `0` integrated / `N1` blocking-red / `N2` infra halt / `N3` usage error (FM-7) | A1,A2,A3,A4,A6,A7 |

## Milestone B — thicken to full v1

| PR | delivers | key files | acceptance test | depends_on |
|----|----------|-----------|-----------------|------------|
| **B1** | multi-PR DAG execution | driver wiring | a 2-PR series runs in dependency order; a failed dependency **skips its dependents** (not silently integrated) | A8 |
| **B2** | governance parity | `core/governance.py` + driver wiring | property: no resolution yields an auto-approve permission or a per-PR model/effort override; model is phase-level; replaces A8's literal governance | A8 |
| **B3** | bounded fix loop | driver | scripted: fix-on-`independent_red` converges to green within `max_fix_attempts`; implementer-only red still blocks (fail-loud); never green over red | A8,B2 |
| **B4** | optional independent lane | `interface/fs_probe.py` + gate wiring | fail-closed when a **blocking** independent check's asset is in-tree/writable; passes when out-of-tree; removes the A1 guard (independent-on-blocking now allowed) | A4,A8 |
| ~~**B5**~~ | **deferred to v2 (FM-1)** — run-state + resume | — | not in v1; A8's checkpoint seam is the v2 hook | — |

## Dependency DAG

```
A0 ─┬─ A1 ─┬─ A2 ─────────────────┐
    │      ├─ A4 ─────────────────┤
    ├─ A3 ─────────────────────── ┤
    ├─ A5 ── A6 ──────────────────┤
    └─ A7 ────────────────────────┤
                                  └─ A8 (MVE) ─┬─ B1 ─┐
                                               ├─ B2 ─┴─ B3
                                               ├─ B4
                                               └─ (B5 → v2, deferred)
```

## Notes

- **A6 is the hard PR** — the spawn core (~200 lines of process mechanics).
  Reimplemented from scratch to the named invariants (00-overview §5 C5), reading
  a proven implementation only as a private reference. Its no-orphan invariant is
  proven by a **real-process** test, not a stub (FM-2).
- **A8 is the de-risking milestone** — per-spawn telemetry granularity, the
  fail-loud gate, the exit-code taxonomy, and infra-vs-task classification all
  first meet end-to-end here, loudly, before any depth.
- **Checkpoint seam (regardless of the FM-1 decision):** A8's driver records,
  after each PR, which PRs have integrated — even if v1 never reads it back. This
  is the seam B5 (or v2 resume) plugs into without reopening the fail-loud loop.
- **Parity guard (B2)** and **fail-loud (A8/B3)** are the invariants that, if
  wrong, silently corrupt behavior rather than failing visibly — strictest
  property tests.
- **Reflection loop:** after the series, triage recurring traps into durable
  checks.

## Pre-mortem (folded)

Fresh-eyes pre-mortem, 2026-07-03: uncertified as first drafted. Folded above —
3 blockers (FM-1 resume gap → the open DoR decision; FM-2 stub can't prove
tree-kill → real-process test; FM-3 no pricing source → `core/pricing.py` in A3),
5 majors (FM-4 split A6→A7/A8; FM-5 DAG seam at A8; FM-6 MVE governance named;
FM-7 exit-code taxonomy; FM-8 infra e2e arm), 3 minors (FM-9 all-three-event
snapshots; FM-10 gate-check timeout; FM-11 A1 guard on independent-blocking).

## Sequencing to the build

1. This plan (folded) + the **FM-1 resume decision**.
2. Author the factory's series (the build-execution input) + per-PR prompts.
3. **The factory builds** — gated on explicit go-ahead (the first token-spending
   step).
