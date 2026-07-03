"""Human-readable progress narration for a headless run (shell).

The driver writes machine telemetry to ``spawns.jsonl``; this Reporter narrates the same
moments to a human on stderr, so an operator watching a run sees what happened without
tailing the JSONL. stdout stays clean for any future machine output. Silence is the
:class:`NullReporter` (the default, and what ``--quiet`` selects); the default
:class:`StderrReporter` prints one concise line per event.
"""

import sys
from typing import Protocol, TextIO

from convoy.core.gate import GateVerdict
from convoy.interface.spawn import SpawnResult

# The most of a failing check's detail to echo on one line (the full detail is in telemetry).
_DETAIL_MAX = 200


class Reporter(Protocol):
    """A sink the driver calls at each notable step of a run. Every method is side-effecting."""

    def run_start(self, series_id: str, run_id: str, n_prs: int) -> None: ...
    def spawn_done(self, pr_id: str, role: str, result: SpawnResult) -> None: ...
    def gate_result(self, pr_id: str, attempt: int, verdict: GateVerdict) -> None: ...
    def fix_attempt(self, pr_id: str, attempt: int, max_attempts: int) -> None: ...
    def pr_skipped(self, pr_id: str, reason: str) -> None: ...
    def integrated(self, pr_id: str) -> None: ...
    def run_done(self, outcome: str, integrated: bool) -> None: ...


class NullReporter:
    """A :class:`Reporter` that says nothing — the default, and what ``--quiet`` selects."""

    def run_start(self, series_id: str, run_id: str, n_prs: int) -> None: ...
    def spawn_done(self, pr_id: str, role: str, result: SpawnResult) -> None: ...
    def gate_result(self, pr_id: str, attempt: int, verdict: GateVerdict) -> None: ...
    def fix_attempt(self, pr_id: str, attempt: int, max_attempts: int) -> None: ...
    def pr_skipped(self, pr_id: str, reason: str) -> None: ...
    def integrated(self, pr_id: str) -> None: ...
    def run_done(self, outcome: str, integrated: bool) -> None: ...


_ROLE_LABEL = {'implementation': 'impl', 'review': 'review', 'fix': 'fix'}


class StderrReporter:
    """A :class:`Reporter` printing one concise line per event to a stream (stderr by default)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def _line(self, text: str) -> None:
        self._stream.write(text + '\n')
        self._stream.flush()

    def run_start(self, series_id: str, run_id: str, n_prs: int) -> None:
        suffix = 'PR' if n_prs == 1 else 'PRs'
        self._line(f'convoy: {series_id} {run_id}  ({n_prs} {suffix})')

    def spawn_done(self, pr_id: str, role: str, result: SpawnResult) -> None:
        label = _ROLE_LABEL.get(role, role)
        economy = result.economy
        self._line(
            f'[{pr_id}] {label:<6} {result.classification:<6} '
            f'${economy.cost_usd:.4f}  {economy.num_turns} turns  {economy.duration_s:.1f}s'
        )

    def gate_result(self, pr_id: str, attempt: int, verdict: GateVerdict) -> None:
        if verdict.blocking_red:
            failed = next((r for r in verdict.results if not r.passed and r.check.blocking), None)
            detail = f'{failed.check.name}: {failed.detail}' if failed is not None else ''
            if len(detail) > _DETAIL_MAX:
                detail = detail[: _DETAIL_MAX - 3] + '...'
            self._line(f'[{pr_id}] gate   FAIL   {detail}')
        else:
            count = len(verdict.results)
            checks = 'check' if count == 1 else 'checks'
            self._line(f'[{pr_id}] gate   PASS   ({count} {checks}, attempt {attempt})')

    def fix_attempt(self, pr_id: str, attempt: int, max_attempts: int) -> None:
        self._line(f'[{pr_id}] fix    {attempt}/{max_attempts}')

    def pr_skipped(self, pr_id: str, reason: str) -> None:
        self._line(f'[{pr_id}] skipped  {reason}')

    def integrated(self, pr_id: str) -> None:
        self._line(f'[{pr_id}] integrated')

    def run_done(self, outcome: str, integrated: bool) -> None:
        tag = ' (integrated)' if integrated else ''
        self._line(f'convoy: {outcome.upper()}{tag}')
