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
pass; on a seatless CI runner the same tests failed. Suite runtime is itself a
regression signal (~28 s; a jump to ~70 s means a real spawn leaked).

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

### The repo stays self-contained

No references to any other tool or project in code or docs; feedback reports and
triage passes stay untracked (`docs/feedback/.gitignore`), while decisions
(`docs/adr/`) and the improvement ledger (`docs/backlog.md`) are tracked.

*Why:* convoy is general-purpose infrastructure; names of surrounding tools are
coupling, and raw reflection streams are session noise that rots — the promoted
output is what deserves history.

*Enforced by:* `docs/feedback/.gitignore` for the tracking split; the PR checklist
for the no-references rule (review-enforced).
