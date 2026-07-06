"""Tests for std-stream hardening at the process entry points."""

import io
import sys

import pytest

from convoy.interface.streams import harden_std_streams


def test_unencodable_narration_degrades_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After hardening, text the stream's charmap cannot encode is written, not raised.

    Agent- and gate-produced text (check marks, emoji) flows through convoy's own
    narration; under a redirected cp1252 stream an unhardened ``print`` raises
    ``UnicodeEncodeError`` and kills the run.
    """
    out_buffer = io.BytesIO()
    err_buffer = io.BytesIO()
    monkeypatch.setattr(sys, 'stdout', io.TextIOWrapper(out_buffer, encoding='cp1252'))
    monkeypatch.setattr(sys, 'stderr', io.TextIOWrapper(err_buffer, encoding='cp1252'))

    harden_std_streams()
    print('gate ✓ passed', file=sys.stdout)
    print('fix ѐ brief', file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    assert 'gate ✓ passed' in out_buffer.getvalue().decode('utf-8')
    assert 'fix ѐ brief' in err_buffer.getvalue().decode('utf-8')


def test_streams_without_reconfigure_are_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """A replaced stream lacking ``reconfigure`` (StringIO, a capture shim) is tolerated."""
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    monkeypatch.setattr(sys, 'stderr', io.StringIO())

    harden_std_streams()  # must simply no-op, not raise
