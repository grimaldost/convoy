"""The telemetry writer — the only place spawn telemetry touches disk (shell).

Appends serialized events to the ``spawns.jsonl`` file under ``[paths].outputs``. The
file is append-only: a reused ``outputs`` dir stays safe because a consumer selects the
most-recent ``run_id`` (see ``docs/design/02-formats.md``). Serialization lives in the
pure ``core.telemetry`` module; this adapter only owns the I/O.
"""

from pathlib import Path

from convoy.core.telemetry import Event, to_json_line


class TelemetryWriter:
    """Appends events to a JSON-lines file, one object per line."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, event: Event) -> None:
        """Append ``to_json_line(event)`` plus a newline, creating parents as needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open('a', encoding='utf-8') as handle:
            handle.write(to_json_line(event) + '\n')
