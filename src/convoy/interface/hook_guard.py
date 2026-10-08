"""The plugin hook's fast path: start ``convoy hook`` only when it could have something to say.

The plugin registers its hook on every ``SubagentStop`` and on every ``Agent``/``Task``
``PostToolUse``, in every session of everyone who installs it, while the hook does nothing
unless a project carries a ``.convoy/gate.toml`` this machine trusts. Starting the full hook
costs uv's environment check, an interpreter and the whole CLI import on every firing. This
script runs first, as ``python -I <plugin root>/src/convoy/interface/hook_guard.py``, reads
the event and decides:

- **skip** (exit 0, nothing on stdout or stderr, no process started) when the full hook would
  certainly be silent and write nothing: no gate spec can be found, or one is found in a
  project that is neither vouched for in ``CONVOY_TRUSTED_ROOTS`` nor listed in the trust
  file (or there is no trust file at all);
- **delegate** otherwise: ``uv run --project <plugin root> convoy hook`` with the same stdin
  bytes, its stdout and stderr inherited, a SIGTERM or SIGINT the guard receives passed on
  to it, its exit code returned.

The decision mirrors the full hook's discovery and trust (``gate_service.find_gate_spec``,
``gate_service.trust_status``, ``hook.decide``, ``hook.run_hook``) and errs one way only:
anything it does not fully understand — an explicit ``CONVOY_GATE_SPEC``, stdin that is not
a UTF-8 JSON object, a trust file it cannot read or whose shape is unexpected, any exception
of its own — is delegated, so the full hook gives its answer. A listed root is delegated
whatever its spec hash: a changed spec is a loud refusal only the full hook gives.
``tests/test_hook_guard.py`` holds the skip side against the full hook's own ``decide``.

Standard library only, and nothing from ``convoy``: the plugin's environment may not have
the package installed yet when this runs (``uv run --frozen --no-sync`` does not sync it).
"""

import json
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

# ``shutil``, ``signal``, ``subprocess`` and ``tomllib`` are imported where they are used: a
# firing that finds no spec needs none of them, and together they were about a third of this
# script's own start-up.
TYPE_CHECKING = False
if TYPE_CHECKING:
    import subprocess

# Mirrors of the names ``gate_service`` defines; this module cannot import them.
_GATE_SPEC = ('.convoy', 'gate.toml')
_GATE_SPEC_ENV = 'CONVOY_GATE_SPEC'
_PROJECT_DIR_ENV = 'CLAUDE_PROJECT_DIR'
_HOME_ENV = 'CONVOY_HOME'
_TRUST_FILE = 'hook-trust.toml'
_TRUSTED_ROOTS_ENV = 'CONVOY_TRUSTED_ROOTS'

# The hook protocol's loud answer: stderr is feedback. Used when the full hook is needed and
# cannot be started, the same answer as a gate that cannot run.
_EXIT_FEEDBACK = 2

# The signals that end a hook early, passed on to the delegate while it runs. SIGTERM and
# SIGINT carry these numbers on every platform; ``signal`` is not imported to name them.
_FORWARDED_SIGNALS = (15, 2)

# ``<root>/src/convoy/interface/hook_guard.py``: the plugin root is four levels up. Derived
# from this file, not from the environment, so the delegate runs the plugin this guard
# belongs to.
PLUGIN_ROOT = Path(__file__).resolve().parents[3]


def _spec_candidates(
    payload: Mapping[str, object], env: Mapping[str, str], cwd: Path
) -> Iterator[Path]:
    """Where the full hook looks for a gate spec, in its order.

    ``$CLAUDE_PROJECT_DIR`` first, then the payload's ``cwd`` (``.`` when absent or empty)
    and each of its parents. Relative paths resolve against *cwd*, the process directory.
    """
    project_dir = env.get(_PROJECT_DIR_ENV)
    if project_dir:
        yield cwd.joinpath(project_dir, *_GATE_SPEC)
    raw_cwd = payload.get('cwd')
    start = (cwd / (raw_cwd if isinstance(raw_cwd, str) and raw_cwd else '.')).resolve()
    for directory in (start, *start.parents):
        yield directory.joinpath(*_GATE_SPEC)


def _listed_roots(env: Mapping[str, str], cwd: Path) -> list[Path] | None:
    """The roots on the trust list, ``[]`` when there is no list, ``None`` when it is not sound.

    Sound means what ``gate_service.trusted_projects`` accepts: a ``projects`` list of tables,
    each with a non-empty absolute string ``root`` and, if present, a string
    ``spec_sha256``. The full hook reads anything else as trusting nothing; the guard leaves
    that reading to it.
    """
    home = env.get(_HOME_ENV)
    base = cwd / home if home else Path.home() / '.convoy'
    path = base / _TRUST_FILE
    if not path.is_file():
        return []
    import tomllib

    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except OSError, UnicodeDecodeError, tomllib.TOMLDecodeError:
        return None
    projects = data.get('projects')
    if not isinstance(projects, list):
        return None
    roots: list[Path] = []
    for item in projects:
        if not isinstance(item, dict):
            return None
        root = item.get('root')
        digest = item.get('spec_sha256', '')
        if not isinstance(root, str) or not root or not isinstance(digest, str):
            return None
        if not Path(root).is_absolute():
            return None
        roots.append(Path(root).resolve())
    return roots


def should_delegate(raw: bytes, env: Mapping[str, str], cwd: Path) -> bool:
    """Whether the full hook could say or write anything for this event."""
    if env.get(_GATE_SPEC_ENV):
        return True
    try:
        payload = json.loads(raw.decode('utf-8'))
    except UnicodeDecodeError, ValueError:
        return True
    if not isinstance(payload, dict):
        return True
    spec = next((path for path in _spec_candidates(payload, env, cwd) if path.is_file()), None)
    if spec is None:
        return False
    root = spec.parent.parent.resolve()
    vouched = env.get(_TRUSTED_ROOTS_ENV, '')
    if any((cwd / item).resolve() == root for item in vouched.split(os.pathsep) if item):
        return True
    listed = _listed_roots(env, cwd)
    if listed is None:
        return True
    return root in listed


def main(raw: bytes, env: Mapping[str, str], cwd: Path, delegate: Callable[[bytes], int]) -> int:
    """Decide, then skip (exit 0) or hand the same bytes to *delegate* and return its code.

    An exception in the decision delegates: a guard that failed must not read as a skip.
    """
    try:
        needed = should_delegate(raw, env, cwd)
    except Exception:
        needed = True
    return delegate(raw) if needed else 0


def find_uv(env: Mapping[str, str]) -> str | None:
    """uv: ``$UV`` when it names a file (uv sets it for what ``uv run`` starts), else PATH."""
    named = env.get('UV')
    if named and Path(named).is_file():
        return named
    import shutil

    return shutil.which('uv')


def delegate_argv(uv: str) -> list[str]:
    """The full hook, from this plugin's own project."""
    return [uv, 'run', '--project', str(PLUGIN_ROOT), 'convoy', 'hook']


def wait_forwarding_signals(child: subprocess.Popen[bytes], raw: bytes) -> int:
    """Hand *raw* to *child* on its stdin, wait for it, and pass SIGTERM and SIGINT on to it.

    The guard is one more process between Claude Code and ``convoy hook``. A hook that runs
    past its timeout is ended by a signal to the process Claude Code started; ``uv run``
    passes it to its child, this guard, and the guard passes it to its own. Without that the
    guard would die and leave ``convoy hook`` running, holding the judge lock, after the
    firing ended. The previous handlers are restored once the child has exited.
    """
    import signal

    def forward(signum: int, _frame: object) -> None:
        child.send_signal(signum)

    previous = [(signum, signal.signal(signum, forward)) for signum in _FORWARDED_SIGNALS]
    try:
        child.communicate(raw)
    finally:
        for signum, handler in previous:
            signal.signal(signum, handler)
    return child.returncode


def run_delegate(raw: bytes, env: Mapping[str, str]) -> int:
    """Run ``convoy hook`` with *raw* on a dedicated stdin pipe; its streams are inherited."""
    uv = find_uv(env)
    if uv is None:
        sys.stderr.write('convoy hook: a gate may apply here but uv was not found to run it\n')
        return _EXIT_FEEDBACK
    import subprocess

    try:
        child = subprocess.Popen(delegate_argv(uv), stdin=subprocess.PIPE)
    except OSError as exc:
        sys.stderr.write(f'convoy hook: could not start the hook through uv: {exc}\n')
        return _EXIT_FEEDBACK
    return wait_forwarding_signals(child, raw)


def _entry() -> int:
    raw = sys.stdin.buffer.read()
    env = dict(os.environ)
    try:
        cwd = Path.cwd()
    except OSError:
        # No working directory to resolve against: the full hook gives its own answer.
        return run_delegate(raw, env)
    return main(raw, env, cwd, lambda data: run_delegate(data, env))


if __name__ == '__main__':
    sys.exit(_entry())
