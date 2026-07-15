# convoy — C1/C3: the formats

> Draft, 2026-07-03. convoy's two public formats — the **series spec** it reads
> and the **telemetry** it writes. These are convoy's own, general-purpose, and
> self-contained: any tool can author a series or consume the telemetry. Both are
> versioned; fields are added, never renamed or repurposed.

## The series spec — `series.toml`

Plain TOML value types only (scalars, arrays, tables, arrays-of-tables), so a
spec can be machine-generated and round-tripped losslessly. A series is a DAG of
PR-sized tasks plus the governance and gate that apply to them.

| Section | Fields | Meaning |
|---|---|---|
| `[series]` | `id`, `version` | Series identity |
| `[branches]` | `base`, `integration` | Fixture staged on `base`; integrated result on `integration` |
| `[paths]` | `prompts` (dir), `outputs` (dir) | Asset locations; **absolute paths accepted** so assets can live outside the scored workspace |
| `[governance]` | `model` (or `tier`), `effort`, `permission_mode`, `timeout_seconds` | The default per-spawn governance; a `[[prs]]` table may override `model`/`tier`/`effort` for itself |
| `[governance.budgets]` | `implementation`, `review`, `fix` | USD ceiling per phase |
| `[governance.tools]` | `implementation`, `review`, `fix` | Tool allow-list per phase |
| `[review]` | `blocking` (optional), `max_fix_attempts` | `max_fix_attempts` bounds the fix loop; `blocking` is **reserved** for an optional blocking LLM self-review the v1 headless driver does not run — optional, default `false` (the deterministic `[[checks]]` gate is the sole merge arbiter) |
| `[[checks]]` | `name`, `run`, `blocking`, `independent`, `asset`, `repair_hint` | The gate — shell checks; `independent = true` marks an author-supplied, implementer-unreachable check (see [01-gate.md](01-gate.md)); `asset` is an optional absolute out-of-tree path to a blocking independent check's oracle; `repair_hint` is an optional one-line repair recipe (a command or instruction) appended verbatim to the fix brief when THAT check fails |
| `[[prs]]` | `id`, `branch`, `prompt`, `phase`, `depends_on`, `model`, `tier`, `effort` | The PR decomposition as a DAG; `model`/`tier`/`effort` are optional per-PR overrides |

`permission_mode` ∈ {`default`, `acceptEdits`, `plan`, `bypassPermissions`};
convoy never *forces* `bypassPermissions` (a caller may set it; the field is
required and passed through unchanged — convoy supplies no permission mode of
its own). Per-PR governance follows four rules:

1. A `[[prs]]` `model`/`tier`/`effort` key wins for that PR; `[governance]` is the
   fallback when the key is absent.
2. A PR that sets `model` **or** `tier` supplies **both** — its `(model, tier)` pair
   replaces the series pair, which is not consulted. So a series `model` never shadows
   a per-PR `tier` (model resolution prefers model over tier, so an independent merge
   would silently pick the wrong one).
3. Both spawns of a PR — implementation and fix — resolve the same value, so a repair
   never runs on a different model than the work it repairs.
4. `[governance]` must still resolve a model even when every PR overrides it: it is the
   fallback and the audit baseline, and the pre-flight resolves it too.

- **`asset`** is the optional out-of-tree path to a blocking independent check's
  oracle. Its isolation is verified **fail-closed at gate time**, not at spec-load:
  a blocking independent check with no `asset`, an `asset` inside the scored
  workspace, or a missing `asset` **fails closed** (a synthetic failing result; the
  check is not run). See [01-gate.md](01-gate.md). It is empty (and omitted from a
  round-tripped spec) for any check that does not use it.
- **The gate is series-global.** The same `[[checks]]` run after **every** PR —
  there is no per-PR check. A PR either passes the one shared gate or is repaired
  against it.
- **`[governance.budgets]` and `[governance.tools]` each require all three roles**
  — `implementation`, `review`, and `fix`. A missing role is a load-time error. The
  **`review` role is reserved**: the v1 headless driver spawns only `implementation` and
  `fix`, so a `review` budget and tool allow-list are required for forward-compatibility
  but have no effect in v1 — the same reserved status as `[review].blocking`.
- **Every budget must be `> 0`.** A `0` (or negative) budget is rejected at load;
  a `0` budget would otherwise silently disable the spawn's `--max-budget-usd` cap
  (unlimited spend), so it is a footgun convoy refuses.
- **`budget`/`budgets` are rejected per PR.** Budgets are per-role
  (`implementation`/`review`/`fix`), so a per-PR scalar `budget` has no role to bind
  to — a different axis, not a narrower version of the per-PR `model`/`tier`/`effort`
  override. A `[[prs]]` table carrying either key is a load-time error.
- **"Phase" has two unrelated meanings.** The governance **role**
  (`implementation` / `review` / `fix`) — what `[governance.budgets]`,
  `[governance.tools]`, and the spawn resolution key on — is distinct from the
  free-form `[[prs]].phase` grouping tag on the DAG. PR execution order is
  determined by `depends_on`; the `phase` tag imposes no cross-phase ordering.

### Worked example

```toml
[series]
id = "add-comparison-ops"
version = "1"

[branches]
base = "convoy/base"
integration = "convoy/integration"

[paths]
prompts = "/abs/series/prompts"        # the series root holds prompts/, oracles/,
outputs = "/abs/series/outputs"        # outputs/ — and the scored workspace/ as a subdir

[governance]
model = "claude-sonnet-5"
effort = "medium"
permission_mode = "default"
timeout_seconds = 1800

[governance.budgets]
implementation = 2.50
review = 0.75
fix = 1.00

[governance.tools]
implementation = ["Read", "Edit", "Write", "Bash"]
review = ["Read", "Grep", "Glob"]
fix = ["Read", "Edit", "Write", "Bash"]

[review]
blocking = true
max_fix_attempts = 2

[[checks]]
name = "suite"
run = "python -m pytest -q"
blocking = true
independent = false
repair_hint = "regenerate fixtures with scripts/gen_fixtures.py before rerunning"  # optional

[[checks]]
name = "type-contract"
run = "python /abs/series/oracles/type_probe.py"   # author-supplied, in the series root's oracles/
asset = "/abs/series/oracles/type_probe.py"        # committable, yet outside the scored workspace/
blocking = true
independent = true

[[prs]]
id = "pr-1-lexer"
branch = "convoy/pr-1"
prompt = "01-lexer.md"
phase = "core"
depends_on = []
tier = "weak"                          # this PR overrides the series tier for itself

[[prs]]
id = "pr-2-parser"
branch = "convoy/pr-2"
prompt = "02-parser.md"
phase = "core"
depends_on = ["pr-1-lexer"]            # no per-PR governance: inherits [governance]
```

### Validation (pure) vs. probing (shell)

`spec.py` validates *structure* purely (required fields, types, `depends_on`
references resolve; per-PR governance keys are optional, `budget`/`budgets` are
rejected); DAG acyclicity and duplicate-id
detection are the pure pre-flight's job (`core/preflight.check_dag` via `dag.order`),
run by `convoy validate` and by `convoy run` before any mutation — not `load_series`'s.
Anything that touches
the filesystem — do `[paths]` exist, and does a blocking `independent` check's
asset live **outside the scored workspace and exist** — is a **shell** concern
(`fs_probe.py`), fed back into the pure verdict as data. convoy verifies workspace
containment (the asset is outside the scored tree) and existence; it does **not**
verify write permissions. `spec.py` never reads the disk.

## The telemetry — `spawns.jsonl`

An **append-only JSON-lines** file under `[paths].outputs`. One object per line.
This is convoy's economy record and its primary observability surface — designed
so *any* external consumer (a dashboard, a cost report, a blind scorer) can join
on it without convoy knowing about that consumer.

Every line carries `schema_version` and an `event`. v1 defines five events:

| `event` | Emitted | Required fields |
|---|---|---|
| `run_start` | once per `convoy run` | `schema_version`, `event`, `run_id`, `series_id` |
| `spawn_complete` | once per agent spawn | `schema_version`, `event`, `run_id`, `pr_id`, `role`, `exit_code`, `input_tokens`, `output_tokens`, `num_turns`, `duration_s`, `cost_usd`, `effective_model` |
| `gate_complete` | after every gate evaluation of a PR | `schema_version`, `event`, `run_id`, `pr_id`, `attempt`, `blocking_red`, `independent_red`, `checks` |
| `pr_skipped` | for each PR the run never processed because an earlier PR halted the series | `schema_version`, `event`, `run_id`, `pr_id`, `reason` |
| `run_complete` | once per `convoy run` | `schema_version`, `event`, `run_id`, `outcome`, `integrated` |

- **`run_id`** — a lexicographically-sortable stamp (`%Y%m%dT%H%M%SZ` + short
  suffix) grouping one invocation's events; a reused `outputs` dir stays safe
  because a consumer selects the most-recent `run_id`.
- **`role`** ∈ {`implementation`, `review`, `fix`}.
- **`gate_complete.attempt`** is `0` for the initial gate and `1..N` after the Nth
  fix re-gate. **`checks`** is a list of objects `{name, passed, blocking,
  independent, detail}` — one per check, in run order — so a blocked run is
  self-explaining: a consumer sees which check failed and why.
- **`pr_skipped.reason`** is free-form (e.g. `series halted at pr-1 (blocked) before
  this PR started`): it states *why the series stopped*, not a claim of a direct
  dependency edge to the halted PR.
- **`effective_model` is never blank.** On a killed or partial spawn it falls back
  to the requested model, so an economy consumer always has a model to attribute
  the row to.
- **`output_tail`** (additive) — the last 2 KB of the spawn's combined stdout+stderr,
  populated only on a non-`ok` classification (`''` on ok lines), so an infrastructure
  or budget halt is diagnosable from telemetry alone (an expired seat's
  `Not logged in`, a usage-limit message) instead of demanding a manual re-run.
- **These two events are additive.** `schema_version` stays `1`; a consumer keys on
  `event` + `schema_version` and ignores unknown events, so an older reader that
  only knows `run_start` / `spawn_complete` / `run_complete` skips `gate_complete`
  and `pr_skipped` lines without breaking.
- **`outcome`** ∈ {`completed`, `blocked`, `infrastructure`, `budget`} — task
  success, a gate-blocked merge, an infra halt (auth/quota/retry) that is
  re-runnable, or a spend-cap truncation. On `budget` the PR is halted and its
  partial work is **not** integrated.
- **Per-spawn granularity is mandatory.** A run-total-only file cannot be joined
  per spawn and is useless for economy analysis. Each spawn is one line.
- **`cost_usd` fallback.** When the provider reports `0.0` under a subscription
  auth, convoy substitutes a `input_tokens × price_in + output_tokens × price_out`
  estimate and sets `cost_estimated: true` on that line, so a consumer never
  silently reads a real run as free.

### Worked example

```json
{"schema_version": 1, "event": "run_start", "run_id": "20260703T142210Z-a1", "series_id": "add-comparison-ops"}
{"schema_version": 1, "event": "spawn_complete", "run_id": "20260703T142210Z-a1", "pr_id": "pr-1-lexer", "role": "implementation", "exit_code": 0, "input_tokens": 18422, "output_tokens": 3110, "num_turns": 9, "duration_s": 74.2, "cost_usd": 0.11, "effective_model": "claude-sonnet-5"}
{"schema_version": 1, "event": "spawn_complete", "run_id": "20260703T142210Z-a1", "pr_id": "pr-1-lexer", "role": "fix", "exit_code": 0, "input_tokens": 9004, "output_tokens": 1520, "num_turns": 4, "duration_s": 38.9, "cost_usd": 0.05, "effective_model": "claude-sonnet-5"}
{"schema_version": 1, "event": "run_complete", "run_id": "20260703T142210Z-a1", "outcome": "completed", "integrated": true}
```

A **blocked** two-PR run (`pr-1-lexer` → `pr-2-parser`). The initial gate is red on
a blocking independent check; the bounded fix loop is exhausted and still red, so
`pr-1-lexer` never integrates and its dependent `pr-2-parser` is never processed.
(Fix spawns and intermediate re-gates elided for brevity; the final `gate_complete`
is still `blocking_red`.)

```json
{"schema_version": 1, "event": "run_start", "run_id": "20260703T160102Z-b7", "series_id": "add-comparison-ops"}
{"schema_version": 1, "event": "spawn_complete", "run_id": "20260703T160102Z-b7", "pr_id": "pr-1-lexer", "role": "implementation", "exit_code": 0, "input_tokens": 17330, "output_tokens": 2980, "num_turns": 8, "duration_s": 69.5, "cost_usd": 0.10, "effective_model": "claude-sonnet-5"}
{"schema_version": 1, "event": "gate_complete", "run_id": "20260703T160102Z-b7", "pr_id": "pr-1-lexer", "attempt": 2, "blocking_red": true, "independent_red": true, "checks": [{"name": "suite", "passed": true, "blocking": true, "independent": false, "detail": "12 passed"}, {"name": "type-contract", "passed": false, "blocking": true, "independent": true, "detail": "type_probe: expected Ordering, got object"}]}
{"schema_version": 1, "event": "pr_skipped", "run_id": "20260703T160102Z-b7", "pr_id": "pr-2-parser", "reason": "series halted at pr-1-lexer (blocked) before this PR started"}
{"schema_version": 1, "event": "run_complete", "run_id": "20260703T160102Z-b7", "outcome": "blocked", "integrated": false}
```

### Exit codes

`convoy run` maps its outcome to a process exit code, so a caller can branch
without parsing telemetry:

| Code | Meaning |
|---|---|
| `0` | completed — every PR passed the gate and integrated |
| `1` | blocked — a blocking check stayed red after the bounded fix loop |
| `2` | infrastructure — an auth / quota / retry / timeout halt, re-runnable |
| `3` | usage — a bad spec, an unreadable file, or a pre-flight problem |
| `4` | budget — a spawn hit its `--max-budget-usd` cap |

## Versioning discipline

`schema_version` is present on every line from day one. Evolution is
**additive**: a new optional field bumps nothing; a breaking change (rename,
retype, semantic shift of an existing field) bumps `schema_version` and is
documented here. A consumer keys on `event` + `schema_version` and can ignore
unknown fields. This is what lets convoy's telemetry stay a stable contract
without convoy knowing who reads it.

**Additive can still be consumer-affecting.** A new telemetry event, a new
optional field, a new `outcome` value, a new `error_kind` value, a new process
exit code, or a new series.toml key is additive — it bumps no `schema_version` and an older reader keeps
working — but a consumer that *branches on* the taxonomy (an exit code → a retry
policy, an `outcome` → a scoring rule) silently mis-handles the new value until it
is taught about it. So every such addition is called out in `CHANGELOG.md` as
**consumer-affecting**, and any engine-agnostic contract that mirrors this taxonomy
is updated in lockstep — the addition is an explicit signal to sync downstream
engines, not a silent superset they must notice on their own. The `outcome="budget"`
/ exit `4` addition is the worked example: additive here, yet a driving consumer that
only knew codes 0–3 had to learn code 4 before it could classify a spend-cap halt.

## Open decisions

1. **`model` vs `tier` — resolved: accept either, resolved during governance.**
   `[governance]` (and now each `[[prs]]` table) accepts a concrete `model` string or
   an abstract `tier` (weak/mid/strong/frontier); `model` wins if both are set, a `tier`
   resolves to a model during governance resolution, and the resolved model is recorded
   as `effective_model` in telemetry. The vocabulary is load-bearing per PR: a per-PR
   `tier` routes that PR through the tier→model table independently of the series.
2. **Independent-check asset home — resolved: a committable `oracles/` directory.**
   The scaffold (`convoy init`, `interface/scaffold.py`) and the reference skill
   place oracle assets in an `oracles/` directory under the series root, a sibling
   of the scored `workspace/` subdirectory — so the oracle commits and travels
   with the series' own assets while still living outside the scored workspace,
   and the fail-closed containment check holds unchanged. The worked example
   above follows this layout. Isolation is still enforced by containment and
   existence (see [01-gate.md](01-gate.md)), not by a read-only mount or a
   permission exclusion, and absolute out-of-tree paths anywhere remain accepted
   (the scaffold itself records the oracle's absolute path in the emitted
   `series.toml`).
