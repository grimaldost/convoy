"""Tests for the Reporter seam: StderrReporter formatting and NullReporter silence.

Also defines :class:`RecordingReporter`, imported by the driver tests to assert the exact
sequence of reporter hooks a run fires.
"""

import io
from dataclasses import dataclass, field

from convoy.core.gate import CheckResult, GateVerdict, decide
from convoy.core.spec import Check
from convoy.interface.reporter import NullReporter, Reporter, StderrReporter
from convoy.interface.spawn import SpawnResult, ok_result


@dataclass
class RecordingReporter:
    """A :class:`Reporter` that records ``(hook, *args)`` tuples for sequence assertions."""

    calls: list[tuple[object, ...]] = field(default_factory=list)

    def run_start(self, series_id: str, run_id: str, n_prs: int) -> None:
        self.calls.append(('run_start', series_id, run_id, n_prs))

    def spawn_done(self, pr_id: str, role: str, result: SpawnResult) -> None:
        self.calls.append(('spawn_done', pr_id, role))

    def gate_result(self, pr_id: str, attempt: int, verdict: GateVerdict) -> None:
        self.calls.append(('gate_result', pr_id, attempt, verdict.blocking_red))

    def fix_attempt(self, pr_id: str, attempt: int, max_attempts: int) -> None:
        self.calls.append(('fix_attempt', pr_id, attempt, max_attempts))

    def pr_skipped(self, pr_id: str, reason: str) -> None:
        self.calls.append(('pr_skipped', pr_id, reason))

    def integrated(self, pr_id: str) -> None:
        self.calls.append(('integrated', pr_id))

    def run_done(self, outcome: str, integrated: bool) -> None:
        self.calls.append(('run_done', outcome, integrated))

    def names(self) -> list[str]:
        """The hook names in call order."""
        return [str(call[0]) for call in self.calls]


def _verdict(*, passed: bool, detail: str = '', name: str = 'suite') -> GateVerdict:
    check = Check(name=name, run='x', blocking=True)
    return decide([CheckResult(check=check, passed=passed, detail=detail)])


def test_run_start_line() -> None:
    buf = io.StringIO()
    StderrReporter(buf).run_start('demo', 'run-1', 2)
    assert buf.getvalue() == 'convoy: demo run-1  (2 PRs)\n'


def test_run_start_uses_singular_for_one_pr() -> None:
    buf = io.StringIO()
    StderrReporter(buf).run_start('demo', 'run-1', 1)
    assert '(1 PR)' in buf.getvalue()


def test_spawn_done_line_shows_role_class_and_cost() -> None:
    buf = io.StringIO()
    StderrReporter(buf).spawn_done('pr-1', 'implementation', ok_result(cost_usd=0.039))
    out = buf.getvalue()
    assert '[pr-1]' in out
    assert 'impl' in out
    assert 'ok' in out
    assert '$0.0390' in out


def test_gate_pass_line() -> None:
    buf = io.StringIO()
    StderrReporter(buf).gate_result('pr-1', 0, _verdict(passed=True))
    out = buf.getvalue()
    assert 'PASS' in out
    assert 'attempt 0' in out


def test_gate_fail_line_shows_check_name_and_detail() -> None:
    buf = io.StringIO()
    StderrReporter(buf).gate_result('pr-1', 1, _verdict(passed=False, detail='exited 1: boom'))
    out = buf.getvalue()
    assert 'FAIL' in out
    assert 'suite' in out
    assert 'boom' in out


def test_gate_fail_truncates_a_long_detail() -> None:
    buf = io.StringIO()
    StderrReporter(buf).gate_result('pr-1', 0, _verdict(passed=False, detail='x' * 500))
    out = buf.getvalue()
    assert '...' in out
    assert len(out) < 300


def test_fix_attempt_line() -> None:
    buf = io.StringIO()
    StderrReporter(buf).fix_attempt('pr-1', 1, 2)
    assert '1/2' in buf.getvalue()


def test_pr_skipped_line() -> None:
    buf = io.StringIO()
    reason = 'series halted at pr-a (blocked) before this PR started'
    StderrReporter(buf).pr_skipped('pr-b', reason)
    out = buf.getvalue()
    assert 'pr-b' in out
    assert 'skipped' in out
    assert reason in out


def test_integrated_line() -> None:
    buf = io.StringIO()
    StderrReporter(buf).integrated('pr-1')
    assert '[pr-1] integrated' in buf.getvalue()


def test_run_done_completed_is_marked_integrated() -> None:
    buf = io.StringIO()
    StderrReporter(buf).run_done('completed', True)
    assert 'COMPLETED (integrated)' in buf.getvalue()


def test_run_done_blocked_is_not_marked_integrated() -> None:
    buf = io.StringIO()
    StderrReporter(buf).run_done('blocked', False)
    out = buf.getvalue()
    assert 'BLOCKED' in out
    assert 'integrated' not in out


def test_null_reporter_writes_nothing_and_never_raises() -> None:
    reporter: Reporter = NullReporter()
    reporter.run_start('s', 'r', 1)
    reporter.spawn_done('p', 'implementation', ok_result())
    reporter.gate_result('p', 0, _verdict(passed=True))
    reporter.fix_attempt('p', 1, 2)
    reporter.pr_skipped('p', 'x')
    reporter.integrated('p')
    reporter.run_done('completed', True)
