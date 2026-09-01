# Authoring doctrine

<!-- Word budget: 1,200 words. Set at the file's birth, per the rule that a document
only acquires a cap while someone still remembers what it is for. A promotion into
this file that would breach the budget names what it displaces — a clause folded,
tightened, or retired — and the budget itself moves only by a deliberate edit to this
header, not by drift. Current scope: gate separability and the one-PR-series pattern.
The full authoring-doctrine fold (gate-scope rules, budget sizing, prompt hygiene)
lands here when it is built; until then the skill and the design docs carry it. -->

Advice for people and agents composing convoy with work that happens outside it. The
schema reference is [design/02-formats.md](design/02-formats.md); the manual is
[skills/convoy/SKILL.md](../skills/convoy/SKILL.md). This document carries doctrine —
the judgment calls the schema cannot state.

## The gate is separable from the run

Convoy is two capabilities with one wire format, and they are adopted separately:

- **The runner** — decompose a plan into a series, spawn an implementation per PR,
  gate, repair, integrate. Buy it when the plan is already PR-shaped and nobody
  intends to sit through the hours.
- **The gate** — `convoy gate` / `convoy_gate`: run declared `[[checks]]` against a
  workspace once, with fail-closed independence, and read back a verdict envelope.
  Buy it whenever the implementation happens *elsewhere* — direct agent turns,
  subagent dispatch, a colleague's branch — and "done" should not be the
  implementer's own claim.

The dispatch mistake this section exists to prevent: evaluating convoy as
all-or-nothing, rejecting the runner on its merits, and discarding the gate with it.
The runner's fit conditions are narrow (a settled multi-PR plan); the gate's are
broad (any work whose verification should be independent of whoever produced it). A
round of externally orchestrated PRs verified only by the agents that implemented
them has judge and defendant identical on every count — exactly the arrangement the
gate exists to break, and it costs one command to break it.

A gate-only file needs two sections:

```toml
[series]
id = "my-gate"

[[checks]]
name = "suite"
run = "uv run pytest -q"
blocking = true
independent = false
```

A full series.toml works unchanged — the same file that drives `run` gates
standalone, so a repo that has a series keeps one set of checks, not two.

What the gate framework adds over running the same commands by hand:

- **Fail-closed independence.** A check marked `independent = true` with an
  out-of-tree `asset` is refused — not skipped, refused — when its isolation cannot
  be backed. An implementer-unreachable oracle is the one gate a self-serving
  implementation cannot quietly satisfy, and the framework makes wiring one safe
  rather than an act of discipline.
- **A machine verdict.** One envelope with per-check structured results, an exit
  code an orchestrator can branch on, and a failure `detail` (plus the check's
  declared `repair_hint`) written to re-brief a fix attempt.
- **Refusals instead of vacuous greens.** A typo'd phase tag, a selection with no
  blocking check, or an unbacked oracle each come back as `usage`, never as a green
  that looks like assurance.

## The one-PR-series pattern

When work arrives one task at a time but should still run governed — implemented by
a spawned agent, gated, budgeted, metered — author a **series of one PR** and run it
with the ordinary engine. This is a supported pattern, not a workaround: an external
harness has driven dozens of single-PR series in production measurement runs, one
`convoy run` per task, collecting the same telemetry a long series yields.

Use it instead of gate-only composition when you want convoy to *own the spawn* —
config isolation, budget caps, the fix loop, and per-spawn economy — and gate-only
composition when the orchestration already exists and only the verification is
missing. The decision is about who owns the implementation spawn; the gate semantics
are identical in both.

Practical notes for the single-PR shape:

- The DAG is trivial, but the schema still wants the section complete: one `[[prs]]`
  entry, `depends_on = []`.
- Budget to the task, not to a wave: with one PR there is no cross-PR amortization,
  so the per-phase caps are the whole ceiling.
- `resume` still works and still matters — a killed driver resumes without
  re-purchasing the implementation if it already gated green.
