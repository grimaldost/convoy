"""End-to-end tests for the headless driver — the MVE's three arms.

Each arm runs the real driver against a real temp git repo and the real
``SubprocessGateRunner``, driving only the agent spawn with a fake so the loop is
deterministic. The three arms are the de-risking milestone's contract:

* **green** — a passing gate integrates the branch and writes a completed run.
* **red** — a blocking-red gate halts fail-loud without integrating.
* **infra** — an infrastructure-classified spawn halts before the gate even runs.

The gate checks are real shell commands (``python -c 'exit(0|1)'``) built from
the running interpreter so they are portable across platforms.
"""

import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from convoy.core.spec import (
    Branches,
    Budgets,
    Check,
    Governance,
    Paths,
    Review,
    Series,
    Tools,
)
from convoy.interface.drivers.headless import (
    EXIT_BLOCKED,
    EXIT_INFRASTRUCTURE,
    EXIT_OK,
    RunOutcome,
    make_run_id,
    run_series,
)
from convoy.interface.gate_runner import SubprocessGateRunner
from convoy.interface.git import Git
from convoy.interface.spawn import (
    FakeSpawn,
    SpawnEconomy,
    SpawnRequest,
    SpawnResult,
    ok_result,
)
from convoy.interface.telemetry_writer import TelemetryWriter

# A gate check that always passes / always fails, built from the running
# interpreter so it resolves without depending on a bare ``python`` on PATH.
_PASS_CMD = f'"{sys.executable}" -c "exit(0)"'
_FAIL_CMD = f'"{sys.executable}" -c "exit(1)"'

# A gate check that is red until a ``fixed.marker`` file exists in the workspace,
# then green — so a fix spawn that creates the marker can flip a REAL check from
# red to green on re-run. Single-quoted literal inside the double-quoted ``-c``
# argument so it survives ``shell=True`` on both cmd.exe and POSIX shells. The
# path is relative, so it resolves against the workspace the check runs in.
_MARKER_CMD = (
    f'"{sys.executable}" -c "import os,sys; sys.exit(0 if os.path.exists(\'fixed.marker\') else 1)"'
)
_FIX_MARKER = 'fixed.marker'


@dataclass(frozen=True)
class Harness:
    """A staged temp repo plus the series and adapters a run needs."""

    repo: Path
    series: Series
    git: Git
    gate_runner: SubprocessGateRunner
    outputs: Path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True)


def _make_series(repo: Path, check: Check) -> Series:
    prompts = repo / 'prompts'
    outputs = repo / 'outputs'
    return Series(
        id='demo-series',
        version='1',
        branches=Branches(base='base', integration='integration'),
        paths=Paths(prompts=str(prompts), outputs=str(outputs)),
        governance=Governance(
            effort='low',
            permission_mode='default',
            timeout_seconds=60,
            budgets=Budgets(implementation=1.0, review=1.0, fix=1.0),
            tools=Tools(implementation=('Read', 'Edit'), review=(), fix=()),
            model='test-model',
        ),
        review=Review(blocking=True, max_fix_attempts=0),
        checks=(check,),
        prs=(),
    )


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    """Init a temp git repo on a ``base`` branch with a prompt file and a one-check series."""
    repo = tmp_path / 'repo'
    repo.mkdir()

    _git(repo, 'init', '-b', 'base')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test')

    prompts = repo / 'prompts'
    prompts.mkdir()
    (prompts / 'impl.md').write_text('Implement the thing.')

    # A committed file so ``base`` has an initial commit to branch from.
    (repo / 'README.md').write_text('seed\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'seed')

    # The default check passes; individual tests override it.
    series = _make_series(repo, Check(name='green', run=_PASS_CMD, blocking=True))

    return Harness(
        repo=repo,
        series=series,
        git=Git(repo),
        gate_runner=SubprocessGateRunner(series.governance.timeout_seconds),
        outputs=repo / 'outputs',
    )


def _one_pr_series(base: Series) -> Series:
    """A copy of ``base`` carrying a single PR that branches off ``base``."""
    from convoy.core.spec import PR

    return Series(
        id=base.id,
        version=base.version,
        branches=base.branches,
        paths=base.paths,
        governance=base.governance,
        review=base.review,
        checks=base.checks,
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='implementation'),),
    )


def _two_pr_series(base: Series) -> Series:
    """A copy of ``base`` carrying ``pr-a`` and ``pr-b`` where ``pr-b`` depends on ``pr-a``.

    Both PRs use their own prompt file so the fixture can script a distinct marker
    per PR; ``pr-b``'s ``depends_on`` forces the DAG to run ``pr-a`` first and to
    branch ``pr-b`` off ``pr-a``'s already-integrated work.
    """
    from convoy.core.spec import PR

    return Series(
        id=base.id,
        version=base.version,
        branches=base.branches,
        paths=base.paths,
        governance=base.governance,
        review=base.review,
        checks=base.checks,
        prs=(
            PR(id='pr-a', branch='pr-a', prompt='impl-a.md', phase='implementation'),
            PR(
                id='pr-b',
                branch='pr-b',
                prompt='impl-b.md',
                phase='implementation',
                depends_on=('pr-a',),
            ),
        ),
    )


def _read_events(outputs: Path) -> list[dict[str, object]]:
    lines = (outputs / 'spawns.jsonl').read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _events_of(events: Sequence[dict[str, object]], tag: str) -> list[dict[str, object]]:
    return [event for event in events if event.get('event') == tag]


class MarkerSpawn(FakeSpawn):
    """A :class:`FakeSpawn` that also writes a per-PR marker file into the workspace.

    The plain fake writes nothing, so ``git.commit_all`` would find a clean tree
    and integrate an empty branch. This double drops one file per spawn — named
    after the brief's PR — so each PR leaves committable work whose presence on
    the integration branch proves it integrated. It still returns the scripted
    ``ok_result`` s in order and records every call in :attr:`calls` exactly as
    :class:`FakeSpawn` does.
    """

    def __init__(self, results: Sequence[SpawnResult], markers_for: Sequence[str]) -> None:
        super().__init__(results)
        self._markers = list(markers_for)

    def spawn(self, request: SpawnRequest, cwd: Path) -> SpawnResult:
        marker = self._markers[len(self.calls)]
        (cwd / marker).write_text(f'{marker} was here\n')
        return super().spawn(request, cwd)


class FixMarkerSpawn(FakeSpawn):
    """A :class:`FakeSpawn` whose *fix* spawns can flip a real check red→green.

    The implementation spawn (call 0) writes nothing, so the marker-gated check
    (:data:`_MARKER_CMD`) is red after implementation. A fix spawn — recognised by
    the ``## Failing checks to repair`` section the driver appends to the brief —
    creates ``fixed.marker`` in the workspace only when ``fix_creates_marker`` is
    true, so the re-gate goes green. With ``fix_creates_marker`` false the fix
    spawns do real work (they still commit nothing that satisfies the check), so the
    gate stays red and the loop exhausts. Every call returns a scripted result and
    is recorded in :attr:`calls` exactly as :class:`FakeSpawn` does.
    """

    def __init__(self, results: Sequence[SpawnResult], *, fix_creates_marker: bool) -> None:
        super().__init__(results)
        self._fix_creates_marker = fix_creates_marker

    def spawn(self, request: SpawnRequest, cwd: Path) -> SpawnResult:
        is_fix = '## Failing checks to repair' in request.brief
        if is_fix and self._fix_creates_marker:
            (cwd / _FIX_MARKER).write_text('fixed\n')
        return super().spawn(request, cwd)


def test_green_arm_integrates_and_records_completed(harness: Harness) -> None:
    """A passing gate integrates the branch and writes a completed, integrated run."""
    series = _one_pr_series(harness.series)  # default check is _PASS_CMD (blocking)
    spawn = FakeSpawn([ok_result()])

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-green',
    )

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    # Integration branch is left checked out.
    assert harness.git.current_branch() == 'integration'

    events = _read_events(harness.outputs)
    assert len(_events_of(events, 'run_start')) == 1
    assert len(_events_of(events, 'spawn_complete')) == 1

    run_completes = _events_of(events, 'run_complete')
    assert len(run_completes) == 1
    assert run_completes[0]['outcome'] == 'completed'
    assert run_completes[0]['integrated'] is True


def test_red_arm_fails_loud_without_integrating(harness: Harness) -> None:
    """A blocking-red gate halts with the blocked exit code and does not integrate."""
    red_series = _make_series(harness.repo, Check(name='red', run=_FAIL_CMD, blocking=True))
    series = _one_pr_series(red_series)
    spawn = FakeSpawn([ok_result()])

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-red',
    )

    assert outcome == RunOutcome('blocked', False, EXIT_BLOCKED)
    # Not integrated: still on the PR branch, never the integration branch.
    assert harness.git.current_branch() != 'integration'

    events = _read_events(harness.outputs)
    run_completes = _events_of(events, 'run_complete')
    assert len(run_completes) == 1
    assert run_completes[0]['outcome'] == 'blocked'
    assert run_completes[0]['integrated'] is False


def test_infra_arm_halts_before_the_gate(harness: Harness) -> None:
    """An infrastructure-classified spawn halts before the gate runs, with the infra exit code."""
    # The check would ERROR if ever run — it removes the marker sentinel — so a
    # green run_complete plus a surviving sentinel proves the gate never ran.
    sentinel = harness.repo / 'gate-ran.marker'
    sentinel.write_text('present')
    gate_probe = f'"{sys.executable}" -c "import os; os.remove(r\'{sentinel}\')"'
    probe_series = _make_series(harness.repo, Check(name='probe', run=gate_probe, blocking=True))
    series = _one_pr_series(probe_series)

    infra_result = SpawnResult(
        exit_code=1,
        output='auth expired',
        economy=SpawnEconomy(
            input_tokens=0,
            output_tokens=0,
            num_turns=0,
            duration_s=0.0,
            cost_usd=0.0,
            effective_model='test-model',
        ),
        classification='infrastructure',
    )
    spawn = FakeSpawn([infra_result])

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-infra',
    )

    assert outcome == RunOutcome('infrastructure', False, EXIT_INFRASTRUCTURE)
    # The gate never ran: its sentinel-removing probe did not execute.
    assert sentinel.exists()

    events = _read_events(harness.outputs)
    run_completes = _events_of(events, 'run_complete')
    assert len(run_completes) == 1
    assert run_completes[0]['outcome'] == 'infrastructure'
    assert run_completes[0]['integrated'] is False


def _branch_exists(repo: Path, branch: str) -> bool:
    """True if ``branch`` resolves in ``repo`` (``git rev-parse --verify`` succeeds)."""
    result = subprocess.run(
        ['git', 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}'],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_two_pr_series_integrates_both_in_dependency_order(harness: Harness) -> None:
    """A 2-PR series runs pr-a before pr-b and integrates BOTH onto the integration branch."""
    series = _two_pr_series(harness.series)  # default check is _PASS_CMD (blocking)
    # Distinct prompt file per PR so each spawn maps to its own marker.
    (harness.repo / 'prompts' / 'impl-a.md').write_text('Implement A.')
    (harness.repo / 'prompts' / 'impl-b.md').write_text('Implement B.')
    spawn = MarkerSpawn([ok_result(), ok_result()], markers_for=('marker-a', 'marker-b'))

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-two-green',
    )

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert harness.git.current_branch() == 'integration'

    # Dependency order: pr-a spawned before pr-b (the DAG ran the dependency first).
    briefs = [request.brief for request, _cwd in spawn.calls]
    assert briefs == ['Implement A.', 'Implement B.']

    # Both PRs integrated: each marker is present on the integration branch at the
    # end. pr-b branched off pr-a's already-integrated state, so integrating pr-b
    # carries pr-a's marker forward too — both land together.
    assert (harness.repo / 'marker-a').exists()
    assert (harness.repo / 'marker-b').exists()

    events = _read_events(harness.outputs)
    assert len(_events_of(events, 'spawn_complete')) == 2
    run_completes = _events_of(events, 'run_complete')
    assert len(run_completes) == 1
    assert run_completes[0]['outcome'] == 'completed'
    assert run_completes[0]['integrated'] is True


def test_dependency_failure_skips_the_dependent(harness: Harness) -> None:
    """When pr-a's gate goes red the run halts fail-loud and pr-b never runs or integrates.

    The gate is series-level, so this uses a 2-PR series with a blocking-red check:
    the gate runs after pr-a (the first PR) is committed, goes red, and halts
    before pr-b — genuinely exercising the "dependent of a failed PR is skipped"
    path rather than a one-PR stand-in.
    """
    red_series = _make_series(harness.repo, Check(name='red', run=_FAIL_CMD, blocking=True))
    series = _two_pr_series(red_series)
    (harness.repo / 'prompts' / 'impl-a.md').write_text('Implement A.')
    (harness.repo / 'prompts' / 'impl-b.md').write_text('Implement B.')
    spawn = MarkerSpawn([ok_result(), ok_result()], markers_for=('marker-a', 'marker-b'))

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-dep-fail',
    )

    assert outcome == RunOutcome('blocked', False, EXIT_BLOCKED)
    # pr-b never spawned: only pr-a's spawn was recorded before the halt.
    assert len(spawn.calls) == 1
    assert spawn.calls[0][0].brief == 'Implement A.'
    # pr-b's branch was never created, and its marker never reached the tree.
    assert not _branch_exists(harness.repo, 'pr-b')
    assert not (harness.repo / 'marker-b').exists()
    # Halted on pr-a's branch, never on integration.
    assert harness.git.current_branch() != 'integration'

    events = _read_events(harness.outputs)
    assert len(_events_of(events, 'spawn_complete')) == 1
    run_completes = _events_of(events, 'run_complete')
    assert len(run_completes) == 1
    assert run_completes[0]['outcome'] == 'blocked'
    assert run_completes[0]['integrated'] is False


def _marker_series(harness: Harness, max_fix_attempts: int) -> Series:
    """A one-PR series gated on the marker check, with ``max_fix_attempts`` fix budget.

    The single blocking check (:data:`_MARKER_CMD`) is red until a fix spawn creates
    ``fixed.marker``, so the fix loop's re-gate is driven by a REAL check flipping,
    not by a scripted verdict.
    """
    base = _make_series(harness.repo, Check(name='marker', run=_MARKER_CMD, blocking=True))
    base = replace(base, review=replace(base.review, max_fix_attempts=max_fix_attempts))
    return _one_pr_series(base)


def test_fix_loop_converges_and_integrates(harness: Harness) -> None:
    """A blocking red the fix repairs turns green on re-gate and integrates.

    ``max_fix_attempts=2``; the implementation leaves the marker check red, and fix
    attempt 1 creates ``fixed.marker`` so the re-gate goes green. The run completes,
    integrated, having recorded an ``implementation`` spawn and at least one ``fix``.
    """
    series = _marker_series(harness, max_fix_attempts=2)
    # One implementation spawn (call 0, no marker) + one fix spawn (call 1, creates it).
    spawn = FixMarkerSpawn([ok_result(), ok_result()], fix_creates_marker=True)

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-fix-converges',
    )

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert harness.git.current_branch() == 'integration'
    # The fix's marker really landed and is carried onto the integration branch.
    assert (harness.repo / _FIX_MARKER).exists()

    events = _read_events(harness.outputs)
    spawn_completes = _events_of(events, 'spawn_complete')
    roles = [event['role'] for event in spawn_completes]
    assert 'implementation' in roles
    assert roles.count('fix') >= 1
    run_completes = _events_of(events, 'run_complete')
    assert len(run_completes) == 1
    assert run_completes[0]['outcome'] == 'completed'
    assert run_completes[0]['integrated'] is True


def test_fix_loop_exhausts_stays_blocked(harness: Harness) -> None:
    """When no fix repairs the red, the loop exhausts and the run is blocked, never green.

    The marker is never created, so every re-gate stays red. After exactly
    ``max_fix_attempts`` fix spawns the run halts ``blocked`` and does not integrate
    — the never-green-over-red invariant: an exhausted fix loop is blocked, not
    completed.
    """
    max_fix_attempts = 3
    series = _marker_series(harness, max_fix_attempts=max_fix_attempts)
    # 1 implementation + max_fix_attempts fix spawns, none of which create the marker.
    results = [ok_result() for _ in range(1 + max_fix_attempts)]
    spawn = FixMarkerSpawn(results, fix_creates_marker=False)

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-fix-exhausts',
    )

    # Blocked, NOT completed — the invariant: green is never emitted over a red.
    assert outcome == RunOutcome('blocked', False, EXIT_BLOCKED)
    assert outcome.outcome != 'completed'
    assert outcome.integrated is False
    assert harness.git.current_branch() != 'integration'
    assert not (harness.repo / _FIX_MARKER).exists()

    events = _read_events(harness.outputs)
    spawn_completes = _events_of(events, 'spawn_complete')
    fix_spawns = [event for event in spawn_completes if event['role'] == 'fix']
    # Exactly max_fix_attempts fix spawns were made — no more, no fewer.
    assert len(fix_spawns) == max_fix_attempts
    run_completes = _events_of(events, 'run_complete')
    assert len(run_completes) == 1
    assert run_completes[0]['outcome'] == 'blocked'
    assert run_completes[0]['integrated'] is False


def test_zero_fix_attempts_halts_immediately(harness: Harness) -> None:
    """``max_fix_attempts=0``: a blocking red halts as blocked with zero fix spawns."""
    series = _marker_series(harness, max_fix_attempts=0)
    # Only the implementation spawn should ever run; no fix budget.
    spawn = FixMarkerSpawn([ok_result()], fix_creates_marker=True)

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-fix-zero',
    )

    assert outcome == RunOutcome('blocked', False, EXIT_BLOCKED)
    assert harness.git.current_branch() != 'integration'
    # No fix spawn was attempted at all.
    assert len(spawn.calls) == 1

    events = _read_events(harness.outputs)
    spawn_completes = _events_of(events, 'spawn_complete')
    # Exactly one spawn recorded, and it is the implementation — no fix spawn.
    assert [event['role'] for event in spawn_completes] == ['implementation']
    run_completes = _events_of(events, 'run_complete')
    assert len(run_completes) == 1
    assert run_completes[0]['outcome'] == 'blocked'


def test_make_run_id_shape() -> None:
    """``make_run_id`` is a sortable ``YYYYMMDDTHHMMSSZ`` timestamp plus a short suffix."""
    run_id = make_run_id()
    assert re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]+', run_id), run_id
