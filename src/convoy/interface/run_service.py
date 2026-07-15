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
from convoy.interface.seat_probe import seat_problem
from convoy.interface.telemetry_writer import TelemetryWriter
from convoy.interface.workspace_lock import workspace_lock


class PreflightError(Exception):
    """A series failed pre-flight: :attr:`problems` holds every located :class:`Problem`.

    Raised before any side effect (no git mutation, no scored spawn — the seat probe's
    unmetered micro-spawn is the one exception), so a caller can surface the problems and
    stop with nothing half-executed.
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
    fresh: bool = False,
) -> RunOutcome:
    """Pre-flight then run ``series`` end-to-end in ``workspace``; return its :class:`RunOutcome`.

    Raises :class:`PreflightError` (carrying the located problems) if pre-flight is not
    clean — before any git mutation or scored spawn. After the filesystem pre-flight, a
    **seat probe** (see :mod:`~convoy.interface.seat_probe`) runs a minimal unmetered
    spawn through the same credential/config the run will use, once per distinct model the
    run can spawn on (the ``[governance]`` model plus any per-PR override); an expired or
    capped seat, or a model the seat cannot access, raises :class:`PreflightError` with a
    ``kind='seat'`` problem before the fresh reset or any branch is staged. Otherwise
    creates ``[paths].outputs``, and unless
    ``config_isolation`` is off wraps the scored spawn in a credential-only
    ``CLAUDE_CONFIG_DIR`` (removed on exit, even on error). Propagates the engine's
    ``GovernanceError`` / ``GitError`` / ``OSError`` unchanged.

    When ``fresh`` is true, after a clean pre-flight and before the engine runs, the
    integration branch and every PR branch the series names are deleted and ``workspace``
    is reset onto the series' base branch — so a completed or halted run can be re-run
    without a prior "branch already exists" failure. Off by default: with ``fresh`` false,
    a leftover branch still fails loud exactly as before this option existed.

    Holds an exclusive lock on ``workspace`` (see :mod:`workspace_lock`) from right after a
    clean pre-flight through the end of the run, so a second concurrent run against the same
    workspace raises :class:`~convoy.interface.workspace_lock.WorkspaceBusyError` instead of
    interleaving git operations. Released on both normal return and exception.
    """
    problems = preflight(series, workspace)
    if problems:
        raise PreflightError(problems)

    with workspace_lock(workspace):
        reporter = reporter if reporter is not None else NullReporter()

        def _execute(spawn: HeadlessSpawn) -> RunOutcome:
            # Probe the seat FIRST — through the same spawn (same credential dir) the scored
            # run will use — against every distinct model the run can spawn on, so an expired
            # or capped seat, or a model the seat cannot access, fails the run here, before
            # the fresh reset or any branch is staged. A few unmetered cents of preflight per
            # model, not a scored spawn (see seat_probe).
            problem = seat_problem(spawn, series, workspace)
            if problem is not None:
                raise PreflightError([problem])

            if fresh:
                branches = [series.branches.integration, *(pr.branch for pr in series.prs)]
                Git(workspace).reset_to_base(series.branches.base, branches)

            # Create the telemetry output dir before the run. A filesystem failure here
            # (e.g. an ancestor path component is a regular file) surfaces as OSError to
            # the caller.
            Path(series.paths.outputs).mkdir(parents=True, exist_ok=True)
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
            # Opt-out: the scored spawn inherits the operator's config dir (pre-isolation
            # behavior).
            return _execute(HeadlessSpawn())
        # Default: a credential-only CLAUDE_CONFIG_DIR so no operator settings, hooks,
        # plugins, or memory leak into the scored spawn. Removed on exit (including on error).
        with isolated_config() as cfg:
            return _execute(HeadlessSpawn(config_dir=cfg.path))
