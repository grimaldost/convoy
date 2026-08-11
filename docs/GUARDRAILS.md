# Guardrails

Non-negotiable invariants for every change. Each rule names what enforces it —
a rule without a mechanical enforcer is marked as review-enforced and is a
candidate for mechanization, not an aspiration.

### The core stays pure

`src/convoy/core/` may not import from `src/convoy/interface/` (no I/O, no
subprocess, no filesystem in core).

*Why:* the engine's decisions — spec validity, DAG order, gate verdicts,
governance, pricing — must be testable without a git repo, a spawned agent, or a
filesystem, and reusable behind any surface.

*Enforced by:* `tests/test_architecture.py` (AST walk over `core/`; fails on any
`convoy.interface` import).

### Every text boundary pins UTF-8

Subprocess output, file reads, and the entry-point std streams decode/encode
UTF-8 explicitly (with `replace` where degrading beats halting) — never the
platform locale default.

*Why:* the locale default is cp1252 on Windows; one agent-produced byte in
`{0x81, 0x8D, 0x8F, 0x90, 0x9D}` killed a production run after its green PRs.

*Enforced by:* the `PLW1514` (unspecified-encoding) ruff rule in `pyproject.toml`;
one decode policy — `TEXT_ENCODING`/`TEXT_ERRORS`, defined in `interface/proc.py`
(two spawn sites still carry matching literals; folding them onto the constants
is a cleanup candidate);
`interface/streams.py::harden_std_streams` at both entry points, with
`tests/test_streams.py` and the ≥0x80-byte regression tests.

### No test reaches a real spawn or seat probe

The unit suite must never launch a real coding-agent subprocess or spend money,
on any machine.

*Why:* a live seat silently turned five CLI tests into five real spawns per suite
pass; on a seatless CI runner the same tests failed. Runtime is a regression
signal, but read it through `--durations`, not a wall-clock ceiling: the total is
too noisy to threshold — 359 tests took 54 s, 57 s, 70 s and 73 s across four
runs of one clean commit (2026-07-25, warm developer machine). The "~28 s, a jump
to ~70 s" this file carried was measured at 0.1.2 and the suite outgrew it, so
the alarm value fell inside the normal band: the last of those clean runs would
have tripped it. A leaked spawn is instead a **single** test taking seconds to
minutes, obvious in `uv run pytest --durations=12` against a suite whose slowest
cases are the deliberate subprocess-timeout tests at ~1–3 s. Re-measure the band
when quoting it; a bare number here rots as the suite grows.

*Enforced by:* the autouse guard in `tests/conftest.py` makes the real seat
probe unreachable by default (wiring tests override it explicitly); the spawn
path itself is stubbed per test by convention — review-enforced, a
mechanization candidate.

### Every subprocess is hermetic

No child inherits the caller's stdin — `stdin=DEVNULL` at every subprocess site
except the agent spawn, which gets a dedicated pipe closed at launch — and every
git invocation carries the hermetic flags (`core.fsmonitor=false`,
`maintenance.auto=false`, `gc.auto=0`).

*Why:* under a stdio MCP server, a child that inherits the JSON-RPC stdin — or a
git background daemon holding an inherited pipe — hangs the client forever.

*Enforced by:* per-site discipline at the four launch sites (`interface/proc.py`
for gate checks and the kill helper, `interface/git.py`, `interface/scaffold.py`,
`interface/headless_spawn.py`), verified end-to-end by
`tests/test_mcp_stdio_integration.py`, which drives the tools over a real stdio
server subprocess and asserts they return.

### Scored spawns run under config isolation

A spawned agent runs with a credential-only configuration by default — the
operator's hooks, memory, and skills must not leak into a scored run.

*Why:* the run's economy and gate outcomes are measurements; an operator-local
config contaminates them and makes runs non-reproducible across machines.

*Enforced by:* `interface/config_isolation.py` + `tests/test_config_isolation.py`;
disabling it is an explicit, per-run flag (`--no-config-isolation` /
`config_isolation=false`).

### Telemetry is append-only and versioned

`spawns.jsonl` is only ever appended, carries `schema_version`, and any addition
to a protocol a consumer keys on — exit codes, `outcome`/`error_kind` values,
events, fields, series.toml keys — gets the **(consumer-affecting)** CHANGELOG
marker even when additive.

*Why:* consumers reconstruct runs from the ledger after the fact; a silent
protocol addition mis-handles instead of failing loud.

*Enforced by:* convention in `docs/design/02-formats.md` + the PR checklist
(review-enforced; mechanization candidate).

### A shipped document does not contradict the shipped engine

The names the code publishes — the MCP tools, the CLI verbs, the `convoy_run`
arguments — appear in the documents that promise to list them, and a stated tool
count matches the real one.

*Why:* the manual said "there is no resume" for three releases after `--resume`
shipped and was documented 300 lines above it; `convoy_status` was registered but
unadvertised in `marketplace.json` for three releases; `convoy clean` appeared zero
times in the manual, which cost two operators a hand-deleted branch the engine
already deletes. The class recurred three times and both earlier fixes were prose.

*Enforced by:* `tests/test_doc_claims.py` — deliberately narrow, pinning only the
claims that have actually drifted, and carrying its own non-vacuity guard. The
conflict rule itself ("if docs and code diverge, code wins") stays review-enforced
in `AGENTS.md`; this fails on the part of it that is mechanical.

### The repo stays self-contained

No references to any other tool or project in code or docs; feedback reports and
triage passes stay untracked (`docs/feedback/.gitignore`), while decisions
(`docs/adr/`) and the improvement ledger (`docs/backlog.md`) are tracked.

*Why:* convoy is general-purpose infrastructure; names of surrounding tools are
coupling, and raw reflection streams are session noise that rots — the promoted
output is what deserves history.

*Enforced by:* `docs/feedback/.gitignore` for the tracking split; the PR checklist
for the no-references rule (review-enforced).
