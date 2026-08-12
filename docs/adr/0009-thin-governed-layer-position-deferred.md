# ADR-0009 — The thin-governed-layer position, deferred on measurement cost

## Status

Accepted (2026-08-12) as a **deferral**. What is accepted is that the position is *not*
recorded as convoy's settled identity, and that this record names the price and the
evidence that would settle it either way. Serves backlog row CONV-B27, which asked for the
position itself; this is the answer that row's own cross-review note licensed.

## Context

Two independent inputs reached the same split. A landscape brief found that every
orchestration mechanism convoy was originally built for is now native to a commodity
harness — spawning, fan-out, per-agent model and effort, worktree isolation, a session
budget, resume, structured returns. An independent feature review arrived from the other
direction at roughly 40% infrastructure the harness has absorbed wrapped around 60% it
still does not do: a deterministic shell-command gate as the sole merge arbiter
([ADR-0002](0002-deterministic-gate-is-the-sole-merge-arbiter.md)), a bounded repair loop
re-briefed with the failing check's own output, branch-per-PR merge-into-integration with
resume-by-ancestry, and an append-only per-spawn economy ledger a third process can read
([ADR-0003](0003-append-only-versioned-telemetry.md)).

CONV-B27 proposed writing that split down as convoy's position — a thin governed layer over
a commodity harness — so the retire list (CONV-B29 through CONV-B35) would have a stated
principle behind it rather than case-by-case judgement.

The load-bearing claim in that position is the residue: that the gate, the repair loop, the
branch/integrate/resume discipline and the ledger are worth their maintenance because
nothing else offers them. **That claim is unmeasured.** Every input behind it is a reading
of what other tools ship, not a comparison of outcomes. The row's own cross-review note said
so and gave two options: sequence the ADR after the measurement, or write the claim as
unmeasured and name what would settle it. This record takes the second, because the
measurement was designed and then not bought.

### The measurement, and the price that stopped it

A sibling evaluation harness owns the comparison (its row FATH-B17, carried here as a join
key): the governed arm against a bare arm at the **weak tier** — the tier where the bare arm
actually fails, which is the only place the comparison can discriminate. The design was
authored, adversarially reviewed, and repaired. It stopped on cost, not on doubt.

The harness's dry-run priced the matrix at **$152.00**: 16 control cells at $32.00 and 8
treatment cells at $120.00, against a **$30 rail** and an original estimate of **$4–16**.
The arithmetic behind the overrun is the finding worth recording: exercising the multi-PR
engine costs about **$15 per cell**, because one cell purchases a whole governed series —
several real spawns, each with its own gate and possible repair — where a control cell
purchases one session. Convoy is roughly an order of magnitude more expensive to measure
than the thing it would be measured against, and that is a property of the engine rather
than a defect of the instrument.

The number is recorded instead of the intention because "this will be measured" has already
survived one reconciliation of this backlog without being bought.

### What is known without it

Three things, each stated at the strength the evidence actually supports.

**1. The mechanisms fire, and they are honest. Nothing says they are necessary.**
Production evidence is real but not comparative: the deterministic gate rejected a "done"
claim five times in 73 gate events with every red repaired or halted; the per-role cap
halted two of ten terminal runs; the DAG produced 21 truthful `pr_skipped` lines. Every run
on disk is governed, so there is no arm in which the mechanisms were absent and the outcome
was worse. This evidence establishes that convoy does what it says; it cannot establish that
a bare agent would have failed in its place.

**2. The nearest existing comparison points the other way, and its headline is
unattributable.** A weak-tier ablation in the sibling harness's ledger ran, on one
single-task bank:

| Arm | Result |
|---|---|
| bare weak-tier model | 3/8 |
| weak tier + a suite gate blind to the defect | 3/8 |
| weak tier + a strengthened gate (suite plus a deterministic contract probe) | 9/10 |

- The **9/10 arm is unattributable and must not be cited.** Its committed scenario shipped a
  literal `/path/to/…` placeholder as the probe command, so the probe never ran as the arm
  describes it, and no preimage of that arm's ledger `config_hash` was found across roughly
  170,000 candidate forms — while all fourteen other arms in the ledger reconstruct exactly.
  It has been forked to a corrected arm. The 9/10 figure is historical only.
- What survives is the **3/8 against 3/8** pair, and it does not support the position: a
  gate that cannot see the defect neither detected it nor lifted the outcome. That is
  consistent with convoy's own in-house trial already recorded in
  [01-gate.md](../design/01-gate.md) — the independent-check lane fires at the weak tier with
  a blind implementer and is null at the strong tier — and it sharpens the open question
  rather than answering it. The residue's value may sit in the **oracle an author supplies**
  rather than in the engine that runs it, and no evidence on hand separates the two.

**3. One keep-list item has direct third-party evidence.** The stream and ledger contract
was consumed by an outside program this cycle: the same sibling harness synced its parser
against 0.8.0 and caught `run_abandoned` unmapped — without the sync it would have scored a
killed run, closed by convoy's recovery path, as `COMPLETED`. That is the append-only-ledger
item on the keep list being used as a contract by someone who did not write it, and it is
[ADR-0003](0003-append-only-versioned-telemetry.md)'s consumer-affecting marker doing the
job it exists to do. It is evidence for one item, not for the position.

## Decision

**Defer.** The thin-governed-layer position is not recorded as convoy's settled identity,
and the retire list does not derive its authority from it.

- The position stands as a **hypothesis**, stated here with its consequences, not as a
  premise anything else may cite.
- **What would license adopting it:** a comparison at the tier where the bare arm actually
  fails, in which the engine's mechanisms are the only difference between arms and the
  governed arm wins by a margin whose interval excludes zero — with the gate's oracle held
  identical across arms, so that the engine and not the oracle carries the difference. That
  is FATH-B17, and its price is now known rather than estimated: about $152 at the design
  last reviewed. Buying it is a purchase decision, not a scheduling one.
- **What would license rejecting it:** the same comparison returning a null; or a cheaper
  decisive result reached first — most plausibly the corrected strengthened-gate arm
  reproducing its lift in a form that attributes the lift to the **oracle** rather than to
  the engine, which would move the residue from convoy to whoever writes the check.
- **Until either exists**, the retire rows stay case-by-case, each carried by its own
  evidence. That is how CONV-B29 through CONV-B35 are already written; none of them needs
  this ADR to stand.
- **Deferring the position does not freeze the engine.** A row with its own evidence — a
  defect, a measured cost, a contract sync — is unaffected by this record.

## Consequences

- **The retire list has no stated principle behind it, and keeps needing case-by-case
  justification.** That is the accepted cost. The alternative — a principle nothing measured
  — is precisely the failure this repository already recorded once in CONV-B09, where a
  rationale was mechanized before anyone checked whether it was true.
- **Anyone citing "convoy is a thin governed layer over a commodity harness" must cite this
  ADR**, which says the claim is unmeasured. There is no record here that can be quoted as
  settling it.
- **The 9/10 figure is quarantined.** Any future argument for the gate's value at the weak
  tier uses the corrected arm, or it uses nothing.
- **A price is now attached to convoy's own measurability** — about $15 per cell, roughly an
  order of magnitude above a single-session control. Any future evaluation of this engine
  should be budgeted against that figure rather than against a session-shaped estimate; the
  $4–16 estimate this design replaced was wrong by that factor.
- **The decisive published input is still unread.** The landscape brief calls an
  openly-published orchestration specification, which its vendor declined to productise, the
  strongest single input to any build-versus-adopt verdict — and it cites that document's
  existence, not its contents. Nobody on this project has read it. This ADR does not rest on
  it, because deferring a verdict requires no verdict; but any successor ADR that **adopts
  or rejects** the position must record that reading first, by whom, and what it changed.
- **Revisit** when the measurement is bought, or when a design appears that discriminates at
  a price closer to the rail.

## Alternatives considered

1. **Write the position as CONV-B27 asked, marked "unmeasured".** Rejected. An ADR titled
   with a position and marked `Accepted` becomes the thing that gets cited, and the hedge
   does not travel with the quotation. The status has to carry the uncertainty, because the
   title and the citation are what most readers will meet.
2. **Buy the measurement now.** Rejected on price against the approved rail, not on value:
   $152 against $30 is five times the ceiling, and the design that would settle the question
   turned out to be a different order of purchase than the one that was approved. It remains
   available at a stated price, which is the point of recording the price.
3. **Substitute a cheaper proxy: mine the run ledgers already on disk.** Rejected. Thirteen
   runs and 76 spawns are on disk and every one of them is governed. The missing arm is
   exactly the one that was never run, and a comparison against a counterfactual assembled
   from governed runs would answer a different question while looking like an answer to this
   one.
4. **Adopt the position on the strength of the two inputs agreeing.** Rejected. Both read
   the same harness release notes and the same repository. Two readings of one body of
   evidence agreeing is not independent confirmation, and the thing they agree about — what
   other tools ship — is not the thing in question, which is what the residue is worth.
