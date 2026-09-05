"""convoy command-line interface."""

import json
import os
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from convoy import __version__
from convoy.core.gate import GateUsageError
from convoy.core.governance import GovernanceError
from convoy.core.preflight import Problem
from convoy.core.spec import Series, SpecError, load_gate_spec, load_series
from convoy.interface.drivers.headless import (
    EXIT_OK,
    EXIT_USAGE,
    format_advisories,
    format_problems,
    make_run_id,
)
from convoy.interface.fs_probe import isolation_result
from convoy.interface.gate_scaffold import GateScaffoldError, scaffold_gate
from convoy.interface.gate_service import (
    advisory_only_detail,
    find_gate_spec,
    gate_brief_envelope,
    gate_envelope,
    gate_root,
    gate_spec_env,
    gate_usage_envelope,
    load_gate_spec_file,
    resolve_gate_spec,
    run_gate,
    trust_project,
    trust_status,
)
from convoy.interface.git import Git, GitError
from convoy.interface.hook import run_hook
from convoy.interface.preflight_probe import preflight
from convoy.interface.reporter import NullReporter, Reporter, StderrReporter
from convoy.interface.run_service import (
    PreflightError,
    abandon_orphaned_run,
    run_series_headless,
)
from convoy.interface.run_summary import error_kind, orphaned_run_id, status_of, summarize_run
from convoy.interface.scaffold import ScaffoldError, scaffold
from convoy.interface.streams import harden_std_streams
from convoy.interface.workspace_lock import WorkspaceBusyError, lock_path, remove_stale_lock

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


def _read_or_exit(series_file: Path) -> str:
    """Read ``series_file`` as UTF-8, or exit ``EXIT_USAGE`` with a message."""
    try:
        return series_file.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError: the read is pinned to UTF-8, so a legacy-encoded file is a
        # usage error like malformed TOML — never an uncaught traceback.
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc


def _load_or_exit(series_file: Path) -> Series:
    """Read and structurally parse ``series_file``, or exit ``EXIT_USAGE`` with a message."""
    try:
        return load_series(_read_or_exit(series_file))
    except SpecError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc


_WORKSPACE_HELP = (
    'The git repository to operate on (the scored tree). Defaults to the current '
    'directory, which is what the workspace was implicitly before this option existed.'
)


_STATUS_WORKSPACE_HELP = (
    'The git repository the run operates on. Read for one thing: the run lock names its '
    'owner, which is what separates a run still going from one whose driver is gone. '
    'Defaults to the current directory; nothing is written to it.'
)


def _workspace_or_exit(workspace: Path | None) -> Path:
    """Resolve the workspace — ``--workspace`` when given, else the cwd — or exit ``EXIT_USAGE``.

    Resolved at call time, never at import: a module-level ``Path.cwd()`` default would
    freeze whatever directory the process started in. A path that is not an existing
    directory fails here with one located message, rather than surfacing later as a
    confusing git or filesystem error against a tree that was never there.
    """
    resolved = Path.cwd() if workspace is None else workspace
    if not resolved.is_dir():
        typer.echo(f'workspace is not an existing directory: {resolved}', err=True)
        raise typer.Exit(EXIT_USAGE)
    return resolved


# The four tables that only an orchestration series has. ``load_gate_spec`` reads none
# of them, so a file carrying any one of them is a series whatever else is wrong with it,
# and must never be answered with a gate's narrower yes. ``[governance]`` is absent from
# the set on purpose: the gate loader does read one field from it, so a gate-only file
# may legitimately carry it.
_SERIES_ONLY_TABLES = frozenset({'branches', 'paths', 'review', 'prs'})


def _is_gate_shaped(text: str) -> bool:
    """Whether ``text`` carries no orchestration table, and so may be read as a gate.

    Shape, not validity: a file that answers yes here still has to satisfy
    ``load_gate_spec``. Unparseable TOML is not gate-shaped — the series loader has
    already produced the better message for it.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    return not (_SERIES_ONLY_TABLES & data.keys())


def _validate_gate_only_or_exit(
    text: str, workspace: Path | None, series_error: SpecError, series_file: Path | None = None
) -> None:
    """Validate ``text`` as a gate-only file, or report the series failure it really is.

    Reached only when :func:`load_series` has already refused ``text``. The gate loader
    reads just ``[series] id``, ``[[checks]]`` and one ``[governance]`` field, so it
    accepts any series whose defect lies in a section it ignores — which would turn every
    broken orchestration file into a passing gate. ``_is_gate_shaped`` is the guard: a
    file carrying ``[branches]``, ``[paths]``, ``[review]`` or ``[[prs]]`` is reported as
    the broken series it is, exit code included.

    For a file that is gate-shaped and loads, the pre-flight that remains meaningful is
    the pair of refusals ``convoy gate`` can decide from the spec alone: a selection with
    no blocking check assures nothing, and a blocking independent check whose oracle is
    in-tree or absent makes the gate self-graded. Both are told before the checks cost
    anything, in the gate's own words. The phase-dependent refusals are left to the gate,
    which alone takes ``--phase``.

    When both loaders refuse, ``series_error`` is reported unchanged — a file that meant
    to be a series should not be told it is a bad gate.
    """
    if not _is_gate_shaped(text):
        typer.echo(str(series_error), err=True)
        raise typer.Exit(EXIT_USAGE)
    try:
        # A project spec is entitled to the same environment `convoy gate` gives it,
        # or validate would blame a missing table for an unset CONVOY_ORACLES.
        env = gate_spec_env(series_file, os.environ) if series_file is not None else os.environ
        spec = load_gate_spec(text, env=env)
    except SpecError as exc:
        typer.echo(str(series_error), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    if not any(check.blocking for check in spec.checks):
        typer.echo(advisory_only_detail(spec.checks), err=True)
        raise typer.Exit(EXIT_USAGE)
    target = _workspace_or_exit(workspace)
    refused = [result for check in spec.checks if (result := isolation_result(target, check))]
    if refused:
        problems = [
            Problem(kind='isolation', where=f'[[checks]] {r.check.name!r}', message=r.detail)
            for r in refused
        ]
        typer.echo(format_problems(problems), err=True)
        raise typer.Exit(EXIT_USAGE)
    typer.echo('ok (gate-only)')


@app.command()
def validate(
    series_file: Path,
    workspace: Annotated[
        Path | None, typer.Option('--workspace', '-w', help=_WORKSPACE_HELP)
    ] = None,
) -> None:
    """Validate a series without running it: structure, model resolution, paths, gate isolation.

    The filesystem checks — ``[paths]`` existence, ``outputs`` out-of-tree, and
    independent-check asset isolation — are evaluated against ``--workspace`` (default:
    the current directory), so validate against the same tree you will run against.

    Advisories (a PR that phase-scoped checks leave ungated) print to stderr and do NOT
    change the exit code: stdout stays ``ok`` and the exit stays 0, because an advisory
    describes an unusual series, not an invalid one.

    A **gate-only** file — one carrying just ``[series] id`` and ``[[checks]]``, the
    input ``convoy gate`` accepts — is validated as the gate it is rather than rejected
    as a series missing its orchestration sections. It gets the two refusals that stay
    decidable without a run, both in ``convoy gate``'s own words: the selection must
    contain a blocking check, and every blocking independent check must back its
    isolation. Stdout then says ``ok (gate-only)``, naming the narrower answer.

    The narrower answer is only ever given to a file that is actually gate-shaped. A
    file carrying ``[branches]``, ``[paths]``, ``[review]`` or ``[[prs]]`` is an
    orchestration series, so a defect anywhere in it is reported as a broken series —
    the series loader's message and exit ``3``, never a gate's pass. Without that guard
    the gate loader, which ignores all four sections, would validate any series that had
    quietly lost one.
    """
    text = _read_or_exit(series_file)
    try:
        series = load_series(text)
    except SpecError as series_error:
        _validate_gate_only_or_exit(text, workspace, series_error, series_file)
        return
    report = preflight(series, _workspace_or_exit(workspace))
    if report.advisories:
        typer.echo(format_advisories(report.advisories), err=True)
    if not report.clean:
        typer.echo(format_problems(report.problems), err=True)
        raise typer.Exit(EXIT_USAGE)
    typer.echo('ok')


def _gate_usage_exit(
    exc: Exception, json_summary: bool, series_id: str | None = None
) -> typer.Exit:
    """Report a gate usage failure on both channels and build the ``EXIT_USAGE`` exit.

    Under ``--json`` stdout still carries exactly one parseable object — the same usage
    envelope the MCP tool returns — because the failure case is the one a machine
    consumer most needs to classify (the reasoning ``run``'s ``_emit_failure_json``
    already records).
    """
    if json_summary:
        typer.echo(
            json.dumps(gate_usage_envelope(exc, error_kind=error_kind(exc), series_id=series_id))
        )
    typer.echo(str(exc), err=True)
    return typer.Exit(EXIT_USAGE)


@app.command()
def gate(
    series_file: Annotated[
        Path | None,
        typer.Argument(
            help=(
                'The file holding the [[checks]] to run: a full series.toml, or a minimal '
                '[series] id + [[checks]] file. Omitted, the project gate spec is used: '
                '$CLAUDE_PROJECT_DIR/.convoy/gate.toml, then .convoy/gate.toml in the '
                'workspace and its parents; none found is a usage failure.'
            ),
            show_default=False,
        ),
    ] = None,
    workspace: Annotated[
        Path | None, typer.Option('--workspace', '-w', help=_WORKSPACE_HELP)
    ] = None,
    phase: Annotated[
        list[str],
        typer.Option(
            '--phase',
            help=(
                'Run the checks a PR carrying this phase tag would be gated on — the '
                'unscoped checks plus the ones scoped to it. Repeatable (tags union). '
                'Without it, the whole gate runs. A tag no check declares is refused '
                '(usage), not silently narrowed to a green.'
            ),
        ),
    ]
    | None = None,
    json_summary: Annotated[
        bool,
        typer.Option(
            '--json',
            help=(
                'Print the gate envelope to stdout as one JSON object — the same envelope '
                'the MCP tool returns. Without it, stdout carries only the outcome word.'
            ),
        ),
    ] = False,
    brief: Annotated[
        bool,
        typer.Option(
            '--brief',
            help=(
                'Print the compact envelope — {ok, outcome, repair_brief, convoy_version} '
                '— as one JSON object, for a caller that reads the verdict inside a model '
                'turn and wants nothing else in it. Usage paths print the usage envelope, '
                'as under --json.'
            ),
        ),
    ] = False,
    init: Annotated[
        bool,
        typer.Option(
            '--init',
            help=(
                'Scaffold the project gate spec at .convoy/gate.toml (plus a .gitignore for '
                "the hook log) from the toolchain found in the workspace — the project's "
                'own suite as blocking, non-independent checks — and exit. Refuses to '
                'overwrite. Nothing detected writes a placeholder check that stays red '
                'until you declare the checks.'
            ),
        ),
    ] = False,
    independent: Annotated[
        str | None,
        typer.Option(
            '--independent',
            metavar='NAME',
            help=(
                'With --init: also scaffold a held-out oracle NAME.py under CONVOY_ORACLES '
                '(default ~/.convoy/oracles/<project dir name>/) and declare it as a '
                'blocking independent check referencing ${CONVOY_ORACLES}. The placeholder '
                'stays red until written — write it before dispatching any implementer.'
            ),
        ),
    ] = None,
    trust: Annotated[
        bool,
        typer.Option(
            '--trust',
            help=(
                'Arm the hook for this workspace: record its root in the per-machine trust '
                'list (CONVOY_HOME/hook-trust.toml, default ~/.convoy/), which the hook '
                "requires before it runs a project's checks — a cloned .convoy/gate.toml "
                'must not run commands on dispatch until you say so. Needs an existing '
                'project spec; --init trusts the project it scaffolds.'
            ),
        ),
    ] = False,
) -> None:
    """Run a series' ``[[checks]]`` against a workspace once — no spawn, no branch, no merge.

    The gate framework standalone: for verifying work produced *outside* convoy (an
    external orchestrator's diff, a hand-written branch) with the same deterministic
    checks, the same fail-closed independence guard, and the same verdict rules a
    governed run applies after every PR. ``series_file`` may be a full series.toml or a
    minimal file carrying only ``[series] id`` and ``[[checks]]``.

    Per-check narration goes to stderr; stdout carries the outcome word (``completed`` /
    ``blocked``), or exactly one JSON object under ``--json`` — on the usage paths too,
    where the object is the same usage envelope the MCP tool returns. Exit codes are
    the run's own: 0 green (a non-blocking red advises without blocking), 1 blocking
    red, 3 usage. Convoy writes nothing to the workspace and takes no lock — but the
    check commands run in the tree and may write (caches, build output), so do not gate
    a workspace a ``convoy run`` is actively driving: beyond gating whatever that
    driver has checked out, the run's commit step stages the whole tree and can commit
    a concurrent gate's artifacts into a scored branch.
    """
    machine = json_summary or brief
    # The workspace first: discovery starts from it, so a gate invoked from anywhere
    # with `-w <project>` finds that project's spec, not the invoking directory's.
    target = _workspace_or_exit(workspace)
    if independent is not None and not init:
        typer.echo('--independent needs --init: it scaffolds a check into a new spec', err=True)
        raise typer.Exit(EXIT_USAGE)
    if init:
        try:
            written = scaffold_gate(target, os.environ, independent=independent)
        except (OSError, GateScaffoldError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_USAGE) from exc
        for path in written:
            typer.echo(f'created {path}')
        # Arming is a second, deliberate act: the scaffold is red until edited, and the
        # hook must not start blocking every subagent with a brief nothing can satisfy.
        typer.echo(
            f'next: edit .convoy/gate.toml, then `convoy gate --trust --workspace {target}` '
            f'to arm the hook'
        )
        raise typer.Exit(EXIT_OK)
    if trust:
        try:
            found = find_gate_spec(target, os.environ)
        except SpecError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_USAGE) from exc
        if found is None:
            typer.echo(
                f'nothing to arm: no .convoy/gate.toml found from {target.resolve()} '
                f'(run `convoy gate --init` to scaffold one)',
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        root = gate_root(found, target)
        try:
            trust_path = trust_project(root, os.environ, found)
        except (OSError, SpecError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_USAGE) from exc
        typer.echo(f'trusted {root} for the hook, spec {found} pinned ({trust_path})')
        raise typer.Exit(EXIT_OK)
    try:
        spec_path = resolve_gate_spec(series_file, target, os.environ)
        root = gate_root(spec_path, target) if series_file is None else None
        spec = load_gate_spec_file(spec_path, os.environ, root=root)
    except (OSError, UnicodeDecodeError, SpecError) as exc:
        raise _gate_usage_exit(exc, machine) from exc
    if series_file is None:
        # A discovered project spec runs here because the operator asked; the hook would
        # not run it until the project is trusted, and a silent difference between the
        # two surfaces is exactly what an operator cannot see. Say so.
        try:
            status = trust_status(gate_root(spec_path, target), spec_path, os.environ)
        except SpecError as exc:
            status = 'untrusted'
            typer.echo(f'note: {exc}', err=True)
        if status == 'changed':
            typer.echo(
                'note: the gate spec changed since the hook was armed; run `convoy gate '
                '--trust` again to re-arm it',
                err=True,
            )
        elif status != 'trusted':
            typer.echo(
                'note: the hook is not armed for this project; run `convoy gate --trust` to arm it',
                err=True,
            )
    phases = tuple(phase or ())
    try:
        outcome = run_gate(spec, target, phases)
    except GateUsageError as exc:
        raise _gate_usage_exit(exc, machine, spec.id) from exc
    except OSError as exc:
        # A workspace vanishing mid-gate, a dead mount, an unspawnable shell: a usage
        # failure, never a traceback — and never exit 1, which would read as a blocking
        # red to a caller watching only the exit code (same rule as `run`).
        raise _gate_usage_exit(exc, machine, spec.id) from exc

    for result in outcome.verdict.results:
        mark = 'ok ' if result.passed else 'RED'
        line = f'  [{mark}] {result.check.name}'
        if not result.passed and result.detail:
            line += f' — {result.detail}'
        typer.echo(line, err=True)

    if brief:
        typer.echo(json.dumps(gate_brief_envelope(outcome)))
    elif json_summary:
        typer.echo(json.dumps(gate_envelope(spec, target, outcome)))
    else:
        typer.echo('blocked' if outcome.verdict.blocking_red else 'completed')
    raise typer.Exit(outcome.exit_code)


def _emit_failure_json(
    enabled: bool,
    series_id: str,
    *,
    problems: Sequence[Problem] = (),
    exc: Exception | None = None,
) -> None:
    """Under ``--json``, print the could-not-start envelope — the MCP tool's shape exactly.

    A machine consumer needs one parseable object per invocation, not a parseable object
    on the happy path and prose on stderr otherwise; the failure case is the one it most
    needs to classify. Reuses ``error_kind`` rather than restating the taxonomy, so the two
    surfaces cannot drift on what counts as ``spec`` versus ``git`` versus ``busy``.
    """
    if not enabled:
        return
    envelope: dict[str, object] = {'ok': False, 'outcome': 'usage', 'series_id': series_id}
    if problems:
        envelope['problems'] = [asdict(problem) for problem in problems]
    if exc is not None:
        envelope['error_kind'] = error_kind(exc)
        envelope['error'] = str(exc)
    typer.echo(json.dumps(envelope))


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
    fresh: bool = typer.Option(
        False,
        '--fresh',
        help=(
            'DESTRUCTIVE. Restore the workspace to base before running — discard '
            'uncommitted changes, delete untracked files, delete prior integration/PR '
            'branches — so a completed or halted run can be re-run cleanly. Same steps as '
            '`convoy clean`; run that with --dry-run first to see them.'
        ),
    ),
    resume: Annotated[
        bool,
        typer.Option(
            '--resume',
            help=(
                'Continue the existing integration branch, skipping every PR whose work '
                'it already contains, so a halted run does not re-spend on PRs that '
                'already gated green. Mutually exclusive with --fresh.'
            ),
        ),
    ] = False,
    workspace: Annotated[
        Path | None, typer.Option('--workspace', '-w', help=_WORKSPACE_HELP)
    ] = None,
    json_summary: Annotated[
        bool,
        typer.Option(
            '--json',
            help=(
                'Print the run summary to stdout as one JSON object — the same envelope '
                'the MCP tool returns. Off by default so stdout stays empty for a caller '
                'that only reads the exit code.'
            ),
        ),
    ] = False,
    pinned_run_id: Annotated[
        str,
        typer.Option(
            '--run-id',
            help=(
                'Use this run id instead of minting one, for a caller that must know the '
                'id before the run starts. An id the ledger already holds lines for is '
                'refused, since folding two runs under one id is undetectable downstream.'
            ),
        ),
    ] = '',
) -> None:
    """Run a convoy series headless.

    With ``--json``, stdout carries exactly one JSON object and nothing else, whatever
    happened: the run envelope (outcome, exit code, economy totals, the per-PR view, and
    the ``telemetry_path`` holding the full trace) for a run that executed, or the same
    ``outcome: "usage"`` shape the MCP tool returns for a run that could not start.
    Progress narration is on stderr either way, so it never contaminates the object.
    The exit code is unchanged — ``--json`` adds output, it does not replace the contract.
    """
    series = _load_or_exit(series_file)
    target = _workspace_or_exit(workspace)
    run_id = pinned_run_id or make_run_id()
    try:
        outcome = run_series_headless(
            series,
            target,
            run_id=run_id,
            config_isolation=not _isolation_disabled(os.environ, no_config_isolation),
            reporter=_select_reporter(quiet),
            fresh=fresh,
            resume=resume,
        )
    except PreflightError as exc:
        # A misconfigured series fails fast and whole, before any git mutation or spawn.
        _emit_failure_json(json_summary, series.id, problems=exc.problems)
        typer.echo(format_problems(exc.problems), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except WorkspaceBusyError as exc:
        # Another run already holds the workspace lock — fail loud, not a traceback.
        _emit_failure_json(json_summary, series.id, exc=exc)
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except (GovernanceError, GitError, OSError) as exc:
        # A resolvable-only-at-runtime misconfiguration, or a git / filesystem failure, must
        # not escape as a traceback and must not collide with EXIT_BLOCKED — map to EXIT_USAGE.
        _emit_failure_json(json_summary, series.id, exc=exc)
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    if json_summary:
        # The same fold the MCP tool returns, from the same module — so the two surfaces
        # can never report different totals for one run, and a CLI-driven consumer stops
        # re-implementing the per-spawn fold over the raw ledger.
        typer.echo(
            json.dumps(
                summarize_run(
                    Path(series.paths.outputs) / 'spawns.jsonl',
                    run_id=run_id,
                    series_id=series.id,
                    outcome=outcome,
                )
            )
        )
    raise typer.Exit(outcome.exit_code)


def _clean_plan(git: Git, series: Series, workspace: Path) -> list[str]:
    """What ``clean`` would do to ``workspace``, one human line per item.

    Enumerated from git's stable porcelain status and ref existence, never from parsing
    ``git clean``'s prose output, so the preview means the same thing under any locale.
    """
    lines: list[str] = []
    # One status read: two reads could disagree and report a plan that never existed.
    status = git.status_porcelain()
    modified = [entry for entry in status if not entry.startswith('??')]
    untracked = [entry[3:] for entry in status if entry.startswith('??')]
    if modified:
        lines.append(f'discard {len(modified)} uncommitted change(s) to tracked files')
        lines += [f'    {entry}' for entry in modified]
    if untracked:
        lines.append(f'delete {len(untracked)} untracked path(s)')
        lines += [f'    {path}' for path in untracked]
    # Only when it is actually a change: listing an unconditional "check out base" would
    # make the plan never empty, and "already clean" unreachable.
    if git.current_branch() != series.branches.base:
        lines.append(f'check out base branch {series.branches.base!r}')
    existing = [
        branch
        for branch in (series.branches.integration, *(pr.branch for pr in series.prs))
        if git.branch_exists(branch)
    ]
    if existing:
        lines.append(f'delete {len(existing)} series branch(es)')
        lines += [f'    {branch}' for branch in existing]
    if lock_path(workspace).exists():
        lines.append(f'remove the run lock ({lock_path(workspace)})')
        orphan = orphaned_run_id(Path(series.paths.outputs) / 'spawns.jsonl')
        if orphan is not None:
            lines.append(f'record run {orphan} as abandoned in the ledger')
    return lines


@app.command()
def clean(
    series_file: Path,
    workspace: Annotated[
        Path | None, typer.Option('--workspace', '-w', help=_WORKSPACE_HELP)
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            '--dry-run',
            '-n',
            help='Print what would be done and change nothing. Do this first.',
        ),
    ] = False,
) -> None:
    """Reset a workspace to the series' base branch after a halted or killed run.

    DESTRUCTIVE AND UNRECOVERABLE. In order: discard uncommitted changes to tracked
    files, delete untracked files and directories (ignored files are kept), check out
    the base branch, delete the series' integration and PR branches, and remove a stale
    run lock. Use ``--dry-run`` first to see exactly what that means for this workspace.

    This is the recovery path, deliberately separate from ``run --fresh``: it starts no
    run, so it takes no workspace lock and pays for no seat probe — which is precisely
    why ``--fresh`` cannot serve it, since ``--fresh`` acquires the lock and probes the
    seat before it ever resets anything. Recovering by hand was otherwise the only
    option, and one campaign needed it five times.

    Removing a stale lock also **closes the killed run's ledger entry** with a terminal
    ``run_abandoned`` line, if that run recorded no outcome of its own. This is the last
    moment at which the fact is establishable — the lock names the process that owned the
    run, and a pid is reusable once it is gone — so the alternative is a ledger entry that
    reads ``running`` for ever. It is the only write ``clean`` makes outside the workspace,
    and it is append-only like every other.
    """
    series = _load_or_exit(series_file)
    target = _workspace_or_exit(workspace)
    git = Git(target)
    removed_lock = False
    abandoned: str | None = None
    try:
        plan = _clean_plan(git, series, target)
        if dry_run:
            typer.echo(f'would clean {target}:' if plan else f'{target} is already clean')
            for line in plan:
                typer.echo(f'  {line}')
            return
        git.discard_changes()
        git.clean_untracked()
        git.reset_to_base(
            series.branches.base,
            [series.branches.integration, *(pr.branch for pr in series.prs)],
        )
        removed_lock = remove_stale_lock(target)
        if removed_lock:
            # Written only when a lock was actually cleared: that is what identifies this
            # workspace as the one a killed run left behind.
            abandoned = abandon_orphaned_run(series)
    except GitError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    for line in plan:
        typer.echo(line)
    if removed_lock:
        typer.echo('removed the run lock')
    if abandoned is not None:
        typer.echo(f'recorded run {abandoned} as abandoned')
    typer.echo(f'clean: {target} is on {series.branches.base!r}')


@app.command()
def status(
    series_file: Path,
    run_id: Annotated[
        str,
        typer.Option(
            '--run-id',
            help='Which run to report. Defaults to the most recent one in the ledger.',
        ),
    ] = '',
    workspace: Annotated[
        Path | None, typer.Option('--workspace', '-w', help=_STATUS_WORKSPACE_HELP)
    ] = None,
    json_summary: Annotated[
        bool, typer.Option('--json', help='Print the envelope as one JSON object.')
    ] = False,
) -> None:
    """Report a run's state and economy so far — including a run still in progress.

    Reads the append-only ledger under ``[paths].outputs``, so it works for a run this
    process never started: the supported long-run pattern is ``convoy run`` in a background
    shell, and this is how you ask that run how it is doing. It spends nothing and writes
    nothing, so polling is cheap and safe.

    ``state`` is the field to read first — ``running`` (no terminal record yet; the economy
    is a partial running total), ``dead`` (no terminal record and the process that would
    have written one is gone), ``finished`` (the outcome fields are meaningful), or
    ``unknown`` (nothing recorded under that id yet, which is not an error). The exit code
    is ``0`` whenever the status could be read, whatever the run's own outcome was: this
    verb reports, it does not adopt the run's verdict.
    """
    series = _load_or_exit(series_file)
    envelope = status_of(series, run_id=run_id, workspace=_workspace_or_exit(workspace))
    if json_summary:
        typer.echo(json.dumps(envelope))
        return
    state = envelope['state']
    typer.echo(f'{envelope.get("run_id") or "(none)"}: {state}')
    if state == 'unknown':
        typer.echo(str(envelope['message']))
        return
    economy = envelope['economy']
    typer.echo(
        f'  spawns {economy["spawn_count"]}, turns {economy["num_turns"]}, '
        f'${economy["total_cost_usd"]:.2f}'
    )
    if state == 'dead':
        typer.echo(f'  {envelope["message"]}')
    if state == 'finished':
        typer.echo(f'  outcome {envelope["outcome"]}, integrated {envelope["integrated"]}')
        halt = envelope['halt']
        if halt:
            typer.echo(f'  halted at {halt["pr_id"]} (phase {halt["phase"]}, {halt["role"]})')
            if halt['cap_usd'] is not None:
                typer.echo(f'    spend ${halt["spend_usd"]:.2f} of ${halt["cap_usd"]:.2f}')


@app.command()
def hook() -> None:
    """Run the project gate as a Claude Code hook around subagent dispatch.

    Reads the hook event JSON from stdin. On ``SubagentStop`` (the judge) a blocking red
    is exit 2 with the repair brief on stderr, which the subagent receives as the reason
    it may not stop yet — one repair round, then it may stop; read-only subagents are
    not gated. On ``PostToolUse`` for ``Agent``/``Task`` (the messenger, synchronous
    dispatch) the judge's verdict is reused and a residual red is exit 2 with the brief
    shown to the orchestrator, its cue to dispatch a fix subagent. Nothing happens
    unless the project has a gate spec — ``$CLAUDE_PROJECT_DIR/.convoy/gate.toml``, then
    ``.convoy/gate.toml`` from the event's ``cwd`` upward — and this machine trusts the
    project (``convoy gate --init`` / ``--trust``). Green: exit 0 and no output. A gate
    that cannot run is exit 2 with a one-line reason. A ``[convoy-phase: <tag>]`` marker
    in the subagent's brief scopes the gate. Every firing appends one JSON line to
    ``.convoy/hook.log``. Exit codes are the hook protocol's (0 silent, 2 feedback),
    not convoy's.
    """
    raise typer.Exit(run_hook(sys.stdin.buffer.read(), os.environ))


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
    harden_std_streams()
    app()


if __name__ == '__main__':
    main()
