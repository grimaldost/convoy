"""Measure what the plugin hook costs a firing that has no gate to run.

Runs the ``SubagentStop`` handler from ``<plugin root>/hooks/hooks.json`` the way Claude Code
does — exec form when the handler has ``args`` (``${CLAUDE_PLUGIN_ROOT}`` substituted in the
text), else shell form: ``sh -c`` on macOS and Linux, Git Bash on Windows
(``CLAUDE_CODE_GIT_BASH_PATH`` when set, else the ``bash.exe`` of the Git on PATH) — with a
synthetic ``SubagentStop`` whose ``cwd`` is a fresh temporary directory holding no gate.

One warm-up run is reported and excluded; then N measured runs. Every sample, the median,
min, max and every exit code are printed. Exits 1 when any run exits non-zero or writes to
stdout: a no-gate firing must be silent.

    uv run python scripts/hook_latency.py [--plugin-root PATH] [--runs N] [--json]
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_ROOT_VAR = '${CLAUDE_PLUGIN_ROOT}'

# Dropped from the hook's environment: they would arm or point the hook, or (the last three)
# were set by the ``uv run`` that started this script, not by Claude Code.
_DROPPED_ENV = (
    'CONVOY_GATE_SPEC',
    'CONVOY_TRUSTED_ROOTS',
    'VIRTUAL_ENV',
    'UV',
    'UV_RUN_RECURSION_DEPTH',
)


def _git_bash() -> str:
    explicit = os.environ.get('CLAUDE_CODE_GIT_BASH_PATH')
    if explicit:
        return explicit
    git = shutil.which('git')
    if git is None:
        raise SystemExit(
            'git is not on PATH, so Git Bash cannot be found; set CLAUDE_CODE_GIT_BASH_PATH'
        )
    # Never a bare `bash`: on Windows it can resolve to WSL. Git for Windows keeps bash.exe in
    # `<git root>/bin`, and `git.exe` sits in `<git root>/cmd` or `<git root>/bin`.
    for parent in Path(git).resolve().parents:
        candidate = parent / 'bin' / 'bash.exe'
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(f'no bin/bash.exe above {git}; set CLAUDE_CODE_GIT_BASH_PATH')


def handler_argv(plugin_root: Path) -> list[str]:
    """The SubagentStop handler of *plugin_root*'s ``hooks/hooks.json``, as an argv."""
    data = json.loads((plugin_root / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))
    handlers = [hook for entry in data['hooks']['SubagentStop'] for hook in entry['hooks']]
    if len(handlers) != 1:
        raise SystemExit(f'expected one SubagentStop handler, found {len(handlers)}')
    handler = handlers[0]
    root = str(plugin_root)
    if 'args' in handler:
        return [
            handler['command'].replace(_PLUGIN_ROOT_VAR, root),
            *(str(arg).replace(_PLUGIN_ROOT_VAR, root) for arg in handler['args']),
        ]
    shell = _git_bash() if sys.platform == 'win32' else 'sh'
    return [shell, '-c', handler['command']]


def measure(plugin_root: Path, runs: int) -> dict:
    argv = handler_argv(plugin_root)
    with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as home:
        env = {k: v for k, v in os.environ.items() if k not in _DROPPED_ENV}
        env.update(
            CLAUDE_PLUGIN_ROOT=str(plugin_root),
            CLAUDE_PROJECT_DIR=work,
            CONVOY_HOME=home,
        )
        payload = json.dumps(
            {
                'hook_event_name': 'SubagentStop',
                'session_id': 'latency-session',
                'agent_id': 'latency-agent',
                'cwd': work,
                'stop_hook_active': False,
                'agent_transcript_path': '',
            }
        ).encode('utf-8')
        samples: list[dict] = []
        for _ in range(runs + 1):
            started = time.perf_counter()
            done = subprocess.run(argv, input=payload, capture_output=True, cwd=work, env=env)
            elapsed = (time.perf_counter() - started) * 1000
            samples.append(
                {
                    'ms': round(elapsed, 1),
                    'exit_code': done.returncode,
                    'stdout': done.stdout.decode('utf-8', 'backslashreplace'),
                    'stderr': done.stderr.decode('utf-8', 'backslashreplace'),
                }
            )
    warmup, measured = samples[0], samples[1:]
    times = [sample['ms'] for sample in measured]
    return {
        'plugin_root': str(plugin_root),
        'argv': argv,
        'warmup': warmup,
        'runs': runs,
        'samples_ms': times,
        'median_ms': round(statistics.median(times), 1),
        'min_ms': min(times),
        'max_ms': max(times),
        'exit_codes': [sample['exit_code'] for sample in measured],
        'stdout': [sample['stdout'] for sample in measured if sample['stdout']],
        'stderr': [sample['stderr'] for sample in measured if sample['stderr']],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--plugin-root', type=Path, default=_REPO_ROOT)
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--json', action='store_true', help='print the result as JSON')
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be at least 1')
    result = measure(args.plugin_root.resolve(), args.runs)
    ok = all(code == 0 for code in result['exit_codes']) and not result['stdout']
    ok = ok and result['warmup']['exit_code'] == 0 and not result['warmup']['stdout']
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        warmup = result['warmup']
        print(f'plugin root: {result["plugin_root"]}')
        print(f'handler:     {result["argv"]}')
        print(f'warm-up:     {warmup["ms"]} ms (exit {warmup["exit_code"]}, excluded)')
        print(f'samples ms:  {result["samples_ms"]}')
        print(
            f'median {result["median_ms"]} ms, min {result["min_ms"]} ms, '
            f'max {result["max_ms"]} ms over {result["runs"]} runs'
        )
        print(f'exit codes:  {result["exit_codes"]}')
        for text in result['stdout']:
            print(f'stdout: {text!r}')
        for text in result['stderr']:
            print(f'stderr: {text!r}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
