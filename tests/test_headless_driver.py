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
from typing import cast

import pytest
from test_reporter import RecordingReporter

from convoy.core.gate import CheckResult, decide
from convoy.core.preflight import Advisory
from convoy.core.spec import (
    PR,
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
    EXIT_BUDGET,
    EXIT_INFRASTRUCTURE,
    EXIT_OK,
    RunOutcome,
    _commit_subject,
    _fix_brief,
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
    budget_result,
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
    # Telemetry outputs live OUTSIDE the scored workspace (as in real usage), so writing
    # spawns.jsonl never dirties the git tree between a commit and the next checkout.
    outputs = repo.parent / 'outputs'
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
        outputs=repo.parent / 'outputs',
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


def test_per_pr_model_reaches_the_implementation_spawn(harness: Harness) -> None:
    """A PR that pins its own model spawns on it; a PR that does not inherits the series model.

    Pins the driver's per-PR ``effective_governance`` layering at the implementation site.
    """
    series = replace(
        _two_pr_series(harness.series),
        prs=(
            PR(id='pr-a', branch='pr-a', prompt='impl-a.md', phase='implementation'),
            PR(
                id='pr-b',
                branch='pr-b',
                prompt='impl-b.md',
                phase='implementation',
                depends_on=('pr-a',),
                model='pr-b-model',
            ),
        ),
    )
    (harness.repo / 'prompts' / 'impl-a.md').write_text('Implement A.')
    (harness.repo / 'prompts' / 'impl-b.md').write_text('Implement B.')
    spawn = MarkerSpawn([ok_result(), ok_result()], markers_for=('marker-a', 'marker-b'))

    outcome = _run(harness, series, spawn, 'run-per-pr-model')

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    # pr-a inherits the series model; pr-b runs on its own.
    assert spawn.calls[0][0].model == 'test-model'
    assert spawn.calls[1][0].model == 'pr-b-model'


def test_fix_spawn_uses_the_prs_own_model(harness: Harness) -> None:
    """A PR's fix spawn reuses that PR's own resolved model, not the series model.

    Without this a repair silently runs on a different tier than the work it repairs.
    """
    base = _make_series(harness.repo, Check(name='marker', run=_MARKER_CMD, blocking=True))
    base = replace(base, review=replace(base.review, max_fix_attempts=1))
    series = replace(
        base,
        prs=(
            PR(
                id='pr-1',
                branch='pr-1',
                prompt='impl.md',
                phase='implementation',
                model='pr-1-model',
            ),
        ),
    )
    # impl leaves the marker check red; the fix spawn creates the marker and goes green.
    spawn = FixMarkerSpawn([ok_result(), ok_result()], fix_creates_marker=True)

    outcome = _run(harness, series, spawn, 'run-fix-model')

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    fix_calls = [
        request for request, _cwd in spawn.calls if '## Failing checks to repair' in request.brief
    ]
    assert len(fix_calls) == 1
    assert fix_calls[0].model == 'pr-1-model'  # not 'test-model'


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


def test_fix_brief_carries_a_declared_repair_hint() -> None:
    """A failing check's ``repair_hint`` reaches the fix brief verbatim; no hint, no line."""
    hinted = Check(
        name='refs-fresh',
        run='pytest -k refs',
        blocking=True,
        repair_hint='run scripts/generate_references.py and commit the diff',
    )
    bare = Check(name='suite', run='pytest', blocking=True)
    verdict = decide(
        [
            CheckResult(check=hinted, passed=False, detail='exited 1: stale mirror'),
            CheckResult(check=bare, passed=False, detail='exited 1: 3 failed'),
        ]
    )

    brief = _fix_brief('Original brief.', verdict)

    assert 'repair hint: run scripts/generate_references.py and commit the diff' in brief
    assert brief.count('repair hint:') == 1  # the hintless check gained no line


def test_repair_hint_reaches_the_fix_spawn_brief(harness: Harness) -> None:
    """The recipe declared on the failing check is briefed to the fix spawn that repairs it."""
    hint = 'create fixed.marker in the workspace root'
    base = _make_series(
        harness.repo,
        Check(name='marker', run=_MARKER_CMD, blocking=True, repair_hint=hint),
    )
    base = replace(base, review=replace(base.review, max_fix_attempts=1))
    series = _one_pr_series(base)
    spawn = FixMarkerSpawn([ok_result(), ok_result()], fix_creates_marker=True)

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-repair-hint',
    )

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    fix_briefs = [
        request.brief
        for request, _cwd in spawn.calls
        if '## Failing checks to repair' in request.brief
    ]
    assert len(fix_briefs) == 1
    assert f'repair hint: {hint}' in fix_briefs[0]


def test_non_ascii_prompt_reaches_the_spawn_intact(harness: Harness) -> None:
    """A UTF-8 prompt with non-ASCII text neither crashes the run nor arrives garbled.

    'ѐ' encodes to D1 90 and byte 0x90 is undefined in cp1252, so reading the
    prompt with the locale-default encoding crashed the run on Windows; the driver
    must pin UTF-8 for the read.
    """
    prompt_text = 'Vérifier ✓ ѐ'
    (harness.repo / 'prompts' / 'impl.md').write_text(prompt_text, encoding='utf-8')
    series = _one_pr_series(harness.series)  # default check is _PASS_CMD (blocking)
    spawn = FakeSpawn([ok_result()])

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-utf8-prompt',
    )

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert spawn.calls[0][0].brief == prompt_text


def test_make_run_id_shape() -> None:
    """``make_run_id`` is a sortable ``YYYYMMDDTHHMMSSZ`` timestamp plus a short suffix."""
    run_id = make_run_id()
    assert re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]+', run_id), run_id


# ---------------------------------------------------------------------------
# gate_complete + pr_skipped telemetry (additive events)
# ---------------------------------------------------------------------------


def _run(harness: Harness, series: Series, spawn: FakeSpawn, run_id: str) -> RunOutcome:
    """Run ``series`` against ``harness`` with ``spawn``, returning the outcome."""
    return run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id=run_id,
    )


def _checks_of(gate_event: dict[str, object]) -> list[dict[str, object]]:
    """The per-check breakdown list from a ``gate_complete`` event."""
    checks = gate_event['checks']
    assert isinstance(checks, list)
    return cast('list[dict[str, object]]', checks)


def test_green_run_emits_gate_complete_attempt_zero(harness: Harness) -> None:
    """A green PR records one gate_complete at attempt 0 with its passing check, and no skips."""
    series = _one_pr_series(harness.series)  # default check is _PASS_CMD (blocking, name 'green')
    _run(harness, series, FakeSpawn([ok_result()]), 'run-gc-green')

    events = _read_events(harness.outputs)
    gates = _events_of(events, 'gate_complete')
    assert len(gates) == 1
    assert gates[0]['pr_id'] == 'pr-1'
    assert gates[0]['attempt'] == 0
    assert gates[0]['blocking_red'] is False
    checks = _checks_of(gates[0])
    assert [c['name'] for c in checks] == ['green']
    assert checks[0]['passed'] is True
    assert _events_of(events, 'pr_skipped') == []


def test_blocked_one_pr_emits_red_gate_and_no_skips(harness: Harness) -> None:
    """A blocked single PR records a red gate_complete and no pr_skipped (nothing follows it)."""
    red_series = _make_series(harness.repo, Check(name='red', run=_FAIL_CMD, blocking=True))
    series = _one_pr_series(red_series)
    _run(harness, series, FakeSpawn([ok_result()]), 'run-gc-red')

    events = _read_events(harness.outputs)
    gates = _events_of(events, 'gate_complete')
    assert len(gates) == 1
    assert gates[0]['blocking_red'] is True
    checks = _checks_of(gates[0])
    assert checks[0]['name'] == 'red'
    assert checks[0]['passed'] is False
    assert _events_of(events, 'pr_skipped') == []


def test_blocked_two_pr_skips_the_dependent(harness: Harness) -> None:
    """When pr-a blocks, pr-b is recorded skipped and never gated or spawned."""
    red_series = _make_series(harness.repo, Check(name='red', run=_FAIL_CMD, blocking=True))
    series = _two_pr_series(red_series)
    (harness.repo / 'prompts' / 'impl-a.md').write_text('Implement A.')
    (harness.repo / 'prompts' / 'impl-b.md').write_text('Implement B.')
    spawn = MarkerSpawn([ok_result(), ok_result()], markers_for=('marker-a', 'marker-b'))
    _run(harness, series, spawn, 'run-gc-skip')

    events = _read_events(harness.outputs)
    skips = _events_of(events, 'pr_skipped')
    assert len(skips) == 1
    assert skips[0]['pr_id'] == 'pr-b'
    assert skips[0]['reason'] == 'series halted at pr-a (blocked) before this PR started'
    # Only pr-a was gated; pr-b was never spawned.
    assert [g['pr_id'] for g in _events_of(events, 'gate_complete')] == ['pr-a']
    assert len(spawn.calls) == 1


def test_fix_converge_emits_gate_attempts_zero_then_one(harness: Harness) -> None:
    """A converging fix loop records gate_complete at attempt 0 (red) then attempt 1 (green)."""
    series = _marker_series(harness, max_fix_attempts=2)
    spawn = FixMarkerSpawn([ok_result(), ok_result()], fix_creates_marker=True)
    _run(harness, series, spawn, 'run-gc-fix')

    gates = _events_of(_read_events(harness.outputs), 'gate_complete')
    assert [g['attempt'] for g in gates] == [0, 1]
    assert gates[0]['blocking_red'] is True
    assert gates[1]['blocking_red'] is False


def test_fix_exhaust_emits_one_red_gate_per_regate(harness: Harness) -> None:
    """An exhausted fix loop records a red gate_complete at attempts 0..max_fix_attempts."""
    series = _marker_series(harness, max_fix_attempts=3)
    results = [ok_result() for _ in range(1 + 3)]
    spawn = FixMarkerSpawn(results, fix_creates_marker=False)
    _run(harness, series, spawn, 'run-gc-exhaust')

    gates = _events_of(_read_events(harness.outputs), 'gate_complete')
    assert [g['attempt'] for g in gates] == [0, 1, 2, 3]
    assert all(g['blocking_red'] is True for g in gates)


def test_infra_halt_skips_downstream_and_emits_no_gate(harness: Harness) -> None:
    """An infra halt on pr-a records pr-b skipped and writes no gate_complete (gate never runs)."""
    series = _two_pr_series(harness.series)
    (harness.repo / 'prompts' / 'impl-a.md').write_text('Implement A.')
    (harness.repo / 'prompts' / 'impl-b.md').write_text('Implement B.')
    infra = SpawnResult(
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
    _run(harness, series, FakeSpawn([infra]), 'run-gc-infra')

    events = _read_events(harness.outputs)
    assert _events_of(events, 'gate_complete') == []
    skips = _events_of(events, 'pr_skipped')
    assert [s['pr_id'] for s in skips] == ['pr-b']
    assert 'infrastructure' in cast('str', skips[0]['reason'])


def test_gate_and_skip_precede_run_complete_in_the_stream(harness: Harness) -> None:
    """run_complete is the terminal line; gate_complete and pr_skipped are written before it."""
    red_series = _make_series(harness.repo, Check(name='red', run=_FAIL_CMD, blocking=True))
    series = _two_pr_series(red_series)
    (harness.repo / 'prompts' / 'impl-a.md').write_text('Implement A.')
    (harness.repo / 'prompts' / 'impl-b.md').write_text('Implement B.')
    spawn = MarkerSpawn([ok_result(), ok_result()], markers_for=('marker-a', 'marker-b'))
    _run(harness, series, spawn, 'run-gc-order')

    tags = [event['event'] for event in _read_events(harness.outputs)]
    assert tags[-1] == 'run_complete'
    assert tags.index('gate_complete') < tags.index('run_complete')
    assert tags.index('pr_skipped') < tags.index('run_complete')


# (The never-blank effective_model fallback is exercised where it lives — at the spawn
# adapter — in tests/test_headless_spawn.py; a driver-level check would only assert its own
# fixtures, which hardcode a model, so it is omitted here as non-discriminating.)


# ---------------------------------------------------------------------------
# Reporter narration (stderr run log) — the same moments as telemetry
# ---------------------------------------------------------------------------


def test_reporter_narrates_a_green_run(harness: Harness) -> None:
    """A green single-PR run fires run_start, spawn_done, gate_result, integrated, run_done."""
    series = _one_pr_series(harness.series)
    rec = RecordingReporter()
    run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result()]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='rep-green',
        reporter=rec,
    )
    assert rec.names() == ['run_start', 'spawn_done', 'gate_result', 'integrated', 'run_done']
    assert rec.calls[-1] == ('run_done', 'completed', True)


def test_reporter_narrates_a_blocked_run_with_a_skip(harness: Harness) -> None:
    """A blocked two-PR run narrates the gate red, the dependent skip, and a blocked run_done."""
    red_series = _make_series(harness.repo, Check(name='red', run=_FAIL_CMD, blocking=True))
    series = _two_pr_series(red_series)
    (harness.repo / 'prompts' / 'impl-a.md').write_text('Implement A.')
    (harness.repo / 'prompts' / 'impl-b.md').write_text('Implement B.')
    rec = RecordingReporter()
    run_series(
        series,
        harness.repo,
        spawn=MarkerSpawn([ok_result(), ok_result()], markers_for=('marker-a', 'marker-b')),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='rep-blocked',
        reporter=rec,
    )
    assert rec.names() == ['run_start', 'spawn_done', 'gate_result', 'pr_skipped', 'run_done']
    assert (
        'pr_skipped',
        'pr-b',
        'series halted at pr-a (blocked) before this PR started',
    ) in rec.calls
    assert rec.calls[-1] == ('run_done', 'blocked', False)


def test_reporter_narrates_a_fix_converge_run(harness: Harness) -> None:
    """A converging fix loop narrates impl, red gate, fix, fix spawn, green gate, integrate."""
    series = _marker_series(harness, max_fix_attempts=2)
    rec = RecordingReporter()
    run_series(
        series,
        harness.repo,
        spawn=FixMarkerSpawn([ok_result(), ok_result()], fix_creates_marker=True),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='rep-fix',
        reporter=rec,
    )
    assert rec.names() == [
        'run_start',
        'spawn_done',
        'gate_result',
        'fix_attempt',
        'spawn_done',
        'gate_result',
        'integrated',
        'run_done',
    ]


# ---------------------------------------------------------------------------
# Budget-truncation halts the PR before commit / gate / integrate
# ---------------------------------------------------------------------------


def test_budget_arm_halts_before_commit_and_gate(harness: Harness) -> None:
    """A budget-classified spawn halts 'budget' before the gate runs and never integrates."""
    # The check would ERROR if ever run (it removes a sentinel), so a surviving sentinel
    # proves the gate never ran — the budget halt precedes it.
    sentinel = harness.repo / 'gate-ran.marker'
    sentinel.write_text('present')
    gate_probe = f'"{sys.executable}" -c "import os; os.remove(r\'{sentinel}\')"'
    probe_series = _make_series(harness.repo, Check(name='probe', run=gate_probe, blocking=True))
    series = _one_pr_series(probe_series)

    outcome = run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([budget_result()]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-budget',
    )

    assert outcome == RunOutcome('budget', False, EXIT_BUDGET)
    assert harness.git.current_branch() != 'integration'
    assert sentinel.exists()  # the gate never ran

    events = _read_events(harness.outputs)
    assert len(_events_of(events, 'spawn_complete')) == 1
    assert _events_of(events, 'gate_complete') == []
    run_completes = _events_of(events, 'run_complete')
    assert run_completes[0]['outcome'] == 'budget'
    assert run_completes[0]['integrated'] is False


def test_budget_in_the_fix_loop_halts(harness: Harness) -> None:
    """A budget-capped fix spawn halts 'budget' before its commit."""
    series = _marker_series(harness, max_fix_attempts=2)
    # impl leaves the marker check red; the fix spawn is budget-capped.
    spawn = FixMarkerSpawn([ok_result(), budget_result()], fix_creates_marker=False)

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-budget-fix',
    )

    assert outcome == RunOutcome('budget', False, EXIT_BUDGET)
    run_completes = _events_of(_read_events(harness.outputs), 'run_complete')
    assert run_completes[0]['outcome'] == 'budget'


def test_budget_halt_skips_the_dependent(harness: Harness) -> None:
    """A budget halt on pr-a records pr-b skipped (never spawned) and narrates it."""
    series = _two_pr_series(harness.series)
    (harness.repo / 'prompts' / 'impl-a.md').write_text('Implement A.')
    (harness.repo / 'prompts' / 'impl-b.md').write_text('Implement B.')
    rec = RecordingReporter()
    spawn = MarkerSpawn([budget_result(), ok_result()], markers_for=('marker-a', 'marker-b'))

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-budget-skip',
        reporter=rec,
    )

    assert outcome == RunOutcome('budget', False, EXIT_BUDGET)
    events = _read_events(harness.outputs)
    skips = _events_of(events, 'pr_skipped')
    assert len(skips) == 1
    assert skips[0]['pr_id'] == 'pr-b'
    assert skips[0]['reason'] == 'series halted at pr-a (budget) before this PR started'
    # pr-b was never spawned and no gate ran (budget halts before commit / gate).
    assert len(spawn.calls) == 1
    assert _events_of(events, 'gate_complete') == []
    assert (
        'pr_skipped',
        'pr-b',
        'series halted at pr-a (budget) before this PR started',
    ) in rec.calls


# ---------------------------------------------------------------------------
# The near-cap signal — said while there is still a run to save
# ---------------------------------------------------------------------------


def test_a_spawn_that_ran_close_to_its_cap_is_flagged_on_its_telemetry_line(
    harness: Harness,
) -> None:
    """The ledger records the ceiling and that the spawn reached the nearing fraction of it.

    The fixture cap is $1.00, so $0.95 is 95% — under the cap, so the run completes exactly
    as it always did. The cap is not softened; what is new is that the record says the spawn
    ran hot before the next one busts it.
    """
    series = _one_pr_series(harness.series)

    run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result(cost_usd=0.95)]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-near-cap',
    )

    spawns = _events_of(_read_events(harness.outputs), 'spawn_complete')
    assert spawns[0]['budget_cap_usd'] == 1.0
    assert spawns[0]['budget_nearing'] is True


def test_an_ordinary_spawn_carries_its_cap_and_is_not_flagged(harness: Harness) -> None:
    """Every line carries the ceiling it ran under; only a hot one is flagged."""
    series = _one_pr_series(harness.series)

    run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result(cost_usd=0.01)]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-cheap',
    )

    spawns = _events_of(_read_events(harness.outputs), 'spawn_complete')
    assert spawns[0]['budget_cap_usd'] == 1.0
    assert spawns[0]['budget_nearing'] is False


def test_a_near_cap_spawn_is_narrated_and_the_run_still_completes(harness: Harness) -> None:
    """The operator hears it on stderr, and the hard cap is untouched — the run integrates."""
    series = _one_pr_series(harness.series)
    rec = RecordingReporter()

    outcome = run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result(cost_usd=0.95)]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-near-cap-narrated',
        reporter=rec,
    )

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert rec.names() == [
        'run_start',
        'spawn_done',
        'budget_nearing',
        'gate_result',
        'integrated',
        'run_done',
    ]
    assert ('budget_nearing', 'pr-1', 'implementation', 0.95, 1.0) in rec.calls


def test_a_near_cap_fix_spawn_reports_the_fix_role_ceiling(harness: Harness) -> None:
    """A repair is metered against the FIX cap, not the implementation one it repairs."""
    series = _marker_series(harness, max_fix_attempts=1)
    fix_cap = series.governance.budgets.fix
    rec = RecordingReporter()

    run_series(
        series,
        harness.repo,
        spawn=FixMarkerSpawn(
            [ok_result(cost_usd=0.01), ok_result(cost_usd=fix_cap * 0.95)],
            fix_creates_marker=True,
        ),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-near-cap-fix',
        reporter=rec,
    )

    spawns = _events_of(_read_events(harness.outputs), 'spawn_complete')
    fix_line = next(line for line in spawns if line['role'] == 'fix')
    assert fix_line['budget_cap_usd'] == fix_cap
    assert fix_line['budget_nearing'] is True
    assert ('budget_nearing', 'pr-1', 'fix', fix_cap * 0.95, fix_cap) in rec.calls


# ---------------------------------------------------------------------------
# output_tail — a non-ok spawn's output reaches telemetry (bounded) for diagnosis
# ---------------------------------------------------------------------------


def _infra_result(output: str) -> SpawnResult:
    """An infrastructure-classified result carrying ``output`` (zeroed economy)."""
    return SpawnResult(
        exit_code=1,
        output=output,
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


def test_non_ok_spawn_records_its_output_tail(harness: Harness) -> None:
    """An infra halt is diagnosable from telemetry alone: the spawn output rides along.

    Two production runs halted on an expired seat showing only ``exit_code: 1, $0`` —
    the operator had to re-run the spawn by hand to see ``Not logged in``.
    """
    series = _one_pr_series(harness.series)
    message = 'claude: Not logged in - please run /login'
    _run(harness, series, FakeSpawn([_infra_result(message)]), 'run-tail-infra')

    spawns = _events_of(_read_events(harness.outputs), 'spawn_complete')
    assert spawns[0]['output_tail'] == message


def test_ok_spawn_records_an_empty_output_tail(harness: Harness) -> None:
    """A healthy spawn's (potentially huge) stream output stays out of telemetry."""
    series = _one_pr_series(harness.series)
    _run(harness, series, FakeSpawn([ok_result(output='x' * 5000)]), 'run-tail-ok')

    spawns = _events_of(_read_events(harness.outputs), 'spawn_complete')
    assert spawns[0]['output_tail'] == ''


def test_output_tail_is_bounded_to_the_last_chars(harness: Harness) -> None:
    """A long failure output is truncated to its tail — the end is where the error is."""
    series = _one_pr_series(harness.series)
    long_output = 'A' * 1000 + 'B' * 2500
    _run(harness, series, FakeSpawn([_infra_result(long_output)]), 'run-tail-bound')

    spawns = _events_of(_read_events(harness.outputs), 'spawn_complete')
    assert spawns[0]['output_tail'] == long_output[-2000:]


# --- phase-scoped checks -----------------------------------------------------
#
# The motivating case: an INCREMENTAL series, where PR1 lands a core slice and a later
# PR completes it. Before phase scoping, PR1 was gated on the whole tuple — including
# the check belonging to the phase PR2 will land — so PR1 could not pass its own gate
# and the series was unrunnable. These run the real driver against the real gate runner.


class RecordingGateRunner:
    """Wraps the real runner and records the check names each gate call received."""

    def __init__(self, inner: SubprocessGateRunner) -> None:
        self._inner = inner
        self.calls: list[tuple[str, ...]] = []

    def run(self, workspace: Path, checks: Sequence[Check]) -> tuple[CheckResult, ...]:
        self.calls.append(tuple(check.name for check in checks))
        return self._inner.run(workspace, checks)


def _two_phase_series(base: Series, checks: tuple[Check, ...]) -> Series:
    """``base`` with two PRs in different phases: pr-1 in 'core', pr-2 in 'extras'."""
    return replace(
        base,
        checks=checks,
        prs=(
            PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),
            PR(id='pr-2', branch='pr-2', prompt='impl.md', phase='extras', depends_on=('pr-1',)),
        ),
    )


def test_a_later_phases_failing_check_does_not_block_an_earlier_pr(harness: Harness) -> None:
    """PR1 passes even though the 'extras' check is red — it does not gate PR1's phase.

    This is the whole point of the feature. Without scoping this series halts at pr-1.
    """
    series = _two_phase_series(
        harness.series,
        (
            Check(name='core-suite', run=_PASS_CMD, blocking=True, phases=('core',)),
            Check(name='extras-suite', run=_FAIL_CMD, blocking=True, phases=('extras',)),
        ),
    )
    recorder = RecordingGateRunner(harness.gate_runner)
    outcome = run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result(), ok_result()]),
        git=harness.git,
        gate_runner=cast('SubprocessGateRunner', recorder),
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-phases',
    )

    # pr-1 gated only on core-suite and integrated; pr-2 gated only on the red one and blocked.
    assert recorder.calls == [('core-suite',), ('extras-suite',)]
    assert outcome == RunOutcome('blocked', False, EXIT_BLOCKED)


def test_an_unscoped_check_still_gates_every_pr(harness: Harness) -> None:
    """The default is unchanged: no ``phases`` anywhere means the whole tuple, every PR."""
    series = _two_phase_series(
        harness.series,
        (
            Check(name='always', run=_PASS_CMD, blocking=True),
            Check(name='core-only', run=_PASS_CMD, blocking=True, phases=('core',)),
        ),
    )
    recorder = RecordingGateRunner(harness.gate_runner)
    outcome = run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result(), ok_result()]),
        git=harness.git,
        gate_runner=cast('SubprocessGateRunner', recorder),
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-mixed',
    )

    assert recorder.calls == [('always', 'core-only'), ('always',)]
    assert outcome == RunOutcome('completed', True, EXIT_OK)


def test_a_pr_no_check_gates_integrates_ungated(harness: Harness) -> None:
    """Selecting nothing is allowed: the PR runs with an empty gate and integrates.

    Pre-flight advises on this (``core.preflight.ungated_prs``); the driver does not
    refuse it. An empty verdict is not ``blocking_red``, so the merge proceeds.
    """
    series = _two_phase_series(
        harness.series,
        (Check(name='core-suite', run=_PASS_CMD, blocking=True, phases=('core',)),),
    )
    recorder = RecordingGateRunner(harness.gate_runner)
    outcome = run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result(), ok_result()]),
        git=harness.git,
        gate_runner=cast('SubprocessGateRunner', recorder),
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-ungated',
    )

    assert recorder.calls == [('core-suite',), ()]
    assert outcome == RunOutcome('completed', True, EXIT_OK)


def test_the_fix_regate_uses_the_same_scoped_checks(harness: Harness) -> None:
    """A repair is judged by exactly the checks that failed it, not the whole tuple."""
    series = replace(
        harness.series,
        review=Review(blocking=True, max_fix_attempts=1),
        checks=(
            Check(name='core-suite', run=_MARKER_CMD, blocking=True, phases=('core',)),
            Check(name='extras-suite', run=_FAIL_CMD, blocking=True, phases=('extras',)),
        ),
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),),
    )

    recorder = RecordingGateRunner(harness.gate_runner)
    outcome = run_series(
        series,
        harness.repo,
        spawn=FixMarkerSpawn([ok_result(), ok_result()], fix_creates_marker=True),
        git=harness.git,
        gate_runner=cast('SubprocessGateRunner', recorder),
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-refix',
    )

    # Initial gate red, fix spawn, re-gate green — and the red 'extras-suite' never ran.
    assert recorder.calls == [('core-suite',), ('core-suite',)]
    assert outcome == RunOutcome('completed', True, EXIT_OK)


# --- resume ------------------------------------------------------------------
#
# After a halt the integration branch retains every green merge, so what it contains is
# the record of what is done. Resuming must not re-spawn those PRs -- the whole value of
# the flag is the money NOT spent, so these assert on spawn counts, not just outcomes.
#
# Each PR commits a marker file (MarkerSpawn), because an empty branch points at the same
# commit as the integration branch, and "merged" would then be indistinguishable from
# "branched and did nothing" -- the distinction Git.is_merged_into exists to make.


def _three_pr_series(base: Series) -> Series:
    return replace(
        base,
        checks=(Check(name='green', run=_PASS_CMD, blocking=True),),
        prs=(
            PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),
            PR(id='pr-2', branch='pr-2', prompt='impl.md', phase='core', depends_on=('pr-1',)),
            PR(id='pr-3', branch='pr-3', prompt='impl.md', phase='core', depends_on=('pr-2',)),
        ),
    )


def _resume_run(
    series: Series, harness: Harness, spawn: FakeSpawn, run_id: str, *, resume: bool = False
) -> RunOutcome:
    return run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id=run_id,
        resume=resume,
    )


def _skips(outputs: Path, run_id: str) -> list[dict[str, str]]:
    return [e for e in _events_of(_read_events(outputs), 'pr_skipped') if e['run_id'] == run_id]


def _spawned_prs(outputs: Path, run_id: str) -> set[str]:
    return {
        event['pr_id']
        for event in _events_of(_read_events(outputs), 'spawn_complete')
        if event['run_id'] == run_id
    }


def test_resume_of_a_completed_series_spawns_nothing(harness: Harness) -> None:
    """The money test: every PR already merged costs exactly zero on resume."""
    series = _three_pr_series(harness.series)
    first = _resume_run(
        series,
        harness,
        MarkerSpawn([ok_result()] * 3, markers_for=['a.txt', 'b.txt', 'c.txt']),
        'run-1',
    )
    assert first == RunOutcome('completed', True, EXIT_OK)

    spawn = FakeSpawn([])  # asserts if called even once
    outcome = _resume_run(series, harness, spawn, 'run-2', resume=True)

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert spawn.calls == []
    skips = _skips(harness.outputs, 'run-2')
    assert {event['pr_id'] for event in skips} == {'pr-1', 'pr-2', 'pr-3'}
    # A reason distinct from the halt reasons: "done" and "never ran" are opposite
    # outcomes, and a consumer folding a resumed run must not confuse them.
    assert all('already integrated' in event['reason'] for event in skips)
    assert all('halted' not in event['reason'] for event in skips)


def test_resume_reruns_only_the_prs_that_never_landed(harness: Harness) -> None:
    series = _three_pr_series(harness.series)
    infra = SpawnResult(
        exit_code=1,
        classification='infrastructure',
        output='auth failed',
        economy=SpawnEconomy(
            input_tokens=0,
            output_tokens=0,
            num_turns=0,
            duration_s=0.0,
            cost_usd=0.0,
            effective_model='test-model',
        ),
    )
    # pr-1 lands; pr-2 dies on an infrastructure spawn, so pr-2 and pr-3 never integrate.
    first = _resume_run(
        series,
        harness,
        MarkerSpawn([ok_result(), infra], markers_for=['a.txt', 'b.txt']),
        'run-1',
    )
    assert first == RunOutcome('infrastructure', False, EXIT_INFRASTRUCTURE)
    assert harness.git.is_merged_into('pr-1', 'integration')
    assert not harness.git.is_merged_into('pr-2', 'integration')

    spawn = MarkerSpawn([ok_result(), ok_result()], markers_for=['b.txt', 'c.txt'])
    outcome = _resume_run(series, harness, spawn, 'run-2', resume=True)

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert len(spawn.calls) == 2  # pr-2 and pr-3 only -- pr-1 was not paid for twice
    assert [event['pr_id'] for event in _skips(harness.outputs, 'run-2')] == ['pr-1']
    assert _spawned_prs(harness.outputs, 'run-2') == {'pr-2', 'pr-3'}


def test_resume_does_not_skip_a_branch_that_merely_points_at_integration(
    harness: Harness,
) -> None:
    """The subtle one: an empty branch is CONTAINED but was never merged.

    A PR whose implementation committed nothing leaves its branch on the same commit as
    the integration branch. Plain containment calls that done, which would silently drop
    the PR from a resumed run and still report ``completed``. It must be re-attempted.
    """
    series = replace(
        harness.series,
        checks=(Check(name='green', run=_PASS_CMD, blocking=True),),
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),),
    )
    harness.git.checkout('base')
    harness.git.checkout('integration', create=True)
    harness.git.checkout('pr-1', create=True)
    harness.git.checkout('integration')
    assert harness.git.is_ancestor('pr-1', 'integration')  # contained...
    assert not harness.git.is_merged_into('pr-1', 'integration')  # ...but never merged

    spawn = MarkerSpawn([ok_result()], markers_for=['a.txt'])
    outcome = _resume_run(series, harness, spawn, 'run-2', resume=True)

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert len(spawn.calls) == 1  # it really ran
    assert _skips(harness.outputs, 'run-2') == []


def test_resume_discards_a_failed_attempts_branch_rather_than_building_on_it(
    harness: Harness,
) -> None:
    """A PR branch with unmerged commits is a failed attempt: re-attempt, do not extend."""
    series = replace(
        harness.series,
        review=Review(blocking=True, max_fix_attempts=0),
        checks=(Check(name='marker', run=_MARKER_CMD, blocking=True),),
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),),
    )
    # The spawn commits work but the gate stays red (no fixed.marker) and there are zero
    # fix attempts, so the series halts blocked with pr-1 unmerged and carrying commits.
    first = _resume_run(
        series, harness, MarkerSpawn([ok_result()], markers_for=['junk.txt']), 'run-1'
    )
    assert first == RunOutcome('blocked', False, EXIT_BLOCKED)
    assert harness.git.branch_exists('pr-1')
    assert not harness.git.is_merged_into('pr-1', 'integration')

    # Resume: the stale branch is dropped and recreated, so `checkout -b` cannot collide
    # and the PR is re-attempted from the current integration state.
    spawn = MarkerSpawn([ok_result()], markers_for=['junk.txt'])
    outcome = _resume_run(series, harness, spawn, 'run-2', resume=True)

    assert outcome == RunOutcome('blocked', False, EXIT_BLOCKED)  # still red, but it RAN
    assert len(spawn.calls) == 1
    assert _skips(harness.outputs, 'run-2') == []


# --- self-describing halts ---------------------------------------------------
#
# Before this, run_complete said only THAT a run stopped. "Which PR, in which phase, and
# how close to which cap" -- the first question a halted run raises -- meant hand-reading
# the ledger. These assert the terminal record answers it on its own.


def _budget_result(cost_usd: float) -> SpawnResult:
    return SpawnResult(
        exit_code=1,
        classification='budget',
        output='error_max_budget_usd',
        economy=SpawnEconomy(
            input_tokens=100,
            output_tokens=10,
            num_turns=2,
            duration_s=3.0,
            cost_usd=cost_usd,
            effective_model='test-model',
        ),
    )


def _run_complete(outputs: Path, run_id: str) -> dict[str, object]:
    (event,) = [
        e for e in _events_of(_read_events(outputs), 'run_complete') if e['run_id'] == run_id
    ]
    return event


def test_a_budget_halt_names_the_pr_phase_and_spend_against_the_cap(harness: Harness) -> None:
    series = replace(
        harness.series,
        checks=(Check(name='green', run=_PASS_CMD, blocking=True),),
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),),
    )
    outcome = run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([_budget_result(1.07)]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-budget',
    )
    assert outcome == RunOutcome('budget', False, EXIT_BUDGET)

    halt = _run_complete(harness.outputs, 'run-budget')['halt']
    assert halt['pr_id'] == 'pr-1'
    assert halt['phase'] == 'core'
    assert halt['role'] == 'implementation'
    assert halt['spend_usd'] == 1.07
    # The implementation ceiling from the harness series, not a fix or review one.
    assert halt['cap_usd'] == series.governance.budgets.implementation


def test_a_fix_budget_halt_reports_the_fix_ceiling_not_the_implementation_one(
    harness: Harness,
) -> None:
    """A repair exhausting its own smaller cap is a different diagnosis, so it must not
    be reported against the implementation budget."""
    series = replace(
        harness.series,
        review=Review(blocking=True, max_fix_attempts=1),
        checks=(Check(name='red', run=_FAIL_CMD, blocking=True),),
        governance=replace(
            harness.series.governance,
            budgets=Budgets(implementation=9.0, review=1.0, fix=0.25),
        ),
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),),
    )
    outcome = run_series(
        series,
        harness.repo,
        # implementation ok, then the FIX spawn is budget-cut
        spawn=FakeSpawn([ok_result(), _budget_result(0.26)]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-fixbudget',
    )
    assert outcome == RunOutcome('budget', False, EXIT_BUDGET)

    halt = _run_complete(harness.outputs, 'run-fixbudget')['halt']
    assert halt['role'] == 'fix'
    assert halt['cap_usd'] == 0.25
    assert halt['cap_usd'] != 9.0


def test_a_blocked_halt_reports_the_gate_and_no_money(harness: Harness) -> None:
    """No ceiling caused it, so reporting one would send the reader after the wrong fix."""
    series = replace(
        harness.series,
        review=Review(blocking=True, max_fix_attempts=0),
        checks=(Check(name='red', run=_FAIL_CMD, blocking=True),),
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),),
    )
    outcome = run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result()]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-blocked',
    )
    assert outcome == RunOutcome('blocked', False, EXIT_BLOCKED)

    halt = _run_complete(harness.outputs, 'run-blocked')['halt']
    assert halt['pr_id'] == 'pr-1'
    assert halt['phase'] == 'core'
    assert halt['role'] == 'gate'
    assert halt['spend_usd'] is None
    assert halt['cap_usd'] is None


def test_a_clean_run_carries_no_halt(harness: Harness) -> None:
    series = replace(
        harness.series,
        checks=(Check(name='green', run=_PASS_CMD, blocking=True),),
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),),
    )
    outcome = run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result()]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-clean',
    )
    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert _run_complete(harness.outputs, 'run-clean')['halt'] is None


def test_every_spawn_line_records_its_classification(harness: Harness) -> None:
    """The verdict that drove control flow is now on the line, not inferred from exit_code.

    A budget cut and an auth failure can both exit 1, so the inference a consumer had to
    make was wrong exactly when it mattered.
    """
    series = replace(
        harness.series,
        checks=(Check(name='green', run=_PASS_CMD, blocking=True),),
        prs=(PR(id='pr-1', branch='pr-1', prompt='impl.md', phase='core'),),
    )
    run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([_budget_result(0.5)]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-class',
    )
    spawns = [
        e
        for e in _events_of(_read_events(harness.outputs), 'spawn_complete')
        if e['run_id'] == 'run-class'
    ]
    assert [e['classification'] for e in spawns] == ['budget']


# --- commit subjects ----------------------------------------------------------------------
#
# The sweep after each spawn commits whatever the agent left uncommitted, so its message is
# the message of record on the integration branch. It used to be the bare PR id, which is
# also the branch name -- the one thing a reader could already get elsewhere.


def _log_subjects(repo: Path, ref: str) -> list[str]:
    """Every commit subject on ``ref``, newest first."""
    result = subprocess.run(
        ['git', 'log', '--pretty=%s', ref],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def test_commit_subject_uses_the_prompts_heading() -> None:
    subject = _commit_subject('pr-1', '# Wire the queue consumer\n\nDetails follow.\n')
    assert subject == 'pr-1: Wire the queue consumer'


def test_commit_subject_uses_a_prose_opening_line_and_skips_blanks() -> None:
    subject = _commit_subject('pr-1', '\n\n  Add a retry policy.  \n\nMore text.\n')
    assert subject == 'pr-1: Add a retry policy.'


def test_commit_subject_cuts_a_long_line_at_a_word_boundary() -> None:
    """convoy's own starter prompt opens with an 85-character sentence."""
    line = 'Create a file named `greeting.txt` in the repository root containing exactly one line:'

    subject = _commit_subject('pr-1', f'{line}\n\nhello convoy\n')

    assert len(subject) <= 72
    assert subject.startswith('pr-1: Create a file named ')
    assert subject.endswith('...')
    # What survived is a prefix of the original ending on a word boundary, not mid-word.
    kept = subject[len('pr-1: ') : -len('...')]
    assert line.startswith(kept)
    assert line[len(kept)] == ' '


def test_commit_subject_falls_back_to_the_bare_id_for_an_empty_brief() -> None:
    assert _commit_subject('pr-1', '') == 'pr-1'
    assert _commit_subject('pr-1', '   \n\n\t\n') == 'pr-1'


def test_commit_subject_falls_back_when_the_opening_line_is_not_a_title() -> None:
    """A frontmatter fence or a code fence is punctuation, not a summary."""
    assert _commit_subject('pr-1', '---\ntitle: something\n---\n') == 'pr-1'
    assert _commit_subject('pr-1', '```\ncode\n```\n') == 'pr-1'
    assert _commit_subject('pr-1', '#\n\nbody\n') == 'pr-1'


def test_commit_subject_falls_back_when_the_id_leaves_no_room() -> None:
    """A stub of a sentence carries no information, so it is dropped rather than shown."""
    long_id = 'pr-' + 'x' * 60

    assert _commit_subject(long_id, 'Add a retry policy.\n') == long_id


def test_the_swept_commit_names_the_work_not_just_the_pr_id(harness: Harness) -> None:
    """End to end: the message on the integration branch carries the prompt's opening line."""
    series = _one_pr_series(harness.series)  # prompt impl.md: 'Implement the thing.'
    spawn = MarkerSpawn([ok_result()], markers_for=('marker-1',))

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-subject',
    )

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert 'pr-1: Implement the thing.' in _log_subjects(harness.repo, 'integration')


def test_a_swept_fix_commit_names_the_work_it_repairs(harness: Harness) -> None:
    """The PR's own brief, so both commits name the same work; ``-fix-N`` says which is which."""
    series = _marker_series(harness, max_fix_attempts=2)
    spawn = FixMarkerSpawn([ok_result(), ok_result()], fix_creates_marker=True)

    outcome = run_series(
        series,
        harness.repo,
        spawn=spawn,
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-fix-subject',
    )

    assert outcome == RunOutcome('completed', True, EXIT_OK)
    assert 'pr-1-fix-1: Implement the thing.' in _log_subjects(harness.repo, 'integration')


# --- advisories on the run_start line -----------------------------------------------------
#
# They ride the terminal-of-the-beginning line for the same reason `halt` rides
# `run_complete`: it keeps the fact reconstructible from the ledger alone, so every
# consumer of a run sees it without the value being threaded through control flow.


def _advisory(pr_id: str = 'pr-1') -> Advisory:
    return Advisory(
        kind='gate',
        where=f'[[prs]] {pr_id!r}',
        message='no blocking check gates this phase, so this PR integrates unverified',
    )


def test_the_run_start_line_carries_the_advisories(harness: Harness) -> None:
    series = _one_pr_series(harness.series)

    run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result()]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-advisory',
        advisories=[_advisory()],
    )

    starts = _events_of(_read_events(harness.outputs), 'run_start')
    assert starts[0]['advisories'] == [
        {
            'kind': 'gate',
            'where': "[[prs]] 'pr-1'",
            'message': 'no blocking check gates this phase, so this PR integrates unverified',
        }
    ]


def test_an_ordinary_run_start_line_carries_an_empty_list(harness: Harness) -> None:
    """Present and empty, not absent — a consumer reads the key unconditionally."""
    series = _one_pr_series(harness.series)

    run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result()]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-quiet',
    )

    starts = _events_of(_read_events(harness.outputs), 'run_start')
    assert starts[0]['advisories'] == []


def test_the_reporter_narrates_advisories_right_after_the_run_header(harness: Harness) -> None:
    """The operator whose run is about to integrate it is the one who needs to hear it."""
    series = _one_pr_series(harness.series)
    rec = RecordingReporter()

    run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result()]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-narrate',
        reporter=rec,
        advisories=[_advisory()],
    )

    assert rec.names()[:2] == ['run_start', 'advisories']


def test_a_quiet_run_does_not_fire_the_advisory_hook(harness: Harness) -> None:
    series = _one_pr_series(harness.series)
    rec = RecordingReporter()

    run_series(
        series,
        harness.repo,
        spawn=FakeSpawn([ok_result()]),
        git=harness.git,
        gate_runner=harness.gate_runner,
        telemetry=TelemetryWriter(harness.outputs / 'spawns.jsonl'),
        run_id='run-narrate-quiet',
        reporter=rec,
    )

    assert 'advisories' not in rec.names()
