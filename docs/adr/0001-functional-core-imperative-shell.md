# ADR-0001 — Functional core / imperative shell

## Status

Accepted (founding decision, recorded 2026-07-09).

## Context

convoy's job mixes pure decision-making (is this spec valid, what order does the
DAG dictate, did the gate pass, what did this run cost) with heavy side effects
(spawning coding agents, driving git, writing telemetry, serving MCP). Mixing the
two makes the decisions untestable without a git repo and a paid agent seat, and
couples them to one serving surface.

## Decision

Two packages with a one-way dependency:

- `src/convoy/core/` — pure functions and frozen data: spec, dag, gate verdict,
  governance, telemetry model, pricing, preflight rules. No I/O of any kind.
- `src/convoy/interface/` — everything that touches the world: `typing.Protocol`
  ports where a fake earns its keep (spawn, gate runner, reporter), concrete
  adapters elsewhere (git, telemetry writer), plus the surfaces (CLI, MCP
  server) and the driver that wires them.

`core/` may not import from `interface/`.

## Consequences

- The engine's logic is tested with plain data; the adapters are tested with
  fakes implementing the ports; only a thin integration layer needs a real
  subprocess.
- Both surfaces (CLI and MCP) share one request-level operation instead of
  duplicating engine wiring (see ADR-driven `run_service` extraction,
  docs/design/03-serving.md).
- The boundary is mechanically enforced by `tests/test_architecture.py`; a new
  core module that reaches for I/O fails the suite, not just review.
