"""Tests for the headless ``claude`` CLI spawn — stub only, no real API or network.

Every test points :class:`~convoy.interface.headless_spawn.HeadlessSpawn` at a stub
``claude`` executable written to ``tmp_path``: a Python script, invoked through a tiny
per-platform launcher so it can sit at argv[0] exactly where the real binary would. The
stub reads its own argv and environment, dumps them to a file the test inspects, and emits
scripted ``--output-format stream-json`` lines to stdout — so the adapter's argv assembly,
env isolation, stream parsing, timeout kill, and failure classification are all exercised
without a real agent.
"""

import json
import os
import stat
import sys
import time
from pathlib import Path

from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.spawn import SpawnRequest, SpawnResult


def _request(
    brief: str = 'do the thing',
    model: str = 'test-model',
    permission_mode: str = 'default',
    tools: tuple[str, ...] = ('Read', 'Edit'),
    budget_usd: float = 1.0,
    timeout_seconds: int = 30,
) -> SpawnRequest:
    return SpawnRequest(
        brief=brief,
        model=model,
        effort='medium',
        permission_mode=permission_mode,
        budget_usd=budget_usd,
        tools=tools,
        timeout_seconds=timeout_seconds,
    )


def _write_stub(tmp_path: Path, body: str) -> str:
    """Write ``body`` as a Python stub CLI and return a launcher path fit for argv[0].

    The stub always dumps its argv and environment to ``capture.json`` next to itself, then
    runs ``body``. A launcher (``.cmd`` on Windows, a shell script elsewhere) invokes the
    stub through this interpreter, so the single-token ``claude_bin`` contract holds on
    every platform without relying on a shebang.
    """
    stub = tmp_path / 'stub_cli.py'
    capture = tmp_path / 'capture.json'
    stub.write_text(
        'import json, os, sys\n'
        f'_capture = {str(capture)!r}\n'
        'with open(_capture, "w", encoding="utf-8") as _f:\n'
        '    json.dump({"argv": sys.argv[1:], "env": dict(os.environ)}, _f)\n'
        f'{body}\n',
        encoding='utf-8',
    )
    if sys.platform == 'win32':
        launcher = tmp_path / 'claude_stub.cmd'
        # %* forwards all args; @echo off keeps the batch banner out of stdout.
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{stub}" %*\r\n', encoding='utf-8')
    else:
        launcher = tmp_path / 'claude_stub.sh'
        launcher.write_text(f'#!/bin/sh\n"{sys.executable}" "{stub}" "$@"\n', encoding='utf-8')
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(launcher)


def _read_capture(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / 'capture.json').read_text(encoding='utf-8'))


def _result_line(**overrides: object) -> str:
    """A stream-json ``result`` event as one NDJSON line, with sensible economy defaults."""
    event: dict[str, object] = {
        'type': 'result',
        'subtype': 'success',
        'is_error': False,
        'result': 'done',
        'total_cost_usd': 0.0123,
        'num_turns': 4,
        'duration_ms': 2500,
        'model': 'claude-sonnet-5',
        'usage': {'input_tokens': 1200, 'output_tokens': 340},
    }
    event.update(overrides)
    return json.dumps(event)


# ---------------------------------------------------------------------------
# Normal completion
# ---------------------------------------------------------------------------


def test_normal_completion_parses_economy(tmp_path: Path) -> None:
    """A valid ``result`` event → ok classification, exit 0, and a fully parsed economy."""
    init = json.dumps({'type': 'system', 'subtype': 'init', 'model': 'claude-sonnet-5'})
    result = _result_line()
    body = f'print({init!r})\nprint({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert isinstance(got, SpawnResult)
    assert got.classification == 'ok'
    assert got.exit_code == 0
    assert got.economy.input_tokens == 1200
    assert got.economy.output_tokens == 340
    assert got.economy.num_turns == 4
    assert got.economy.duration_s == 2.5
    assert got.economy.cost_usd == 0.0123
    assert got.economy.effective_model == 'claude-sonnet-5'
    assert 'done' in got.output


def test_cost_reported_as_is_even_when_zero(tmp_path: Path) -> None:
    """The CLI's cost is returned verbatim — 0 under subscription auth, never estimated here."""
    result = _result_line(total_cost_usd=0.0)
    body = f'print({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'ok'
    assert got.economy.cost_usd == 0.0
    # Token counts still recovered from the result event.
    assert got.economy.input_tokens == 1200


def test_partial_stream_recovers_economy_from_assistant(tmp_path: Path) -> None:
    """No ``result`` event → economy recovered from the last assistant message and turn count."""
    a1 = json.dumps(
        {
            'type': 'assistant',
            'message': {'model': 'm', 'usage': {'input_tokens': 10, 'output_tokens': 5}},
        }
    )
    a2 = json.dumps(
        {
            'type': 'assistant',
            'message': {'model': 'm', 'usage': {'input_tokens': 70, 'output_tokens': 20}},
        }
    )
    body = f'print({a1!r})\nprint({a2!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    # Two assistant messages → two turns; economy from the last one.
    assert got.economy.num_turns == 2
    assert got.economy.input_tokens == 70
    assert got.economy.output_tokens == 20


def test_truncated_json_line_is_tolerated(tmp_path: Path) -> None:
    """A line cut off mid-write does not crash parsing; the valid result still lands."""
    result = _result_line()
    # Emit a good result, then a deliberately truncated JSON fragment (no newline handling
    # needed — the fragment simply fails json.loads and is skipped).
    body = (
        f'sys.stdout.write({result!r} + "\\n")\n'
        'sys.stdout.write(\'{"type": "resu\')\n'
        'sys.exit(0)\n'
    )
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'ok'
    assert got.economy.num_turns == 4


# ---------------------------------------------------------------------------
# argv and environment
# ---------------------------------------------------------------------------


def test_argv_carries_model_permission_and_flags(tmp_path: Path) -> None:
    """The built argv contains the request's model, permission mode, and the core flags."""
    body = f'print({_result_line()!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    spawn.spawn(
        _request(model='claude-opus-4-8', permission_mode='acceptEdits', tools=('Read', 'Bash')),
        cwd=tmp_path,
    )

    argv = _read_capture(tmp_path)['argv']
    assert isinstance(argv, list)
    assert '-p' in argv
    assert 'do the thing' in argv
    assert argv[argv.index('--model') + 1] == 'claude-opus-4-8'
    assert argv[argv.index('--permission-mode') + 1] == 'acceptEdits'
    assert argv[argv.index('--output-format') + 1] == 'stream-json'
    assert argv[argv.index('--allowed-tools') + 1] == 'Read,Bash'
    assert argv[argv.index('--max-budget-usd') + 1] == '1.0'
    # No auto-approve flag is ever added.
    assert '--dangerously-skip-permissions' not in argv


def test_stripped_env_vars_absent_from_child(tmp_path: Path) -> None:
    """Billing / routing overrides in the host env are absent from the child's environment."""
    body = f'print({_result_line()!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    injected = {
        'ANTHROPIC_API_KEY': 'sk-should-be-stripped',
        'ANTHROPIC_BASE_URL': 'https://evil.example',
        'ANTHROPIC_AUTH_TOKEN': 'tok',
        'CLAUDE_CODE_USE_BEDROCK': '1',
    }
    for key, value in injected.items():
        os.environ[key] = value
    try:
        spawn.spawn(_request(), cwd=tmp_path)
    finally:
        for key in injected:
            os.environ.pop(key, None)

    child_env = _read_capture(tmp_path)['env']
    assert isinstance(child_env, dict)
    for key in injected:
        assert key not in child_env, f'{key} leaked into the child env'


def test_config_dir_pinned_when_given(tmp_path: Path) -> None:
    """A ``config_dir`` is passed to the child as ``CLAUDE_CONFIG_DIR``."""
    cfg = tmp_path / 'cred_only'
    cfg.mkdir()
    body = f'print({_result_line()!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body), config_dir=cfg)

    spawn.spawn(_request(), cwd=tmp_path)

    child_env = _read_capture(tmp_path)['env']
    assert isinstance(child_env, dict)
    assert child_env.get('CLAUDE_CONFIG_DIR') == str(cfg)


# ---------------------------------------------------------------------------
# Infrastructure classification
# ---------------------------------------------------------------------------


def test_usage_limit_signature_is_infrastructure(tmp_path: Path) -> None:
    """A usage-limit error on the CLI's stderr → infrastructure classification."""
    body = 'sys.stderr.write("Claude usage limit reached. Upgrade to Pro.\\n")\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'infrastructure'


def test_auth_error_result_is_infrastructure(tmp_path: Path) -> None:
    """An auth failure carried on a non-success result event → infrastructure."""
    result = _result_line(
        is_error=True, subtype='error', result='Authentication failed: not logged in'
    )
    body = f'print({result!r})\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'infrastructure'


def test_retry_exhausted_signature_is_infrastructure(tmp_path: Path) -> None:
    """A retry-exhausted signature on stderr → infrastructure."""
    body = 'sys.stderr.write("overloaded: retries exhausted after 5 attempts\\n")\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'infrastructure'


def test_successful_result_mentioning_limit_is_ok(tmp_path: Path) -> None:
    """A cleanly successful spawn whose output merely mentions a limit stays ok — task content.

    The phrase "usage limit" in the result of a successful run is the agent's own output (an
    error handler it wrote, a test name), not a spawn infrastructure failure.
    """
    result = _result_line(result='Added a test named test_usage_limit_reached and it passes.')
    body = f'print({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'ok'
    assert got.exit_code == 0


def test_plain_task_failure_is_ok_classified(tmp_path: Path) -> None:
    """A non-zero exit with no infrastructure signature is a task outcome, not infrastructure."""
    result = _result_line(is_error=True, subtype='error', result='The tests failed: 2 assertions.')
    body = f'print({result!r})\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'ok'
    assert got.exit_code == 1


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_timeout_returns_infrastructure_without_hanging(tmp_path: Path) -> None:
    """A stub that sleeps past a short timeout → infrastructure, and the call returns promptly.

    proc.py already proves the whole-tree kill reaps grandchildren; here we only assert the
    timeout path classifies infrastructure and does not hang. The stub spawns a grandchild
    (so a kill has something to reach) then blocks well past the 1s timeout.
    """
    body = (
        'import subprocess\n'
        'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])\n'
        'import time\n'
        'time.sleep(3600)\n'
    )
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    start = time.monotonic()
    got = spawn.spawn(_request(timeout_seconds=1), cwd=tmp_path)
    elapsed = time.monotonic() - start

    assert got.classification == 'infrastructure'
    assert got.exit_code == -1
    # The timeout, not a natural exit, ended it (the stub sleeps for an hour); it must return
    # well under the stub's own sleep, with generous margin for the tree-kill drain.
    assert elapsed < 60.0


def test_timeout_recovers_partial_economy(tmp_path: Path) -> None:
    """Economy that streamed before a timeout is still recovered on the infrastructure result."""
    a1 = json.dumps(
        {
            'type': 'assistant',
            'message': {'model': 'm', 'usage': {'input_tokens': 42, 'output_tokens': 8}},
        }
    )
    # Emit one assistant message (flushed), then block past the timeout.
    body = f'sys.stdout.write({a1!r} + "\\n")\nsys.stdout.flush()\nimport time\ntime.sleep(3600)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(timeout_seconds=2), cwd=tmp_path)

    assert got.classification == 'infrastructure'
    assert got.economy.input_tokens == 42
    assert got.economy.output_tokens == 8
    # No result event → duration falls back to the timeout bound.
    assert got.economy.duration_s == 2.0


def test_effective_model_falls_back_to_request_when_stream_has_none(tmp_path: Path) -> None:
    """A stream that never names a model records the requested model, never a blank string."""
    result = _result_line(model='')  # no usable model in the stream (as on a killed spawn)
    body = f'print({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(model='claude-haiku-4-5'), cwd=tmp_path)

    assert got.economy.effective_model == 'claude-haiku-4-5'


def test_effective_model_prefers_the_streamed_model_over_the_request(tmp_path: Path) -> None:
    """When the stream reports a model it wins over the requested one (the resolved model)."""
    result = _result_line(model='claude-sonnet-5')
    body = f'print({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(model='test-model'), cwd=tmp_path)

    assert got.economy.effective_model == 'claude-sonnet-5'


# ---------------------------------------------------------------------------
# Budget-cap classification
# ---------------------------------------------------------------------------


def test_budget_subtype_classifies_as_budget(tmp_path: Path) -> None:
    """A result subtype of error_max_budget_usd is classified 'budget', not 'ok'."""
    result = _result_line(subtype='error_max_budget_usd', is_error=True)
    body = f'print({result!r})\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'budget'
    assert got.exit_code == 1


def test_budget_subtype_with_auth_signature_is_infrastructure(tmp_path: Path) -> None:
    """Infrastructure takes precedence: an auth signature on a budget-capped run is infra."""
    result = _result_line(subtype='error_max_budget_usd', is_error=True)
    body = f'print({result!r})\nsys.stderr.write("invalid api key")\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'infrastructure'


def test_success_subtype_is_ok(tmp_path: Path) -> None:
    result = _result_line(subtype='success')
    body = f'print({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    assert spawn.spawn(_request(), cwd=tmp_path).classification == 'ok'


def test_task_failure_with_error_subtype_stays_ok(tmp_path: Path) -> None:
    """A non-budget error subtype (exit 1, is_error) is a task failure, classified 'ok'."""
    result = _result_line(subtype='error', is_error=True)
    body = f'print({result!r})\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'ok'
    assert got.exit_code == 1


def test_zero_budget_request_omits_the_flag(tmp_path: Path) -> None:
    """Defense-in-depth: a request built with budget 0 omits --max-budget-usd (no zero cap)."""
    result = _result_line()
    body = f'print({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    spawn.spawn(_request(budget_usd=0.0), cwd=tmp_path)

    argv = _read_capture(tmp_path)['argv']
    assert isinstance(argv, list)
    assert '--max-budget-usd' not in argv
