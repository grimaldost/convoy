"""The headless driver — the ``convoy run`` engine (shell).

This is the run loop: stage on the base branch, walk the dependency-ordered PRs,
and integrate as it goes. Each PR branches off the *accumulated* integration
state, so a dependent sees its predecessors' merged work; its implementation is
spawned, committed, and gated, and a green PR is merged onto the integration
branch immediately — before the next PR branches from it. Every agent spawn is
economy-accounted to the telemetry file; the run ends with a single
``run_complete`` carrying its outcome, leaving the integration tree checked out
when the whole series is green.

The loop is deliberately fail-loud: a blocking red is never integrated over. On a
blocking red the driver runs a *bounded* fix loop — up to
``series.review.max_fix_attempts`` fix spawns, re-running the gate after each — and
integrates only if the gate goes green; if it is still red after the attempts the
run halts ``blocked`` and processes no later PR, so a dependent of a failed PR
never runs or integrates. The re-gate is the sole arbiter: a red always blocks
regardless of provenance, so attempting a fix can never make things worse and
green is never emitted while the gate is still ``blocking_red``. An infrastructure
failure — whether from the implementation spawn or a fix spawn — halts before the
gate is trusted so a bad matrix stops cleanly rather than being scored. It iterates
``dag.order`` for a one-PR series exactly as for many, and a one-PR series is
behaviorally identical to integrating once at the end.

The pure decisions (DAG order, gate verdict) live in ``core``; this driver owns
the effects and the orchestration around them, composing the shell adapters
(spawn, git, gate runner, telemetry writer) behind their ports.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex

from convoy.core.dag import order
from convoy.core.gate import GateVerdict, decide
from convoy.core.governance import resolve_spawn
from convoy.core.preflight import Problem
from convoy.core.spec import PR, Series
from convoy.core.telemetry import (
    GateCheckLine,
    GateComplete,
    PRSkipped,
    RunComplete,
    RunStart,
    SpawnComplete,
    apply_cost_fallback,
)
from convoy.interface.gate_runner import GateRunner
from convoy.interface.git import Git
from convoy.interface.reporter import NullReporter, Reporter
from convoy.interface.spawn import AgentSpawn, SpawnRequest, SpawnResult
from convoy.interface.telemetry_writer import TelemetryWriter

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_INFRASTRUCTURE = 2
EXIT_USAGE = 3
EXIT_BUDGET = 4


def format_problems(problems: Sequence[Problem]) -> str:
    """A human-readable summary of pre-flight problems: a count plus one located line each."""
    lines = [f'{len(problems)} problem(s) found:']
    lines += [f'  - {problem.where} [{problem.kind}] {problem.message}' for problem in problems]
    return '\n'.join(lines)


@dataclass(frozen=True)
class RunOutcome:
    """A headless run's result: the coarse outcome, whether it integrated, the exit code."""

    outcome: str  # 'completed' | 'blocked' | 'infrastructure' | 'budget'
    integrated: bool
    exit_code: int


def make_run_id() -> str:
    """A lexicographically-sortable run id: UTC ``%Y%m%dT%H%M%SZ`` plus a short random suffix.

    The timestamp prefix orders runs by start time; the random suffix keeps two
    runs started in the same second distinct.
    """
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    return f'{stamp}-{token_hex(4)}'


def _fix_brief(original_brief: str, verdict: GateVerdict) -> str:
    """The original brief plus an appended section naming each failing blocking check.

    Lists every blocking check that is red, with its ``name`` and ``detail``, so a
    fix agent knows exactly what to repair. Whether any of those reds is
    *independent* is recorded as provenance only — it never changes that the red
    blocks; the re-gate is the arbiter.
    """
    failures = [r for r in verdict.results if not r.passed and r.check.blocking]
    lines = [original_brief, '', '## Failing checks to repair', '']
    if verdict.independent_red:
        lines.append(
            'At least one failing check is independent (author-supplied, unreachable '
            'by you) — its red is a trustworthy signal.'
        )
        lines.append('')
    for result in failures:
        lines.append(f'- {result.check.name}: {result.detail}')
    return '\n'.join(lines)


def _gate_event(run_id: str, pr_id: str, attempt: int, verdict: GateVerdict) -> GateComplete:
    """A ``gate_complete`` event for ``verdict``: one line per check plus the derived flags.

    ``attempt`` is 0 for the initial gate and ``n`` after the nth fix spawn's re-gate.
    """
    checks = tuple(
        GateCheckLine(
            name=result.check.name,
            passed=result.passed,
            blocking=result.check.blocking,
            independent=result.check.independent,
            detail=result.detail,
        )
        for result in verdict.results
    )
    return GateComplete(
        run_id=run_id,
        pr_id=pr_id,
        attempt=attempt,
        blocking_red=verdict.blocking_red,
        independent_red=verdict.independent_red,
        checks=checks,
    )


def _skip_remaining(
    telemetry: TelemetryWriter,
    reporter: Reporter,
    run_id: str,
    ordered: Sequence[PR],
    halted_pr_id: str,
    reason: str,
) -> None:
    """Record every PR after ``halted_pr_id`` in ``ordered`` as skipped — telemetry and reporter.

    Once the series halts on ``halted_pr_id`` no later PR in the dependency order is ever
    processed, so each is recorded as skipped with ``reason``. A halt on the last PR
    writes nothing. ``reason`` states why the series stopped, not a direct dependency edge.
    """
    seen_halt = False
    for pr in ordered:
        if seen_halt:
            telemetry.write(PRSkipped(run_id=run_id, pr_id=pr.id, reason=reason))
            reporter.pr_skipped(pr.id, reason)
        elif pr.id == halted_pr_id:
            seen_halt = True


def _record_spawn(
    telemetry: TelemetryWriter, run_id: str, pr_id: str, role: str, result: SpawnResult
) -> None:
    """Write a ``spawn_complete`` line for ``result`` under ``role`` (with cost fallback)."""
    telemetry.write(
        apply_cost_fallback(
            SpawnComplete(
                run_id=run_id,
                pr_id=pr_id,
                role=role,
                exit_code=result.exit_code,
                input_tokens=result.economy.input_tokens,
                output_tokens=result.economy.output_tokens,
                num_turns=result.economy.num_turns,
                duration_s=result.economy.duration_s,
                cost_usd=result.economy.cost_usd,
                effective_model=result.economy.effective_model,
            )
        )
    )


def run_series(
    series: Series,
    workspace: Path,
    *,
    spawn: AgentSpawn,
    git: Git,
    gate_runner: GateRunner,
    telemetry: TelemetryWriter,
    run_id: str,
    reporter: Reporter | None = None,
) -> RunOutcome:
    """Run ``series`` end-to-end in ``workspace``, returning its outcome.

    Stages on ``series.branches.base``, ensures the integration branch exists,
    then walks ``dag.order(series.prs)`` — always via the DAG, whether one PR or
    many. Per PR: check out the integration branch (so the PR branches off the
    *accumulated* integrated state and a dependent sees its predecessors), branch,
    read the prompt, spawn the implementation, record its economy, and (unless the
    spawn was an infrastructure failure) commit and run the gate. A green PR is
    merged onto ``series.branches.integration`` immediately, before the next PR
    branches from it. A blocking red does not integrate; instead the driver runs a
    bounded fix loop (up to ``series.review.max_fix_attempts`` fix spawns, re-gating
    after each) and integrates only if the gate turns green. If it is still red
    after the attempts the run halts ``blocked`` and processes no later PR, so a
    dependent of a failed PR never runs or integrates; an infrastructure
    classification (from the implementation or a fix spawn) halts before the gate is
    trusted. Green is never emitted while the gate is still ``blocking_red``. When
    every PR is green, the integration branch — carrying every PR's work — is left
    checked out.
    """
    reporter = reporter if reporter is not None else NullReporter()
    telemetry.write(RunStart(run_id=run_id, series_id=series.id))
    reporter.run_start(series.id, run_id, len(series.prs))

    # Stage on base, then create the integration branch from it. v1 requires a CLEAN
    # base: this creates the integration branch (and each PR branch below) with
    # ``git checkout -b``, which fails loud if the branch already exists — so a re-run
    # must first reset the workspace to base and delete the prior integration / PR
    # branches (see "Limits and re-runs" in the convoy skill). Every PR below branches
    # off the accumulated integration state rather than off base.
    git.checkout(series.branches.base)
    git.checkout(series.branches.integration, create=True)

    ordered = order(series.prs)
    for pr in ordered:
        # Branch off the accumulated integration state so this PR builds on every
        # predecessor already merged onto the integration branch.
        git.checkout(series.branches.integration)
        git.checkout(pr.branch, create=True)

        # UTF-8 pinned, replacement over crash: by here money is already spent on the
        # series, so a stray byte in a prompt degrades the brief instead of halting it.
        brief = (Path(series.paths.prompts) / pr.prompt).read_text(
            encoding='utf-8', errors='replace'
        )

        governed = resolve_spawn(series.governance, 'implementation')
        request = SpawnRequest(
            brief=brief,
            model=governed.model,
            effort=governed.effort,
            permission_mode=governed.permission_mode,
            budget_usd=governed.budget_usd,
            tools=governed.tools,
            timeout_seconds=governed.timeout_seconds,
        )
        result = spawn.spawn(request, workspace)
        _record_spawn(telemetry, run_id, pr.id, 'implementation', result)
        reporter.spawn_done(pr.id, 'implementation', result)

        if result.classification == 'infrastructure':
            reason = f'series halted at {pr.id} (infrastructure) before this PR started'
            _skip_remaining(telemetry, reporter, run_id, ordered, pr.id, reason)
            telemetry.write(RunComplete(run_id=run_id, outcome='infrastructure', integrated=False))
            reporter.run_done('infrastructure', False)
            return RunOutcome('infrastructure', False, EXIT_INFRASTRUCTURE)

        if result.classification == 'budget':
            # A budget-truncated spawn is untrustworthy partial work: halt the PR before
            # committing, gating, or integrating it. Distinct outcome/exit for an observer.
            reason = f'series halted at {pr.id} (budget) before this PR started'
            _skip_remaining(telemetry, reporter, run_id, ordered, pr.id, reason)
            telemetry.write(RunComplete(run_id=run_id, outcome='budget', integrated=False))
            reporter.run_done('budget', False)
            return RunOutcome('budget', False, EXIT_BUDGET)

        git.commit_all(pr.id)

        # Gate the PR, then repair on a blocking red. The re-gate after each fix is
        # the sole arbiter: a red always blocks regardless of provenance, so
        # attempting a fix never makes things worse and green is never emitted while
        # the gate is still red. Bounded by ``series.review.max_fix_attempts`` — zero
        # means a blocking red halts immediately with no fix spawn.
        verdict = decide(gate_runner.run(workspace, series.checks))
        telemetry.write(_gate_event(run_id, pr.id, 0, verdict))
        reporter.gate_result(pr.id, 0, verdict)
        attempts = 0
        while verdict.blocking_red and attempts < series.review.max_fix_attempts:
            attempts += 1
            reporter.fix_attempt(pr.id, attempts, series.review.max_fix_attempts)
            governed = resolve_spawn(series.governance, 'fix')
            fix_request = SpawnRequest(
                brief=_fix_brief(brief, verdict),
                model=governed.model,
                effort=governed.effort,
                permission_mode=governed.permission_mode,
                budget_usd=governed.budget_usd,
                tools=governed.tools,
                timeout_seconds=governed.timeout_seconds,
            )
            fix_result = spawn.spawn(fix_request, workspace)
            _record_spawn(telemetry, run_id, pr.id, 'fix', fix_result)
            reporter.spawn_done(pr.id, 'fix', fix_result)

            if fix_result.classification == 'infrastructure':
                reason = f'series halted at {pr.id} (infrastructure) before this PR started'
                _skip_remaining(telemetry, reporter, run_id, ordered, pr.id, reason)
                telemetry.write(
                    RunComplete(run_id=run_id, outcome='infrastructure', integrated=False)
                )
                reporter.run_done('infrastructure', False)
                return RunOutcome('infrastructure', False, EXIT_INFRASTRUCTURE)

            if fix_result.classification == 'budget':
                reason = f'series halted at {pr.id} (budget) before this PR started'
                _skip_remaining(telemetry, reporter, run_id, ordered, pr.id, reason)
                telemetry.write(RunComplete(run_id=run_id, outcome='budget', integrated=False))
                reporter.run_done('budget', False)
                return RunOutcome('budget', False, EXIT_BUDGET)

            git.commit_all(f'{pr.id}-fix-{attempts}')
            verdict = decide(gate_runner.run(workspace, series.checks))
            telemetry.write(_gate_event(run_id, pr.id, attempts, verdict))
            reporter.gate_result(pr.id, attempts, verdict)

        if verdict.blocking_red:
            _skip_remaining(
                telemetry,
                reporter,
                run_id,
                ordered,
                pr.id,
                f'series halted at {pr.id} (blocked) before this PR started',
            )
            telemetry.write(RunComplete(run_id=run_id, outcome='blocked', integrated=False))
            reporter.run_done('blocked', False)
            return RunOutcome('blocked', False, EXIT_BLOCKED)

        # Green: integrate this PR now so the next one branches from it. git.merge
        # checks out the integration branch and leaves it checked out.
        git.merge(pr.branch, series.branches.integration)
        reporter.integrated(pr.id)

    telemetry.write(RunComplete(run_id=run_id, outcome='completed', integrated=True))
    reporter.run_done('completed', True)
    return RunOutcome('completed', True, EXIT_OK)
