"""convoy command-line interface."""

from pathlib import Path

import typer

from convoy import __version__
from convoy.core.spec import SpecError, load_series
from convoy.interface.drivers.headless import (
    EXIT_USAGE,
    make_run_id,
    run_series,
)
from convoy.interface.gate_runner import SubprocessGateRunner
from convoy.interface.git import Git
from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.telemetry_writer import TelemetryWriter

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


@app.command()
def run(series_file: Path) -> None:
    """Run a convoy series headless."""
    try:
        text = series_file.read_text()
        series = load_series(text)
    except (OSError, SpecError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    workspace = Path.cwd()
    outcome = run_series(
        series,
        workspace,
        spawn=HeadlessSpawn(),
        git=Git(workspace),
        gate_runner=SubprocessGateRunner(series.governance.timeout_seconds),
        telemetry=TelemetryWriter(Path(series.paths.outputs) / 'spawns.jsonl'),
        run_id=make_run_id(),
    )
    raise typer.Exit(outcome.exit_code)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == '__main__':
    main()
