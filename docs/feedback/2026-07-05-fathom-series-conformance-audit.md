# convoy feedback — series-engine contract conformance audit (from fathom)

- **Date:** 2026-07-05
- **Source:** a fathom polish session that ran a clause-by-clause conformance audit of the
  engine-agnostic series contract (`fathom/docs/specs/2026-07-03-series-engine-contract.md`, which
  fathom owns) against convoy as the reference producer. convoy accessed **read-only** (source read +
  driven headless via fathom's token-free `claude` shim in `fathom smoke`).
- **Headline: convoy conforms.** Every load-bearing clause verified against convoy source and a real
  engine-boundary run:
  - **§2 invocation** — `convoy run <series.toml>` exists (`interface/cli.py`), honors `cwd` and the
    isolated `CLAUDE_CONFIG_DIR`, and the real smoke run confirmed convoy spawns `claude` with
    **`--permission-mode default`** (never `--dangerously-skip-permissions` / `bypassPermissions`).
  - **§3 series.toml** — the round-trip schema (`[[prs]]` with `id`/`branch`/`prompt`/`phase`/
    `depends_on`, `[branches]`, `[governance.budgets]` as numbers) matches what fathom regenerates;
    `core/spec.py` `_FORBIDDEN_PR_KEYS` correctly rejects per-PR `model`/`tier`/`effort`/`budget`.
  - **§5 telemetry** — `spawns.jsonl` field names (`spawn_complete`, `role`, `input_tokens`,
    `output_tokens`, `num_turns`, `duration_s`, `cost_usd`, `effective_model`) match fathom's parser;
    the `cost_estimated` subscription fallback is present.
  - **§7 exit codes** — convoy emits 0/1/2/3 as specified **and** a fifth, `EXIT_BUDGET=4` /
    `run_complete outcome="budget"` with `integrated=False` (`interface/drivers/headless.py`),
    documented in convoy `docs/design/02-formats.md`. convoy behaves correctly here; the gap was on
    the **consumer** side — fathom's `_classify` and the contract only enumerated 0/1/2/3 and dropped
    exit 4 into an opaque errored bucket. **Fixed on fathom's side this session** (fathom PR #2): the
    contract now enumerates exit 4 / outcome "budget", and `_classify` records it as a non-scored,
    re-runnable budget halt. No convoy change is required for this.

## Proposals

1. **[LOW — coordination] Flag consumer-affecting protocol additions.** convoy correctly added
   `EXIT_BUDGET=4` / `outcome="budget"` and documented it in `02-formats.md`, but a downstream
   consumer that keys on the exit-code taxonomy (fathom, or any tool driving convoy as an engine) can
   silently mis-handle a new code until it notices. Consider marking such additions in the CHANGELOG as
   **consumer-affecting** (or cross-referencing the engine-agnostic contract), so a new exit
   code / outcome / telemetry field is an explicit signal to sync consumers, not a silent superset.
   Home: `CHANGELOG.md` convention / `docs/design/02-formats.md` header note.

## Cost (economy — no model spend from this audit)

| activity | model spend | note |
|---|---|---|
| convoy source read (read-only) | $0 | conformance verified by reading `interface/`, `core/spec.py`, `core/governance.py`, `core/pricing.py`, `docs/design/02-formats.md` |
| `convoy run` via fathom `smoke` shim | $0 | the shim shadows `claude` with a token-free recorder; convoy ran, spawned the shim, and recorded argv — no model tokens spent |
| **total** | **$0** | a paid convoy engine run was neither needed nor performed for the conformance audit |
