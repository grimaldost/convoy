"""The gate-only service: run a spec's checks against a workspace, once, no run loop.

This is the fold both gate-only surfaces consume — the CLI's ``convoy gate`` and the MCP
``convoy_gate`` tool — so the two can never disagree about a verdict, an envelope, or an
exit code. It reuses the run's own machinery end to end: selection is
:func:`convoy.core.gate.checks_for_phases`, execution is
:class:`~convoy.interface.gate_runner.SubprocessGateRunner`, and the verdict is
:func:`convoy.core.gate.decide`. Nothing here spawns an agent, moves a branch, writes
telemetry, or takes the workspace lock. Convoy itself writes nothing to the workspace —
but the CHECK COMMANDS run in it and routinely do (``__pycache__``, coverage files,
build output), so gating a tree a ``convoy run`` is actively driving risks more than a
stale read: the run's commit step stages the whole tree, and a concurrent gate's
artifacts can be committed into a scored branch. Don't gate a driven workspace.

Four invocations are refused before anything executes, all mapped to a ``usage``
outcome rather than a verdict (:class:`~convoy.core.gate.GateUsageError` and its
subclasses carry the reasons): an empty selection, a phase tag no check declares, a
selection with no blocking check, and a blocking independent check whose isolation
cannot be backed. The common thread: a gate-only caller asked a question, and each of
these is an invocation that cannot produce a meaningful answer — the run path handles
the same conditions with pre-flight problems and author-declared advisories, which a
standalone invocation does not have.
"""

import hashlib
import os
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import tomli_w

from convoy import __version__
from convoy.core.gate import (
    AdvisoryOnlySelectionError,
    EmptySelectionError,
    GateVerdict,
    IsolationRefusedError,
    UnknownPhaseError,
    checks_for_phases,
    decide,
    repair_brief,
)
from convoy.core.spec import Check, GateSpec, SpecError, load_gate_spec
from convoy.interface.drivers.headless import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE
from convoy.interface.fs_probe import isolation_result
from convoy.interface.gate_runner import GateRunner, SubprocessGateRunner

# Cap the per-check list projected inline, the same bound and report shape as the run
# envelope's per-PR list (`run_summary._PR_CAP`). Unlike a run there is no on-disk
# trace to point at — the envelope IS the record — so what is dropped is counted,
# never silent.
_CHECK_CAP = 50

# The per-project gate spec: the gate-only file shape, at a fixed place under the project
# root, so ``convoy gate`` and ``convoy hook`` need no argument to find it — and its
# presence is the per-project switch that arms the hook.
GATE_SPEC_RELPATH = Path('.convoy') / 'gate.toml'
# Claude Code exports the project root to hooks and MCP servers under this name.
PROJECT_DIR_ENV = 'CLAUDE_PROJECT_DIR'
# An explicit spec path from the launching process — a harness or CI job that keeps the
# gate outside the tree it stages. Wins over discovery; a missing file is refused.
GATE_SPEC_ENV = 'CONVOY_GATE_SPEC'
# The out-of-tree home for a project's held-out oracles (see ``core.spec.expand_env``).
ORACLES_ENV = 'CONVOY_ORACLES'
# Convoy's per-user directory: the default oracles home and the hook trust list live
# here. ``~/.convoy`` unless overridden (tests, CI, a shared machine).
HOME_ENV = 'CONVOY_HOME'
# The projects whose ``.convoy/gate.toml`` the hook may execute on this machine.
TRUST_FILE = 'hook-trust.toml'
# Roots the process that launched Claude Code vouches for (``os.pathsep``-separated) —
# a harness or CI job staging a fresh workspace per run has no trust list to edit.
TRUSTED_ROOTS_ENV = 'CONVOY_TRUSTED_ROOTS'


# The timeout ``hooks/hooks.json`` declares for both hook events, in seconds. Claude Code kills a
# hook that outlasts it without a word, and a gate runs its checks one after another, each
# bounded by the spec's ``timeout_seconds`` — so ``len(checks) * timeout_seconds`` must stay
# under this. The JSON file sits outside the package, so the number lives here and
# ``tests/test_manifest.py`` pins the two together.
HOOK_TIMEOUT_SECONDS = 1800

# Held back from the hook timeout for the hook's own start-up and its log append, which are
# not part of the gate's worst case. On an armed firing the start-up runs uv twice: once for
# the plugin's guard (``hook_guard.py``), once more for ``convoy hook`` it delegates to.
HOOK_MARGIN_SECONDS = 30

# How much of the hook timeout a gate's worst case (checks x ``timeout_seconds``) may take:
# five checks at the default 300 s, what ``convoy gate --init`` scaffolds for a Python
# project. The rest holds the margin and :data:`JUDGE_MIN_WAIT_SECONDS`, the least a firing
# that finds another firing's gate running in the same tree waits for it (``convoy hook``
# runs one gate per tree at a time). One threshold for three places: the scaffold fits its
# checks inside it, ``convoy validate`` warns past it, and the hook plans its wait from it.
GATE_BUDGET_SECONDS = 1500
JUDGE_MIN_WAIT_SECONDS = HOOK_TIMEOUT_SECONDS - HOOK_MARGIN_SECONDS - GATE_BUDGET_SECONDS


class GateSpecNotFoundError(SpecError):
    """No series file was given and no project gate spec could be found."""


def find_gate_spec(start: Path, env: Mapping[str, str]) -> Path | None:
    """Locate the project gate spec, or ``None``.

    ``$CONVOY_GATE_SPEC`` first when set — an explicit file the launching process names,
    refused (:class:`GateSpecNotFoundError`) when it does not exist, because a caller
    that set it and got a walk-up result instead would never learn its file is missing.
    Then ``.convoy/gate.toml`` in *start* and each of its parents, nearest first, so a
    gate invoked from a subdirectory finds the project's spec the way git finds ``.git``,
    and a subagent working in a worktree of the project (Claude Code puts an isolated
    agent's under ``<project>/.claude/worktrees/<id>``) finds the worktree's own spec, not
    the main checkout's. Only when the walk finds none,
    ``$CLAUDE_PROJECT_DIR/.convoy/gate.toml`` — the root Claude Code hands a hook or an
    MCP server, which may lie outside *start*'s ancestry.
    """
    explicit = env.get(GATE_SPEC_ENV)
    if explicit:
        named = Path(explicit)
        if not named.is_file():
            raise GateSpecNotFoundError(f'${GATE_SPEC_ENV}={explicit} is not an existing file')
        return named
    resolved = Path(start).resolve()
    candidates = [directory / GATE_SPEC_RELPATH for directory in (resolved, *resolved.parents)]
    project_dir = env.get(PROJECT_DIR_ENV)
    if project_dir:
        candidates.append(Path(project_dir) / GATE_SPEC_RELPATH)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def resolve_gate_spec(series_file: Path | None, start: Path, env: Mapping[str, str]) -> Path:
    """An explicit *series_file* as given; otherwise the discovered project spec.

    Raises :class:`GateSpecNotFoundError` (a ``SpecError``, so both surfaces classify it
    as ``spec``) naming everywhere it looked, when there is nothing to run.
    """
    if series_file is not None:
        return series_file
    found = find_gate_spec(start, env)
    if found is None:
        project_dir = env.get(PROJECT_DIR_ENV) or 'unset'
        raise GateSpecNotFoundError(
            f'no series file given and no {GATE_SPEC_RELPATH.as_posix()} found — searched '
            f'{Path(start).resolve()} and its parents, then ${PROJECT_DIR_ENV} '
            f'({project_dir}); pass a series file, or create the project spec'
        )
    return found


def project_root_of(spec_path: Path) -> Path | None:
    """The project a ``.convoy/gate.toml`` belongs to; ``None`` for any other file."""
    if spec_path.parent.name == GATE_SPEC_RELPATH.parent.name:
        return spec_path.parent.parent
    return None


def gate_root(spec_path: Path, workspace: Path) -> Path:
    """The project a gate spec governs: its ``.convoy`` parent's parent, else the workspace.

    A spec named by ``$CONVOY_GATE_SPEC`` or passed explicitly may live anywhere — a task
    directory, a CI checkout — so the tree it judges, not the directory it sits in, is
    what the trust list is checked against and where the hook log goes.
    """
    return project_root_of(spec_path) or Path(workspace).resolve()


def same_path(a: str, b: str, *, windows: bool = os.name == 'nt') -> bool:
    """Whether two path strings name one path, read the way this platform reads paths.

    Git on Windows may write a lower-case drive letter and backslashes in the pointers it
    leaves (``c:\\work\\proj\\.git``) where Python spells ``C:/work/proj/.git``; on
    Windows the two are one path, on POSIX a difference in case is a different path.
    """
    flavour = PureWindowsPath if windows else PurePosixPath
    return flavour(a) == flavour(b)


@dataclass(frozen=True)
class GitLayout:
    """Where a working tree's repository lives: its shared git dir, and whether it is linked."""

    common: Path
    linked: bool


def git_layout(root: Path) -> GitLayout | None:
    """Read *root*'s ``.git`` the way git wrote it; ``None`` when *root* holds none git reads.

    Read from files rather than by running git: the hook's guard mirrors this with the
    standard library alone, and a firing should not start a process to learn it. A
    ``.git`` directory is a main checkout. A ``.git`` file names a git dir: with a
    ``commondir`` in it, *root* is a linked worktree whose repository is that shared dir,
    and the git dir must name *root*'s ``.git`` back (its ``gitdir`` file) or the pointer
    is not believed; without one, it is a ``--separate-git-dir`` main checkout or a
    submodule, whose repository is the git dir itself. A pointer that cannot be read, or
    one carrying a byte no path can hold, is no layout.
    """
    dot_git = Path(root) / '.git'
    try:
        if dot_git.is_dir():
            return GitLayout(dot_git.resolve(), linked=False)
        if not dot_git.is_file():
            return None
        pointer = dot_git.read_text(encoding='utf-8').strip()
        if not pointer.startswith('gitdir:'):
            return None
        own = (Path(root) / pointer.removeprefix('gitdir:').strip()).resolve()
        commondir = own / 'commondir'
        if not commondir.is_file():
            return GitLayout(own, linked=False) if own.is_dir() else None
        common = (own / commondir.read_text(encoding='utf-8').strip()).resolve()
        back = (own / (own / 'gitdir').read_text(encoding='utf-8').strip()).resolve()
        if not same_path(str(back), str(dot_git.resolve())):
            return None
    except OSError, UnicodeDecodeError, ValueError:
        return None
    return GitLayout(common, linked=True)


def main_checkout_of(root: Path) -> Path | None:
    """The main checkout of the linked git worktree at *root*; ``None`` for anything else.

    The shared git dir's parent, when that dir is a checkout's ``.git``. A bare
    repository's worktrees and a ``--separate-git-dir`` repository's have none that can be
    read from the worktree; a submodule or a main checkout is no linked worktree.
    """
    layout = git_layout(root)
    if layout is None or not layout.linked or layout.common.name != '.git':
        return None
    return layout.common.parent


def convoy_home(env: Mapping[str, str]) -> Path:
    """Convoy's per-user directory: ``$CONVOY_HOME``, else ``~/.convoy``."""
    explicit = env.get(HOME_ENV)
    return Path(explicit) if explicit else Path.home() / '.convoy'


def oracles_dir_for(root: Path, env: Mapping[str, str]) -> Path:
    """Where a project's held-out oracles live: ``CONVOY_ORACLES`` when set, else the default.

    The default is ``<convoy home>/oracles/<project dir name>`` — outside every checkout the
    implementer can reach, keyed by the project directory's name so two clones of one
    project share their oracles.
    """
    explicit = env.get(ORACLES_ENV)
    if explicit:
        return Path(explicit)
    # The directory name becomes part of a shell command through ``${CONVOY_ORACLES}``;
    # anything a shell could read as syntax is replaced, never passed through.
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', Path(root).resolve().name) or 'project'
    return convoy_home(env) / 'oracles' / safe


@dataclass(frozen=True)
class TrustEntry:
    """One trusted project: its root and the hash of the gate spec the operator read."""

    root: Path
    spec_sha256: str = ''


def spec_text_digest(spec_path: Path) -> str:
    """sha256 of the spec's bytes with CRLF and CR line endings read as LF; ``''`` when unreadable.

    What a worktree's spec is compared with its anchor's by: git's line-ending conversion
    (``core.autocrlf``, ``.gitattributes`` ``eol``) can check one spec out with other line
    endings than the anchor's file has, and that is no difference in what the gate runs.
    """
    try:
        data = Path(spec_path).read_bytes()
    except OSError:
        return ''
    return hashlib.sha256(data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')).hexdigest()


def spec_digest(spec_path: Path) -> str:
    """sha256 of the spec file's bytes, ``''`` when it cannot be read."""
    try:
        return hashlib.sha256(Path(spec_path).read_bytes()).hexdigest()
    except OSError:
        return ''


def trusted_projects(env: Mapping[str, str]) -> tuple[TrustEntry, ...]:
    """The trust list — ``[[projects]]`` tables of ``root`` and ``spec_sha256``; ``()`` when absent.

    A malformed trust list is a ``SpecError`` — the hook treats it as trusting nothing,
    and ``convoy gate --trust`` refuses to append to a file it cannot read. A relative
    ``root`` is malformed too: it would trust whatever directory the hook happens to run
    in.
    """
    path = convoy_home(env) / TRUST_FILE
    if not path.is_file():
        return ()
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f'{path}: invalid TOML: {exc}') from exc
    projects = data.get('projects')
    if not isinstance(projects, list):
        raise SpecError(f'{path}: [[projects]] tables expected')
    entries: list[TrustEntry] = []
    for index, item in enumerate(projects):
        root = item.get('root') if isinstance(item, dict) else None
        digest = item.get('spec_sha256', '') if isinstance(item, dict) else None
        if not isinstance(root, str) or not root or not isinstance(digest, str):
            raise SpecError(f'{path}: [[projects]][{index}] needs a string root (and spec_sha256)')
        if not Path(root).is_absolute():
            raise SpecError(f'{path}: [[projects]][{index}] root must be absolute, got {root!r}')
        entries.append(TrustEntry(root=Path(root), spec_sha256=digest))
    return tuple(entries)


@dataclass(frozen=True)
class TrustDecision:
    """Whether the hook may run a spec, and the tree a worktree's trust came from.

    *status* is ``trusted``, ``untrusted``, ``changed`` (the root's own pinned spec is not
    the one that was trusted) or ``differs`` (a worktree's spec is not its anchor's).
    *anchor* is the tree a linked worktree inherits from — set for ``differs``, for an
    inherited ``trusted``, and for an ``untrusted`` worktree whose anchor could not vouch.
    """

    status: str
    anchor: Path | None = None


def _vouched(resolved: Path, env: Mapping[str, str]) -> bool:
    vouched = env.get(TRUSTED_ROOTS_ENV, '')
    return any(Path(item).resolve() == resolved for item in vouched.split(os.pathsep) if item)


def _listed(resolved: Path, env: Mapping[str, str]) -> TrustEntry | None:
    return next((e for e in trusted_projects(env) if e.root.resolve() == resolved), None)


def trust_anchor(root: Path, env: Mapping[str, str]) -> Path | None:
    """The tree the linked git worktree at *root* takes its trust from; ``None`` when there is none.

    ``$CLAUDE_PROJECT_DIR`` first, when *root* lies inside it or belongs to the same
    repository (it was made from it: an agent's worktree under a session that is itself a
    worktree) and this machine trusts it (listed or vouched for); otherwise git's main
    checkout. A *root* that is not a linked worktree has no anchor: it is its own tree.
    """
    layout = git_layout(root)
    if layout is None or not layout.linked:
        return None
    resolved = Path(root).resolve()
    project_dir = env.get(PROJECT_DIR_ENV)
    if project_dir:
        project = Path(project_dir).resolve()
        project_layout = git_layout(project)
        related = resolved.is_relative_to(project) or (
            project_layout is not None and same_path(str(project_layout.common), str(layout.common))
        )
        if (
            project != resolved
            and related
            and (_vouched(project, env) or _listed(project, env) is not None)
        ):
            return project
    return main_checkout_of(root)


def trust_decision(root: Path, spec_path: Path | None, env: Mapping[str, str]) -> TrustDecision:
    """Whether the hook may run *spec_path* in *root*, with the anchor a worktree's trust came from.

    ``CONVOY_TRUSTED_ROOTS`` in *env* names roots the process that launched Claude Code
    vouches for — a harness or a CI job that stages a workspace it created and cannot
    have listed in advance; those carry no spec pin, because the spec lives with the
    harness, outside the tree. A root on the trust list is ``trusted`` while the spec's
    hash matches the one recorded when the operator trusted it, and ``changed`` when it
    does not: the implementer edits the tree the spec lives in, and a gate it can
    rewrite is no gate. The claim is only as strong as the environment the hook runs in;
    a project's own settings can set these variables, which is Claude Code's trust model
    to enforce, not this function's.

    A linked git worktree that is not itself listed or vouched for inherits from its
    :func:`trust_anchor`, for a pinned spec only: the anchor's own spec must still be the
    one its entry pins, and the worktree's spec must match it once line endings are read
    alike (:func:`spec_text_digest`) — ``trusted`` when it does, ``differs`` when it does
    not, so a worktree cannot arm a different gate by itself. An anchor that cannot vouch
    (an unpinned entry, a vouched-for root, a spec missing or changed) leaves the
    worktree ``untrusted``, with the anchor named so the caller can judge the anchor's
    own tree instead (:func:`fallback_gate`).
    """
    resolved = Path(root).resolve()
    if _vouched(resolved, env):
        return TrustDecision('trusted')
    entry = _listed(resolved, env)
    if entry is not None:
        if (
            entry.spec_sha256
            and spec_path is not None
            and spec_digest(spec_path) != entry.spec_sha256
        ):
            return TrustDecision('changed')
        return TrustDecision('trusted')
    anchor = trust_anchor(resolved, env)
    if anchor is None or spec_path is None:
        return TrustDecision('untrusted')
    anchor_entry = _listed(anchor, env)
    anchor_spec = anchor / GATE_SPEC_RELPATH
    if (
        anchor_entry is None
        or not anchor_entry.spec_sha256
        or not anchor_spec.is_file()
        or spec_digest(anchor_spec) != anchor_entry.spec_sha256
    ):
        return TrustDecision('untrusted', anchor)
    if spec_text_digest(spec_path) == spec_text_digest(anchor_spec):
        return TrustDecision('trusted', anchor)
    return TrustDecision('differs', anchor)


def trust_status(root: Path, spec_path: Path | None, env: Mapping[str, str]) -> str:
    """:func:`trust_decision`'s status, with ``differs`` read as ``changed``."""
    status = trust_decision(root, spec_path, env).status
    return 'changed' if status == 'differs' else status


def fallback_gate(
    spec_path: Path, workspace: Path, anchor: Path | None, env: Mapping[str, str]
) -> tuple[Path, Path, TrustDecision] | None:
    """The spec to judge by instead of an untrusted nearest one, so no gated tree goes ungated.

    Before CONV-B75 the hook tried ``$CLAUDE_PROJECT_DIR``'s spec first and judged that
    tree. When the nearest spec is untrusted, the anchor's spec and then that one are
    tried, and the first whose tree the machine trusts (or refuses loudly) is returned
    with its root and decision: the agent is judged in that tree, which the caller says.
    ``None`` when neither gives anything but silence.
    """
    candidates: list[Path] = []
    if anchor is not None:
        candidates.append(anchor / GATE_SPEC_RELPATH)
    project_dir = env.get(PROJECT_DIR_ENV)
    if project_dir:
        candidates.append(Path(project_dir).resolve() / GATE_SPEC_RELPATH)
    nearest = Path(spec_path).resolve()
    for candidate in candidates:
        if not candidate.is_file() or candidate.resolve() == nearest:
            continue
        root = gate_root(candidate, workspace)
        decision = trust_decision(root, candidate, env)
        if decision.status != 'untrusted':
            return candidate, root.resolve(), decision
    return None


def oracles_root_for(root: Path, env: Mapping[str, str]) -> Path:
    """The tree whose name keys a judged tree's default oracles dir.

    A linked worktree's oracles are its anchor's (:func:`trust_anchor`, else git's main
    checkout), never its own directory's name: ``<project>/.claude/worktrees/<id>`` would
    key on ``<id>``, where no oracle was ever written. Any other tree keys on itself. A
    trust list that cannot be read leaves the session project out of the choice.
    """
    try:
        anchor = trust_anchor(root, env)
    except SpecError:
        anchor = main_checkout_of(root)
    return anchor or Path(root).resolve()


def is_trusted(root: Path, env: Mapping[str, str], spec_path: Path | None = None) -> bool:
    """Whether the hook would execute *root*'s spec: :func:`trust_status` is ``trusted``."""
    return trust_status(root, spec_path, env) == 'trusted'


def trust_project(root: Path, env: Mapping[str, str], spec_path: Path | None = None) -> Path:
    """Record *root* (and the hash of its spec) on the trust list; return the list's path.

    With no *spec_path*, the project's own ``.convoy/gate.toml`` is pinned when it exists.
    Re-trusting a root replaces its entry, which is how an operator accepts a changed spec.
    """
    path = convoy_home(env) / TRUST_FILE
    resolved = Path(root).resolve()
    pinned = spec_path if spec_path is not None else resolved / GATE_SPEC_RELPATH
    digest = spec_digest(pinned) if Path(pinned).is_file() else ''
    entries = [e for e in trusted_projects(env) if e.root.resolve() != resolved]
    entries.append(TrustEntry(root=resolved, spec_sha256=digest))
    path.parent.mkdir(parents=True, exist_ok=True)
    listed = [{'root': e.root.as_posix(), 'spec_sha256': e.spec_sha256} for e in entries]
    path.write_text(tomli_w.dumps({'projects': listed}), encoding='utf-8')
    return path


def gate_spec_env(
    spec_path: Path, env: Mapping[str, str], *, root: Path | None = None
) -> dict[str, str]:
    """The environment a spec at *spec_path* is loaded with.

    A project spec (one living at ``.convoy/gate.toml``, or one whose governed *root* the
    caller names — the ``$CONVOY_GATE_SPEC`` case) gets ``CONVOY_ORACLES`` defaulted
    through :func:`oracles_dir_for` when the caller has not set it, so the scaffolded
    ``${CONVOY_ORACLES}/...`` references resolve on a machine that never exported the
    variable. An explicit series file with no named root gets no default: its author
    wrote its paths, and an unset reference is refused at load, as documented.
    """
    resolved = dict(env)
    governed = project_root_of(spec_path) if root is None else root
    if governed is not None and ORACLES_ENV not in resolved:
        resolved[ORACLES_ENV] = str(oracles_dir_for(governed, env))
    return resolved


def load_gate_spec_file(
    spec_path: Path, env: Mapping[str, str], *, root: Path | None = None
) -> GateSpec:
    """Read and parse *spec_path* under :func:`gate_spec_env`; the loader's errors pass through."""
    text = spec_path.read_text(encoding='utf-8')
    return load_gate_spec(text, env=gate_spec_env(spec_path, env, root=root))


def advisory_only_detail(selected: Sequence[Check]) -> str:
    """Why a selection carrying no blocking check is refused.

    Its own function because two surfaces reach the same conclusion from the spec alone:
    :func:`run_gate` raises it, and ``convoy validate`` reports it on a gate-only file
    before any check runs. One spelling keeps the two from drifting into different words
    for the same defect.
    """
    return (
        f'the selection ({len(selected)} check(s)) contains no blocking check — '
        f'nothing in it can fail the gate, so "completed" would assure nothing; '
        f'mark a check blocking, or widen the selection'
    )


@dataclass(frozen=True)
class GateOutcome:
    verdict: GateVerdict
    selected: tuple[Check, ...]
    phases: tuple[str, ...]
    exit_code: int


def run_gate(
    spec: GateSpec,
    workspace: Path,
    phases: tuple[str, ...] = (),
    *,
    runner: GateRunner | None = None,
) -> GateOutcome:
    """Select ``spec``'s checks for ``phases``, run them in ``workspace``, judge once.

    No tags runs the whole gate; tags select what a PR carrying them would be gated on.
    The exit code is the run's own vocabulary: ``EXIT_OK`` unless a blocking check
    failed, ``EXIT_BLOCKED`` when one did — a non-blocking red advises, exactly as in a
    series.

    Refusals, all :class:`~convoy.core.gate.GateUsageError` subclasses raised before any
    check command runs:

    - a tag no check declares (:class:`~convoy.core.gate.UnknownPhaseError`) — the
      run-side pre-flight makes the same typo a blocking problem, because a check that
      never runs is worse than a missing one: the result still looks gated;
    - a selection with no blocking check
      (:class:`~convoy.core.gate.AdvisoryOnlySelectionError`) — nothing selected can
      say no, so ``completed`` would be vacuous;
    - an empty selection (:class:`~convoy.core.gate.EmptySelectionError`) — unreachable
      through the two guards above for any loader-produced spec, kept as the
      fail-closed backstop for a directly constructed one;
    - a blocking independent check whose isolation is not backed
      (:class:`~convoy.core.gate.IsolationRefusedError`) — the run reports this
      identical defect as a pre-flight problem; classifying it as a red would point a
      repair loop keyed on ``independent_red`` at a spec misconfiguration it cannot
      fix.
    """
    declared = {phase for check in spec.checks for phase in check.phases}
    unknown = [phase for phase in phases if phase not in declared]
    if unknown:
        named = ', '.join(repr(phase) for phase in unknown)
        raise UnknownPhaseError(
            f'phase tag(s) {named} appear on no check (declared: '
            f'{", ".join(sorted(declared)) or "none"}) — the gate you named cannot run, '
            f'and a green from the remaining checks would look gated while it never was'
        )
    selected = checks_for_phases(spec.checks, phases)
    if not selected:
        raise EmptySelectionError(
            f'the selection is empty ({len(spec.checks)} check(s) in the spec) — a green '
            f'verdict from zero checks would be vacuous, so it is refused'
        )
    if not any(check.blocking for check in selected):
        raise AdvisoryOnlySelectionError(advisory_only_detail(selected))
    for check in selected:
        refused = isolation_result(workspace, check)
        if refused is not None:
            raise IsolationRefusedError(
                f'check {check.name!r}: {refused.detail} — a gate-spec defect, not a '
                f"red; fix the check's asset, or drop independent"
            )
    gate_runner = runner if runner is not None else SubprocessGateRunner(spec.timeout_seconds)
    verdict = decide(gate_runner.run(workspace, selected))
    exit_code = EXIT_BLOCKED if verdict.blocking_red else EXIT_OK
    return GateOutcome(verdict=verdict, selected=selected, phases=phases, exit_code=exit_code)


def gate_envelope(spec: GateSpec, workspace: Path, outcome: GateOutcome) -> dict[str, Any]:
    """The one result envelope both surfaces emit for a gate-only invocation.

    ``outcome`` keeps the run's vocabulary — ``completed`` for a green gate, ``blocked``
    for a blocking red — so a consumer already reading run envelopes learns no new
    words. Every selected check appears (capped at ``_CHECK_CAP`` with the run
    envelope's ``truncated`` report shape) with its verdict, the structured failure
    facts (``exit_code``, ``timed_out``) and the prose ``detail`` a repair can be
    briefed with. ``workspace`` is resolved so the envelope means the same thing
    outside the invoking shell. ``advisories`` is always present and currently always
    empty — the same read-unconditionally guarantee every other convoy envelope gives,
    reserved so a future non-fatal remark is an addition, not a shape change.

    Two fields serve a caller that orchestrates its own repairs. ``repair_brief`` is the
    ready-to-append failing-checks section — :func:`convoy.core.gate.repair_brief`, the
    same text the run's own fix loop briefs a fix spawn with, and ``''`` on a green gate
    — so an external orchestrator appends it to its implementer's brief instead of
    reassembling one from the per-check fields. ``convoy_version`` names the engine that
    produced the envelope, so a stored verdict stays interpretable when the shape later
    grows.

    ``repair_brief`` is deliberately uncapped, unlike the neighbouring ``checks`` list:
    the list is a record, and a record can report what it dropped, while the brief is an
    instruction to repair every blocking red. A brief missing some of them would send a
    fix at part of the problem while reading as the whole of it. A gate wide enough for
    the size to matter has a spec problem the cap would only hide.
    """
    results = outcome.verdict.results
    passed = sum(1 for result in results if result.passed)
    listed = results[:_CHECK_CAP]
    return {
        'ok': outcome.exit_code == EXIT_OK,
        'outcome': 'blocked' if outcome.verdict.blocking_red else 'completed',
        'series_id': spec.id,
        'workspace': str(Path(workspace).resolve()),
        'phases': list(outcome.phases),
        'checks': [
            {
                'name': result.check.name,
                'passed': result.passed,
                'blocking': result.check.blocking,
                'independent': result.check.independent,
                'phases': list(result.check.phases),
                'exit_code': result.exit_code,
                'timed_out': result.timed_out,
                'detail': result.detail,
            }
            for result in listed
        ],
        'blocking_red': outcome.verdict.blocking_red,
        'independent_red': outcome.verdict.independent_red,
        'repair_brief': repair_brief(outcome.verdict),
        'counts': {
            'total': len(spec.checks),
            'selected': len(results),
            'passed': passed,
            'failed': len(results) - passed,
        },
        'advisories': [],
        'truncated': {
            'any': len(results) > _CHECK_CAP,
            'checks': max(0, len(results) - _CHECK_CAP),
        },
        'exit_code': outcome.exit_code,
        'convoy_version': __version__,
    }


def gate_brief_envelope(outcome: GateOutcome) -> dict[str, Any]:
    """The compact envelope: ``ok``, ``outcome``, ``repair_brief``, ``convoy_version``.

    For a caller that must read the verdict inside a model turn and wants nothing else
    in it — the four fields a repair decision needs, and no per-check list to skim past.
    Agrees with :func:`gate_envelope` field for field; the full envelope remains the
    record.
    """
    return {
        'ok': outcome.exit_code == EXIT_OK,
        'outcome': 'blocked' if outcome.verdict.blocking_red else 'completed',
        'repair_brief': repair_brief(outcome.verdict),
        'convoy_version': __version__,
    }


def gate_usage_envelope(
    error: Exception,
    *,
    error_kind: str,
    series_id: str | None = None,
) -> dict[str, Any]:
    """The could-not-answer envelope, shared by both surfaces (CLI ``--json`` and MCP).

    Mirrors the run surfaces' usage results and carries the two fields a consumer
    branches on unconditionally: ``exit_code`` (the documented ``3``, which would
    otherwise appear in prose only) and ``series_id`` when the spec loaded far enough
    to have one.
    """
    envelope: dict[str, Any] = {
        'ok': False,
        'outcome': 'usage',
        'error_kind': error_kind,
        'error': str(error),
        'exit_code': EXIT_USAGE,
    }
    if series_id is not None:
        envelope['series_id'] = series_id
    return envelope
