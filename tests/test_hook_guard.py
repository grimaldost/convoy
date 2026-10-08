"""Tests for the hook guard (interface/hook_guard.py): the plugin hook's no-gate fast path.

The guard runs before ``convoy hook`` on every firing and decides, from the standard library
alone, whether the full hook could have anything to say. It skips only when the full hook
would certainly be silent and write nothing; every other case — including every case it
does not understand — is delegated. The parity table below holds that claim against the
full hook's own :func:`convoy.interface.hook.decide`, not against a restatement of it.
"""

import ast
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import convoy.interface.hook_guard as hook_guard
from convoy.interface.gate_service import trust_project
from convoy.interface.hook import decide, parse_event

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GUARD = _REPO_ROOT / 'src' / 'convoy' / 'interface' / 'hook_guard.py'
_FIXTURES = Path(__file__).parent / 'fixtures' / 'hooks'

_OK = f'"{sys.executable}" -c "exit(0)"'
_SIDE_EFFECT = f'"{sys.executable}" -c "open(\'side-effect.txt\', \'w\').close()"'


class _Recorder:
    """A delegate that records what it was handed and answers with a fixed exit code."""

    def __init__(self, exit_code: int = 0) -> None:
        self.calls: list[bytes] = []
        self.exit_code = exit_code

    def __call__(self, raw: bytes) -> int:
        self.calls.append(raw)
        return self.exit_code


def _spec(root: Path, run: str = _OK) -> Path:
    (root / '.convoy').mkdir(parents=True, exist_ok=True)
    spec = root / '.convoy' / 'gate.toml'
    spec.write_text(
        '[series]\nid = "guarded"\n\n[[checks]]\nname = "ok"\n'
        f'run = {json.dumps(run)}\nblocking = true\nindependent = false\n',
        encoding='utf-8',
    )
    return spec


def _home(tmp_path: Path) -> dict[str, str]:
    return {'CONVOY_HOME': str(tmp_path / 'guard-home')}


def _trust_file(env: Mapping[str, str]) -> Path:
    return Path(env['CONVOY_HOME']) / 'hook-trust.toml'


def _write_trust(env: Mapping[str, str], text: str) -> None:
    path = _trust_file(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _stop(cwd: Path | str, transcript: Path | None = None) -> dict[str, Any]:
    payload = json.loads((_FIXTURES / 'subagentstop.json').read_text(encoding='utf-8'))
    payload['cwd'] = str(cwd)
    payload['agent_transcript_path'] = str(transcript) if transcript else ''
    payload['stop_hook_active'] = False
    return payload


def _raw(payload: Any) -> bytes:
    return json.dumps(payload).encode('utf-8')


def _guard(raw: bytes, env: Mapping[str, str], cwd: Path, delegate: Callable[[bytes], int]) -> int:
    return hook_guard.main(raw, env, cwd, delegate)


# --- skip: nothing for the full hook to judge -------------------------------------------------


def test_no_spec_anywhere_exits_silently_and_starts_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work = tmp_path / 'bare' / 'sub'
    work.mkdir(parents=True)
    env = {**_home(tmp_path), 'CLAUDE_PROJECT_DIR': str(tmp_path / 'bare')}
    delegate = _Recorder()
    assert _guard(_raw(_stop(work)), env, work, delegate) == 0
    assert delegate.calls == []  # no convoy process was started
    out = capsys.readouterr()
    assert out.out == '' and out.err == ''


def test_a_spec_with_no_trust_file_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _spec(root)
    delegate = _Recorder()
    assert _guard(_raw(_stop(root)), _home(tmp_path), root, delegate) == 0
    assert delegate.calls == []


def test_a_spec_whose_root_is_not_listed_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _spec(root)
    other = tmp_path / 'other'
    _spec(other)
    env = _home(tmp_path)
    trust_project(other, env)
    delegate = _Recorder()
    assert _guard(_raw(_stop(root)), env, root, delegate) == 0
    assert delegate.calls == []


# --- delegate: the full hook has something to say ---------------------------------------------


def test_a_root_vouched_for_in_the_environment_delegates(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _spec(root)
    env = {**_home(tmp_path), 'CONVOY_TRUSTED_ROOTS': os.pathsep.join(['', str(root)])}
    raw = _raw(_stop(root))
    delegate = _Recorder(exit_code=2)
    assert _guard(raw, env, root, delegate) == 2
    assert delegate.calls == [raw]


def test_a_root_on_the_trust_list_delegates_with_the_exact_bytes(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _spec(root)
    env = _home(tmp_path)
    trust_project(root, env)
    # Bytes as Claude Code may send them: not ASCII, not re-serialised by the guard.
    raw = json.dumps(_stop(root) | {'last_assistant_message': 'feito, ação'}).encode('utf-8')
    delegate = _Recorder(exit_code=7)
    assert _guard(raw, env, root, delegate) == 7
    assert delegate.calls == [raw]


def test_a_changed_spec_delegates_so_the_full_hook_can_refuse_it(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    spec = _spec(root)
    env = _home(tmp_path)
    trust_project(root, env)
    spec.write_text(spec.read_text(encoding='utf-8') + '# edited\n', encoding='utf-8')
    raw = _raw(_stop(root))
    delegate = _Recorder(exit_code=2)
    assert _guard(raw, env, root, delegate) == 2
    assert delegate.calls == [raw]


def test_an_explicit_gate_spec_always_delegates(tmp_path: Path) -> None:
    # Even naming a file that does not exist: the full hook refuses that loudly.
    env = {**_home(tmp_path), 'CONVOY_GATE_SPEC': str(tmp_path / 'missing.toml')}
    raw = _raw(_stop(tmp_path))
    delegate = _Recorder(exit_code=2)
    assert _guard(raw, env, tmp_path, delegate) == 2
    assert delegate.calls == [raw]


@pytest.mark.parametrize(
    'raw',
    [b'', b'not json', b'[1, 2]', b'"text"', b'\xff\xfe{}', b'{"cwd": '],
    ids=['empty', 'not-json', 'array', 'string', 'not-utf8', 'truncated'],
)
def test_stdin_that_is_not_a_hook_event_delegates(tmp_path: Path, raw: bytes) -> None:
    delegate = _Recorder(exit_code=2)
    assert _guard(raw, _home(tmp_path), tmp_path, delegate) == 2
    assert delegate.calls == [raw]


@pytest.mark.parametrize(
    'text',
    [
        'this is [not toml',
        'projects = "a string"',
        '[other]\nkey = 1\n',
        'projects = [1]',
        '[[projects]]\nspec_sha256 = "x"\n',
        '[[projects]]\nroot = "relative/root"\n',
        '[[projects]]\nroot = "/abs"\nspec_sha256 = 3\n',
    ],
    ids=[
        'invalid',
        'projects-not-list',
        'no-projects',
        'item-not-table',
        'no-root',
        'relative-root',
        'digest-not-string',
    ],
)
def test_a_malformed_trust_file_delegates(tmp_path: Path, text: str) -> None:
    root = tmp_path / 'proj'
    _spec(root)
    env = _home(tmp_path)
    _write_trust(env, text)
    delegate = _Recorder()
    _guard(_raw(_stop(root)), env, root, delegate)
    assert len(delegate.calls) == 1


def test_an_unreadable_trust_file_delegates(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _spec(root)
    env = _home(tmp_path)
    _write_trust(env, '')
    _trust_file(env).write_bytes(b'\xff\xfe\x00broken')
    delegate = _Recorder()
    _guard(_raw(_stop(root)), env, root, delegate)
    assert len(delegate.calls) == 1


def test_an_unexpected_error_delegates_rather_than_skipping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError('unexpected')

    monkeypatch.setattr(hook_guard, 'should_delegate', boom)
    delegate = _Recorder()
    _guard(_raw(_stop(tmp_path)), _home(tmp_path), tmp_path, delegate)
    assert len(delegate.calls) == 1


# --- discovery: the full hook's order ---------------------------------------------------------


def test_the_project_dir_spec_is_found_before_the_walk(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    _spec(project)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    env = {**_home(tmp_path), 'CLAUDE_PROJECT_DIR': str(project)}
    trust_project(project, env)
    delegate = _Recorder()
    _guard(_raw(_stop(elsewhere)), env, elsewhere, delegate)
    assert len(delegate.calls) == 1


def test_the_walk_finds_a_parents_spec(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _spec(root)
    deep = root / 'a' / 'b'
    deep.mkdir(parents=True)
    env = _home(tmp_path)
    trust_project(root, env)
    delegate = _Recorder()
    _guard(_raw(_stop(deep)), env, deep, delegate)
    assert len(delegate.calls) == 1


def test_a_relative_payload_cwd_resolves_against_the_process_cwd(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _spec(root)
    env = _home(tmp_path)
    trust_project(root, env)
    for cwd_field in ('', '.'):
        delegate = _Recorder()
        _guard(_raw(_stop(cwd_field)), env, root, delegate)
        assert len(delegate.calls) == 1, cwd_field


# --- parity with the full hook ------------------------------------------------------------------


@dataclass(frozen=True)
class _Layout:
    """One arrangement of spec, trust and payload, built under a fresh ``tmp_path``."""

    name: str
    spec_at: str  # 'none' | 'cwd' | 'parent' | 'project_dir'
    trust: str  # see _arrange
    payload: str = 'stop'  # 'stop' | 'dispatch' | 'not-json' | 'not-object'


_SPEC_PLACES = ('none', 'cwd', 'parent', 'project_dir')
_TRUSTS = (
    'no-file',
    'other-root',
    'listed',
    'listed-changed',
    'env-root',
    'env-other-root',
    'invalid-toml',
    'relative-root',
    'empty-projects',
)
_LAYOUTS = [
    _Layout(f'{spec}-{trust}', spec, trust) for spec in _SPEC_PLACES for trust in _TRUSTS
] + [
    _Layout('dispatch-cwd-no-file', 'cwd', 'no-file', 'dispatch'),
    _Layout('dispatch-cwd-listed', 'cwd', 'listed', 'dispatch'),
    _Layout('not-json', 'none', 'no-file', 'not-json'),
    _Layout('not-object', 'none', 'no-file', 'not-object'),
    _Layout('explicit-spec', 'none', 'explicit', 'stop'),
]


def _arrange(tmp_path: Path, layout: _Layout) -> tuple[bytes, dict[str, str], Path]:
    """Build *layout*: the stdin bytes, the environment and the payload's cwd."""
    base = tmp_path / 'layout'
    project = base / 'project'
    cwd = project / 'sub'
    cwd.mkdir(parents=True)
    spec_root = {
        'none': None,
        'cwd': cwd,
        'parent': project,
        'project_dir': base / 'claimed',
    }[layout.spec_at]
    env = _home(tmp_path)
    if layout.spec_at == 'project_dir':
        env['CLAUDE_PROJECT_DIR'] = str(base / 'claimed')
    if spec_root is not None:
        _spec(spec_root, _SIDE_EFFECT)
    root = spec_root or project
    other = base / 'other'
    match layout.trust:
        case 'no-file':
            pass
        case 'other-root':
            other.mkdir()
            trust_project(other, env)
        case 'listed':
            trust_project(root, env)
        case 'listed-changed':
            _write_trust(
                env,
                f'[[projects]]\nroot = {json.dumps(root.resolve().as_posix())}\n'
                f'spec_sha256 = "{hashlib.sha256(b"old").hexdigest()}"\n',
            )
        case 'env-root':
            env['CONVOY_TRUSTED_ROOTS'] = str(root)
        case 'env-other-root':
            env['CONVOY_TRUSTED_ROOTS'] = str(other)
        case 'invalid-toml':
            _write_trust(env, 'this is [not toml')
        case 'relative-root':
            _write_trust(env, '[[projects]]\nroot = "relative"\n')
        case 'empty-projects':
            _write_trust(env, 'projects = []\n')
        case 'explicit':
            env['CONVOY_GATE_SPEC'] = str(base / 'missing.toml')
        case _:
            raise AssertionError(layout.trust)
    match layout.payload:
        case 'stop':
            raw = _raw(_stop(cwd))
        case 'dispatch':
            payload = json.loads((_FIXTURES / 'posttooluse_agent.json').read_text(encoding='utf-8'))
            payload['cwd'] = str(cwd)
            raw = _raw(payload)
        case 'not-json':
            raw = b'{not json'
        case 'not-object':
            raw = b'[]'
        case _:
            raise AssertionError(layout.payload)
    return raw, env, cwd


def _tree_files(root: Path) -> set[Path]:
    return {path for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize('layout', _LAYOUTS, ids=[layout.name for layout in _LAYOUTS])
def test_whenever_the_guard_skips_the_full_hook_is_silent_and_writes_nothing(
    tmp_path: Path, layout: _Layout
) -> None:
    raw, env, cwd = _arrange(tmp_path, layout)
    delegate = _Recorder()
    exit_code = _guard(raw, env, cwd, delegate)
    if delegate.calls:
        assert delegate.calls == [raw]
        return
    assert exit_code == 0
    before = _tree_files(tmp_path)
    # The full hook's own reading of stdin first: a payload it cannot parse is a loud exit 2.
    payload = parse_event(raw)
    assert not isinstance(payload, str), (layout.name, payload)
    result = decide(payload, env)
    assert result.exit_code == 0, (layout.name, result)
    assert result.stderr == ''
    assert result.record is None or result.record.get('outcome') == 'untrusted', (
        layout.name,
        result.record,
    )
    # decide() runs a trusted gate; a skipped layout must never have reached one.
    assert _tree_files(tmp_path) == before


def test_the_parity_table_exercises_both_answers(tmp_path: Path) -> None:
    """Non-vacuity: the table holds layouts the guard skips and layouts it delegates."""
    answers: set[bool] = set()
    for index, layout in enumerate(_LAYOUTS):
        raw, env, cwd = _arrange(tmp_path / str(index), layout)
        delegate = _Recorder()
        _guard(raw, env, cwd, delegate)
        answers.add(bool(delegate.calls))
    assert answers == {True, False}


# --- the module itself ------------------------------------------------------------------------


def test_the_guard_imports_only_the_standard_library() -> None:
    tree = ast.parse(_GUARD.read_text(encoding='utf-8'))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, 'relative import'
            imported.append(node.module or '')
    assert imported, 'no imports found — the walk is not reading the guard'
    outside = [name for name in imported if name.split('.')[0] not in sys.stdlib_module_names]
    assert outside == []


def test_the_delegate_runs_convoy_hook_from_the_plugin_root() -> None:
    argv = hook_guard.delegate_argv('uv')
    assert argv[0] == 'uv'
    assert argv[1:3] == ['run', '--project']
    assert Path(argv[3]) == _REPO_ROOT
    assert argv[-2:] == ['convoy', 'hook']


def test_uv_comes_from_the_environment_when_it_names_a_file(tmp_path: Path) -> None:
    fake = tmp_path / 'uv-binary'
    fake.write_bytes(b'')
    assert hook_guard.find_uv({'UV': str(fake)}) == str(fake)
    assert hook_guard.find_uv({'UV': str(tmp_path / 'missing')}) != str(tmp_path / 'missing')


def test_no_uv_at_all_is_a_loud_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr('shutil.which', lambda _name: None)
    assert hook_guard.run_delegate(b'{}', {}) == 2
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'uv' in err


# --- end to end ---------------------------------------------------------------------------------


def _run_guard(raw: bytes, env: Mapping[str, str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, '-I', str(_GUARD)],
        input=raw,
        capture_output=True,
        cwd=cwd,
        env=dict(env),
        timeout=300,
        check=False,
    )


def test_the_script_exits_silently_on_an_unarmed_payload(tmp_path: Path) -> None:
    work = tmp_path / 'bare'
    work.mkdir()
    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(work)}
    done = _run_guard(_raw(_stop(work)), env, work)
    assert done.returncode == 0
    assert done.stdout == b''
    assert done.stderr == b''


def test_the_script_delegates_an_armed_trusted_gate_to_convoy_hook(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _spec(root, _OK)
    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(root)}
    trust_project(root, env)
    transcript = tmp_path / 'agent.jsonl'
    transcript.write_text(
        json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'Build it'}})
        + '\n'
        + json.dumps(
            {
                'type': 'assistant',
                'message': {
                    'role': 'assistant',
                    'content': [{'type': 'tool_use', 'name': 'Edit', 'input': {}}],
                },
            }
        )
        + '\n',
        encoding='utf-8',
    )
    done = _run_guard(_raw(_stop(root, transcript)), env, root)
    assert done.returncode == 0, done.stderr.decode('utf-8', 'backslashreplace')
    lines = (root / '.convoy' / 'hook.log').read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])['outcome'] == 'completed'
