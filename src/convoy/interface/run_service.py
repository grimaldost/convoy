"""The request-level headless run service (shell) — the one path the CLI and MCP tool share.

``convoy run`` (the CLI) and the ``convoy_run`` MCP tool both drive a validated series
through the headless engine. This module owns that shared operation: pre-flight the series
(raising :class:`PreflightError` on any problem, before any side effect), create the
telemetry output dir, wrap the scored spawn in credential-only config isolation, wire the
shell adapters, and call ``run_series``. It raises plain exceptions — :class:`PreflightError`
and the engine's ``GovernanceError`` / ``GitError`` / ``OSError`` — rather than exiting, so
each caller maps them to its own surface: the CLI to an exit code, the MCP tool to a
structured result.
"""

from pathlib import Path

from convoy.core.preflight import Problem
from convoy.core.spec import Series
from convoy.interface.config_isolation import isolated_config
from convoy.interface.drivers.headless import RunOutcome, format_problems, run_series
from convoy.interface.gate_runner import SubprocessGateRunner
from convoy.interface.git import Git
from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.preflight_probe import preflight
from convoy.interface.reporter import NullReporter, Reporter
from convoy.interface.telemetry_writer import TelemetryWriter


class PreflightError(Exception):
    """A series failed pre-flight: :attr:`problems` holds every located :class:`Problem`.

    Raised before any side effect (no git mutation, no spawn), so a caller can surface the
    problems and stop with nothing half-executed.
    """

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        super().__init__(format_problems(problems))


def run_series_headless(
    series: Series,
    workspace: Path,
    *,
    run_id: str,
    config_isolation: bool = True,
    reporter: Reporter | None = None,
) -> RunOutcome:
    """Pre-flight then run ``series`` end-to-end in ``workspace``; return its :class:`RunOutcome`.

    Raises :class:`PreflightError` (carrying the located problems) if pre-flight is not
    clean — before any git mutation or spawn. Otherwise creates ``[paths].outputs``, and
    unless ``config_isolation`` is off wraps the scored spawn in a credential-only
    ``CLAUDE_CONFIG_DIR`` (removed on exit, even on error). Propagates the engine's
    ``GovernanceError`` / ``GitError`` / ``OSError`` unchanged.
    """
    problems = preflight(series, workspace)
    if problems:
        raise PreflightError(problems)

    # Create the telemetry output dir before the run. A filesystem failure here (e.g. an
    # ancestor path component is a regular file) surfaces as OSError to the caller, and
    # still precedes every git mutation.
    Path(series.paths.outputs).mkdir(parents=True, exist_ok=True)
    reporter = reporter if reporter is not None else NullReporter()

    def _execute(spawn: HeadlessSpawn) -> RunOutcome:
        return run_series(
            series,
            workspace,
            spawn=spawn,
            git=Git(workspace),
            gate_runner=SubprocessGateRunner(series.governance.timeout_seconds),
            telemetry=TelemetryWriter(Path(series.paths.outputs) / 'spawns.jsonl'),
            run_id=run_id,
            reporter=reporter,
        )

    if not config_isolation:
        # Opt-out: the scored spawn inherits the operator's config dir (pre-isolation behavior).
        return _execute(HeadlessSpawn())
    # Default: a credential-only CLAUDE_CONFIG_DIR so no operator settings, hooks, plugins,
    # or memory leak into the scored spawn. Removed on exit (including on error).
    with isolated_config() as cfg:
        return _execute(HeadlessSpawn(config_dir=cfg.path))
