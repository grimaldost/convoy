"""convoy command-line interface."""

import os
from collections.abc import Mapping
from pathlib import Path

import typer

from convoy import __version__
from convoy.core.governance import GovernanceError
from convoy.core.spec import Series, SpecError, load_series
from convoy.interface.drivers.headless import EXIT_USAGE, format_problems, make_run_id
from convoy.interface.git import GitError
from convoy.interface.preflight_probe import preflight
from convoy.interface.reporter import NullReporter, Reporter, StderrReporter
from convoy.interface.run_service import PreflightError, run_series_headless
from convoy.interface.scaffold import ScaffoldError, scaffold

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
        return load_series(series_file.read_text())
    except (OSError, SpecError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc


@app.command()
def validate(series_file: Path) -> None:
    """Validate a series without running it: structure, model resolution, paths, gate isolation."""
    series = _load_or_exit(series_file)
    problems = preflight(series, Path.cwd())
    if problems:
        typer.echo(format_problems(problems), err=True)
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
) -> None:
    """Run a convoy series headless."""
    series = _load_or_exit(series_file)
    try:
        outcome = run_series_headless(
            series,
            Path.cwd(),
            run_id=make_run_id(),
            config_isolation=not _isolation_disabled(os.environ, no_config_isolation),
            reporter=_select_reporter(quiet),
        )
    except PreflightError as exc:
        # A misconfigured series fails fast and whole, before any git mutation or spawn.
        typer.echo(format_problems(exc.problems), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except (GovernanceError, GitError, OSError) as exc:
        # A resolvable-only-at-runtime misconfiguration, or a git / filesystem failure, must
        # not escape as a traceback and must not collide with EXIT_BLOCKED — map to EXIT_USAGE.
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    raise typer.Exit(outcome.exit_code)


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
    app()


if __name__ == '__main__':
    main()
