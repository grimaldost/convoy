"""Smoke tests for the convoy scaffold."""

from typer.testing import CliRunner

from convoy import __version__
from convoy.interface.cli import app


def test_version_is_nonempty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_cli_version_flag() -> None:
    result = CliRunner().invoke(app, ['--version'])
    assert result.exit_code == 0
    assert __version__ in result.stdout
