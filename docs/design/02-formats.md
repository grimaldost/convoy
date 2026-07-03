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
| `[governance]` | `model` (or `tier`), `effort`, `permission_mode`, `timeout_seconds` | Per-spawn governance, pinned per phase |
| `[governance.budgets]` | `implementation`, `review`, `fix` | USD ceiling per phase |
| `[governance.tools]` | `implementation`, `review`, `fix` | Tool allow-list per phase |
| `[review]` | `blocking`, `max_fix_attempts` | Review gate + bounded fix loop |
| `[[checks]]` | `name`, `run`, `blocking`, `independent` | The gate — shell checks; `independent = true` marks an author-supplied, implementer-unreachable check (see [01-gate.md](01-gate.md)) |
| `[[prs]]` | `id`, `branch`, `prompt`, `phase`, `depends_on` | The PR decomposition as a DAG |

`permission_mode` ∈ {`default`, `acceptEdits`, `plan`, `bypassPermissions`};
convoy never *forces* `bypassPermissions` (a caller may set it, but governance
resolution defaults to a non-auto-approve mode). `model`/`effort` are
**phase-level** only — there is no per-PR model field, so authoring-time and
runtime cannot disagree about which model runs a PR.

### Worked example

```toml
[series]
id = "add-comparison-ops"
version = "1"

[branches]
base = "convoy/base"
integration = "convoy/integration"

[paths]
prompts = "/abs/assets/prompts"        # outside the scored workspace
outputs = "/abs/assets/outputs"

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

[[checks]]
name = "type-contract"
run = "python /abs/assets/oracles/type_probe.py"   # author-supplied, out-of-tree
blocking = true
independent = true

[[prs]]
id = "pr-1-lexer"
branch = "convoy/pr-1"
prompt = "01-lexer.md"
phase = "core"
depends_on = []

[[prs]]
id = "pr-2-parser"
branch = "convoy/pr-2"
prompt = "02-parser.md"
phase = "core"
depends_on = ["pr-1-lexer"]
```

### Validation (pure) vs. probing (shell)

`spec.py` validates *structure* purely (required fields, types, DAG acyclicity,
`depends_on` references resolve, no per-PR model field). Anything that touches
the filesystem — do `[paths]` exist, is an `independent` check's asset actually
out-of-tree and non-writable — is a **shell** concern (`fs_probe.py`), fed back
into the pure verdict as data. `spec.py` never reads the disk.

## The telemetry — `spawns.jsonl`

An **append-only JSON-lines** file under `[paths].outputs`. One object per line.
This is convoy's economy record and its primary observability surface — designed
so *any* external consumer (a dashboard, a cost report, a blind scorer) can join
on it without convoy knowing about that consumer.

Every line carries `schema_version` and an `event`. v1 defines three events:

| `event` | Emitted | Required fields |
|---|---|---|
| `run_start` | once per `convoy run` | `schema_version`, `event`, `run_id`, `series_id` |
| `spawn_complete` | once per agent spawn | `schema_version`, `event`, `run_id`, `pr_id`, `role`, `exit_code`, `input_tokens`, `output_tokens`, `num_turns`, `duration_s`, `cost_usd`, `effective_model` |
| `run_complete` | once per `convoy run` | `schema_version`, `event`, `run_id`, `outcome`, `integrated` |

- **`run_id`** — a lexicographically-sortable stamp (`%Y%m%dT%H%M%SZ` + short
  suffix) grouping one invocation's events; a reused `outputs` dir stays safe
  because a consumer selects the most-recent `run_id`.
- **`role`** ∈ {`implementation`, `review`, `fix`}.
- **`outcome`** ∈ {`completed`, `blocked`, `infrastructure`} — task success,
  gate-blocked merge, or an infra halt (auth/quota/retry) that is re-runnable.
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

## Versioning discipline

`schema_version` is present on every line from day one. Evolution is
**additive**: a new optional field bumps nothing; a breaking change (rename,
retype, semantic shift of an existing field) bumps `schema_version` and is
documented here. A consumer keys on `event` + `schema_version` and can ignore
unknown fields. This is what lets convoy's telemetry stay a stable contract
without convoy knowing who reads it.

## Open decisions

1. **`model` vs `tier`.** Accept a concrete `model` string, an abstract `tier`
   (weak/mid/strong), or both (tier resolved to a model at load)? *Recommend:*
   accept either; if `tier` is given, resolve it to a model during governance
   resolution and record the resolved `effective_model` in telemetry.
2. **Independent-check asset home.** Absolute out-of-tree path (as shown) vs. a
   committable read-only `oracles/` convention (Overview open-decision 2). The
   example uses absolute paths; the committable convention is the likely v1
   answer and would change the `[[checks]].run` examples.
