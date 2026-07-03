# convoy — working conventions

convoy is a governed, measurable multi-PR execution engine. Self-contained and
general-purpose; **no references to any other tool** in code or docs.

## Commands

```
uv sync                                              # install deps
uv run ruff check src tests && uv run ruff format --check src tests   # lint + format
uv run ty check src                                  # type check
uv run pytest                                        # tests
```

## Architecture

Application layout, functional core / imperative shell:

- `src/convoy/core/` — pure, no I/O (spec, dag, gate verdict, governance,
  telemetry model, pricing).
- `src/convoy/interface/` — adapters behind `Protocol` ports (cli, spawn,
  gate_runner, git, telemetry_writer, drivers).

`core/` imports nothing from `interface/`.

## Style

- Python 3.14; single quotes for code, double quotes for docstrings.
- `typing.Protocol` for seams; type everything (ty must pass).
- Tests in top-level `tests/`, never in `src/`.

Design: `docs/design/00-overview.md`, `01-gate.md`, `02-formats.md`.
Build plan: `docs/plans/v1-build-plan.md`.
