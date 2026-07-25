"""convoy command-line interface."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import typer

from convoy import __version__
from convoy.core.governance import GovernanceError
from convoy.core.spec import Series, SpecError, load_series
from convoy.interface.drivers.headless import (
    EXIT_USAGE,
    format_advisories,
    format_problems,
    make_run_id,
)
from convoy.interface.git import Git, GitError
from convoy.interface.preflight_probe import preflight
from convoy.interface.reporter import NullReporter, Reporter, StderrReporter
from convoy.interface.run_service import PreflightError, run_series_headless
from convoy.interface.scaffold import ScaffoldError, scaffold
from convoy.interface.streams import harden_std_streams
from convoy.interface.workspace_lock import WorkspaceBusyError, lock_path, remove_stale_lock

app = typer.Typer(
    help='Governed, measurable multi-PR execution engine.',
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def root(
    version: bool = typer.Option(
        False,
        '--version',
        callback=_version_callback,
        is_eager=True,
        help='Show the convoy version and exit.',
    ),
) -> None:
    """convoy — governed, measurable multi-PR execution."""


def _load_or_exit(series_file: Path) -> Series:
    """Read and structurally parse ``series_file``, or exit ``EXIT_USAGE`` with a message."""
    try:
        return load_series(series_file.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, SpecError) as exc:
        # UnicodeDecodeError: the read is pinned to UTF-8, so a legacy-encoded file is a
        # usage error like malformed TOML — never an uncaught traceback.
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc


_WORKSPACE_HELP = (
    'The git repository to operate on (the scored tree). Defaults to the current '
    'directory, which is what the workspace was implicitly before this option existed.'
)


def _workspace_or_exit(workspace: Path | None) -> Path:
    """Resolve the workspace — ``--workspace`` when given, else the cwd — or exit ``EXIT_USAGE``.

    Resolved at call time, never at import: a module-level ``Path.cwd()`` default would
    freeze whatever directory the process started in. A path that is not an existing
    directory fails here with one located message, rather than surfacing later as a
    confusing git or filesystem error against a tree that was never there.
    """
    resolved = Path.cwd() if workspace is None else workspace
    if not resolved.is_dir():
        typer.echo(f'workspace is not an existing directory: {resolved}', err=True)
        raise typer.Exit(EXIT_USAGE)
    return resolved


@app.command()
def validate(
    series_file: Path,
    workspace: Annotated[
        Path | None, typer.Option('--workspace', '-w', help=_WORKSPACE_HELP)
    ] = None,
) -> None:
    """Validate a series without running it: structure, model resolution, paths, gate isolation.

    The filesystem checks — ``[paths]`` existence, ``outputs`` out-of-tree, and
    independent-check asset isolation — are evaluated against ``--workspace`` (default:
    the current directory), so validate against the same tree you will run against.

    Advisories (a PR that phase-scoped checks leave ungated) print to stderr and do NOT
    change the exit code: stdout stays ``ok`` and the exit stays 0, because an advisory
    describes an unusual series, not an invalid one.
    """
    series = _load_or_exit(series_file)
    report = preflight(series, _workspace_or_exit(workspace))
    if report.advisories:
        typer.echo(format_advisories(report.advisories), err=True)
    if not report.clean:
        typer.echo(format_problems(report.problems), err=True)
        raise typer.Exit(EXIT_USAGE)
    typer.echo('ok')


def _select_reporter(quiet: bool) -> Reporter:
    """Silence progress with ``--quiet``; otherwise narrate to stderr (stdout stays clean)."""
    return NullReporter() if quiet else StderrReporter()


def _isolation_disabled(environ: Mapping[str, str], flag: bool) -> bool:
    """True when credential-only config isolation is turned off.

    Off when ``--no-config-isolation`` is passed, or when ``CONVOY_NO_CONFIG_ISOLATION`` is a
    truthy environment value.
    """
    if flag:
        return True
    return environ.get('CONVOY_NO_CONFIG_ISOLATION', '').strip().lower() in {
        '1',
        'true',
        'yes',
        'on',
    }


@app.command()
def run(
    series_file: Path,
    quiet: bool = typer.Option(
        False, '--quiet', '-q', help='Silence progress narration (which is written to stderr).'
    ),
    no_config_isolation: bool = typer.Option(
        False,
        '--no-config-isolation',
        help='Run the agent under the operator config instead of an isolated credential-only one.',
    ),
    fresh: bool = typer.Option(
        False,
        '--fresh',
        help=(
            'Reset the workspace to base and delete prior integration/PR branches before '
            'running, so a completed or halted run can be re-run cleanly.'
        ),
    ),
    resume: Annotated[
        bool,
        typer.Option(
            '--resume',
            help=(
                'Continue the existing integration branch, skipping every PR whose work '
                'it already contains, so a halted run does not re-spend on PRs that '
                'already gated green. Mutually exclusive with --fresh.'
            ),
        ),
    ] = False,
    workspace: Annotated[
        Path | None, typer.Option('--workspace', '-w', help=_WORKSPACE_HELP)
    ] = None,
) -> None:
    """Run a convoy series headless."""
    series = _load_or_exit(series_file)
    target = _workspace_or_exit(workspace)
    try:
        outcome = run_series_headless(
            series,
            target,
            run_id=make_run_id(),
            config_isolation=not _isolation_disabled(os.environ, no_config_isolation),
            reporter=_select_reporter(quiet),
            fresh=fresh,
            resume=resume,
        )
    except PreflightError as exc:
        # A misconfigured series fails fast and whole, before any git mutation or spawn.
        typer.echo(format_problems(exc.problems), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except WorkspaceBusyError as exc:
        # Another run already holds the workspace lock — fail loud, not a traceback.
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except (GovernanceError, GitError, OSError) as exc:
        # A resolvable-only-at-runtime misconfiguration, or a git / filesystem failure, must
        # not escape as a traceback and must not collide with EXIT_BLOCKED — map to EXIT_USAGE.
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    raise typer.Exit(outcome.exit_code)


def _clean_plan(git: Git, series: Series, workspace: Path) -> list[str]:
    """What ``clean`` would do to ``workspace``, one human line per item.

    Enumerated from git's stable porcelain status and ref existence, never from parsing
    ``git clean``'s prose output, so the preview means the same thing under any locale.
    """
    lines: list[str] = []
    # One status read: two reads could disagree and report a plan that never existed.
    status = git.status_porcelain()
    modified = [entry for entry in status if not entry.startswith('??')]
    untracked = [entry[3:] for entry in status if entry.startswith('??')]
    if modified:
        lines.append(f'discard {len(modified)} uncommitted change(s) to tracked files')
        lines += [f'    {entry}' for entry in modified]
    if untracked:
        lines.append(f'delete {len(untracked)} untracked path(s)')
        lines += [f'    {path}' for path in untracked]
    # Only when it is actually a change: listing an unconditional "check out base" would
    # make the plan never empty, and "already clean" unreachable.
    if git.current_branch() != series.branches.base:
        lines.append(f'check out base branch {series.branches.base!r}')
    existing = [
        branch
        for branch in (series.branches.integration, *(pr.branch for pr in series.prs))
        if git.branch_exists(branch)
    ]
    if existing:
        lines.append(f'delete {len(existing)} series branch(es)')
        lines += [f'    {branch}' for branch in existing]
    if lock_path(workspace).exists():
        lines.append(f'remove the run lock ({lock_path(workspace)})')
    return lines


@app.command()
def clean(
    series_file: Path,
    workspace: Annotated[
        Path | None, typer.Option('--workspace', '-w', help=_WORKSPACE_HELP)
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            '--dry-run',
            '-n',
            help='Print what would be done and change nothing. Do this first.',
        ),
    ] = False,
) -> None:
    """Reset a workspace to the series' base branch after a halted or killed run.

    DESTRUCTIVE AND UNRECOVERABLE. In order: discard uncommitted changes to tracked
    files, delete untracked files and directories (ignored files are kept), check out
    the base branch, delete the series' integration and PR branches, and remove a stale
    run lock. Use ``--dry-run`` first to see exactly what that means for this workspace.

    This is the recovery path, deliberately separate from ``run --fresh``: it starts no
    run, so it takes no workspace lock and pays for no seat probe — which is precisely
    why ``--fresh`` cannot serve it, since ``--fresh`` acquires the lock and probes the
    seat before it ever resets anything. Recovering by hand was otherwise the only
    option, and one campaign needed it five times.
    """
    series = _load_or_exit(series_file)
    target = _workspace_or_exit(workspace)
    git = Git(target)
    removed_lock = False
    try:
        plan = _clean_plan(git, series, target)
        if dry_run:
            typer.echo(f'would clean {target}:' if plan else f'{target} is already clean')
            for line in plan:
                typer.echo(f'  {line}')
            return
        git.discard_changes()
        git.clean_untracked()
        git.reset_to_base(
            series.branches.base,
            [series.branches.integration, *(pr.branch for pr in series.prs)],
        )
        removed_lock = remove_stale_lock(target)
    except GitError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    for line in plan:
        typer.echo(line)
    if removed_lock:
        typer.echo('removed the run lock')
    typer.echo(f'clean: {target} is on {series.branches.base!r}')


@app.command()
def init(
    directory: Path = typer.Argument(
        Path('.'), help='Directory to scaffold the starter series into.'
    ),
) -> None:
    """Scaffold a runnable starter series (series.toml, a prompt, an oracle, a git workspace)."""
    try:
        written = scaffold(directory)
    except (OSError, ScaffoldError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    for path in written:
        typer.echo(f'created {path}')
    typer.echo(f'next: cd {directory / "workspace"} && convoy run {directory / "series.toml"}')


def main() -> None:
    """Console-script entry point."""
    harden_std_streams()
    app()


if __name__ == '__main__':
    main()
