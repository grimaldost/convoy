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
import shutil
import stat
import sys
import time
from pathlib import Path

import pytest

from convoy.interface.headless_spawn import _RESULT_SUBTYPES, HeadlessSpawn
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


def test_num_turns_falls_back_to_assistant_count_when_result_omits_it(tmp_path: Path) -> None:
    """A terminal ``result`` lacking a valid ``num_turns`` still reports the counted turns.

    The stream completes (a ``result`` event arrives), so the no-result partial-stream
    fallback never fires — but the result event carries ``num_turns: null`` (or a non-int).
    The economy must reflect the assistant turns actually seen, not a silent ``0``.
    """
    assistants = [
        json.dumps(
            {
                'type': 'assistant',
                'message': {'model': 'm', 'usage': {'input_tokens': 10, 'output_tokens': 5}},
            }
        )
        for _ in range(3)
    ]
    result = _result_line(num_turns=None)  # present result, but no usable turn count
    prints = '\n'.join(f'print({line!r})' for line in [*assistants, result])
    body = f'{prints}\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'ok'
    assert got.economy.num_turns == 3  # the three assistant turns, not 0


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
        is_error=True,
        subtype='error_during_execution',
        result='Authentication failed: not logged in',
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
    result = _result_line(
        is_error=True, subtype='error_during_execution', result='The tests failed: 2 assertions.'
    )
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


def test_budget_subtype_with_usage_phrase_in_result_stays_budget(tmp_path: Path) -> None:
    """A budget-capped run whose partial result text mentions a limit stays 'budget', not infra.

    The agent's own truncated output ("limit reached") is task content, not a spawn
    infrastructure failure — the authoritative signal is the ``error_max_budget_usd``
    subtype. Only the CLI's own stderr channel may override it to infrastructure.
    """
    result = _result_line(
        subtype='error_max_budget_usd',
        is_error=True,
        result='stopping early — limit reached in the retry loop',
    )
    body = f'print({result!r})\nsys.exit(1)\n'  # clean stderr; the phrase is only in result text
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'budget'


def test_success_subtype_is_ok(tmp_path: Path) -> None:
    result = _result_line(subtype='success')
    body = f'print({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    assert spawn.spawn(_request(), cwd=tmp_path).classification == 'ok'


def test_task_failure_with_error_subtype_stays_ok(tmp_path: Path) -> None:
    """A recorded non-budget error subtype (exit 1, is_error) is a task failure: 'ok'."""
    result = _result_line(subtype='error_during_execution', is_error=True)
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


# ---------------------------------------------------------------------------
# Diagnosis: why a non-ok spawn was classified that way
#
# The classification alone tells a caller to halt; it does not tell the operator what
# broke. The whole stream does, buried. The diagnosis is the sentence from the channel
# that decided the verdict, so the two cannot drift.
# ---------------------------------------------------------------------------


def test_diagnosis_quotes_the_stderr_that_decided_it(tmp_path: Path) -> None:
    body = 'sys.stderr.write("Claude usage limit reached. Upgrade to Pro.\\n")\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.diagnosis == 'Claude usage limit reached. Upgrade to Pro.'


def test_diagnosis_quotes_the_result_text_when_that_decided_it(tmp_path: Path) -> None:
    result = _result_line(
        is_error=True,
        subtype='error_during_execution',
        result='Authentication failed: not logged in',
    )
    body = f'print({result!r})\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.diagnosis == 'Authentication failed: not logged in'


def test_a_budget_truncation_carries_its_own_diagnosis(tmp_path: Path) -> None:
    result = _result_line(is_error=True, subtype='error_max_budget_usd', result='ran out of budget')
    body = f'print({result!r})\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'budget'
    assert got.diagnosis == 'ran out of budget'


def test_an_ok_spawn_has_nothing_to_diagnose(tmp_path: Path) -> None:
    body = f'print({_result_line()!r})\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'ok'
    assert got.diagnosis == ''


def test_diagnosis_is_one_line_however_the_cli_wrapped_it(tmp_path: Path) -> None:
    """It is embedded in one-line messages; an embedded newline breaks every one of them."""
    body = (
        'sys.stderr.write("Invalid API key\\n  please run /login\\n\\n  again\\n")\nsys.exit(1)\n'
    )
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert '\n' not in got.diagnosis
    assert got.diagnosis == 'Invalid API key please run /login again'


def test_diagnosis_is_bounded(tmp_path: Path) -> None:
    """The head, not the tail: a diagnosis leads with the diagnosis."""
    long_tail = 'x' * 1000
    body = f'sys.stderr.write("Invalid API key " + {long_tail!r} + "\\n")\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert len(got.diagnosis) <= 300
    assert got.diagnosis.startswith('Invalid API key')


def test_diagnosis_falls_back_to_the_subtype_when_the_cli_said_nothing(tmp_path: Path) -> None:
    """Thin, but a name beats an empty field; the raw stream is still there for more."""
    result = _result_line(is_error=True, subtype='error_max_budget_usd', result='')
    body = f'print({result!r})\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'budget'
    assert got.diagnosis == "result subtype 'error_max_budget_usd'"


def test_a_timeout_diagnoses_itself(tmp_path: Path) -> None:
    """The timeout IS the diagnosis; whatever the CLI was mid-sentence about is not."""
    body = 'import time\ntime.sleep(30)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(timeout_seconds=1), cwd=tmp_path)

    assert got.classification == 'infrastructure'
    assert got.diagnosis == 'no result within the 1s timeout'


# ---------------------------------------------------------------------------
# Structured signals over prose: a refused invocation is not a clean result
# ---------------------------------------------------------------------------
#
# `_classify` matched the vendor CLI's prose on stderr and returned 'ok' for any non-success
# spawn carrying no auth / usage / retry signature. So a spawn the CLI refused at argument
# parse -- a flag renamed upstream, a value dropped from a choice list -- was scored as a
# clean task result with $0 economy, and the seat probe, which blocks only on
# 'infrastructure', passed it. The operator then saw a blocked run with $0 spend and no
# diagnosis.


def test_a_spawn_refused_at_argument_parse_is_infrastructure(tmp_path: Path) -> None:
    """No result event at all: the CLI never got as far as running the task."""
    body = (
        "sys.stderr.write(\"error: option '--effort <level>' argument 'lo' is invalid.\")\n"
        'sys.exit(1)\n'
    )
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'infrastructure'
    assert got.economy.cost_usd == 0.0
    # And it says why, so the operator is not left with a blocked run and no diagnosis.
    assert '--effort' in got.diagnosis


def test_a_silent_refusal_still_names_the_finding(tmp_path: Path) -> None:
    """Nothing on stderr either -- 'the CLI never ran the task' is itself the diagnosis."""
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, 'sys.exit(2)\n'))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'infrastructure'
    assert 'result event' in got.diagnosis


def test_a_clean_exit_with_no_result_event_is_left_alone(tmp_path: Path) -> None:
    """The rule is narrow on purpose: it fires on a NON-SUCCESS spawn, not on a quiet one."""
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, 'sys.exit(0)\n'))

    assert spawn.spawn(_request(), cwd=tmp_path).classification == 'ok'


@pytest.mark.parametrize(
    ('subtype', 'expected'), sorted((k, v) for k, v in _RESULT_SUBTYPES.items())
)
def test_every_subtype_convoy_has_a_decision_for_classifies_as_recorded(
    tmp_path: Path, subtype: str, expected: str
) -> None:
    """The table in the source IS the decision; this asserts the classifier implements it."""
    failed = expected != 'ok'
    result = _result_line(subtype=subtype, is_error=failed)
    body = f'print({result!r})\nsys.exit({1 if failed else 0})\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    assert spawn.spawn(_request(), cwd=tmp_path).classification == expected


def test_an_unrecognised_subtype_on_a_failed_spawn_is_not_scored_as_clean(
    tmp_path: Path,
) -> None:
    """A subtype convoy has no decision for is a reason it does not understand.

    Scoring it 'ok' with zero economy is the one guess that is wrong silently. The recovery
    when the CLI ships a new subtype is to record a decision for it in `_RESULT_SUBTYPES`,
    not to widen the guess.
    """
    result = _result_line(subtype='error_something_new', is_error=True, result='what happened')
    body = f'print({result!r})\nsys.exit(1)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    got = spawn.spawn(_request(), cwd=tmp_path)

    assert got.classification == 'infrastructure'
    assert got.diagnosis


def test_an_unrecognised_subtype_on_a_successful_spawn_stays_ok(tmp_path: Path) -> None:
    """A spawn that exited clean produced a task result, whatever the outcome is named."""
    result = _result_line(subtype='error_something_new')
    body = f'print({result!r})\nsys.exit(0)\n'
    spawn = HeadlessSpawn(claude_bin=_write_stub(tmp_path, body))

    assert spawn.spawn(_request(), cwd=tmp_path).classification == 'ok'


# ---------------------------------------------------------------------------
# The suite-wide guard (tests/conftest.py)
# ---------------------------------------------------------------------------


def test_a_spawn_left_on_the_default_binary_is_unreachable_from_the_suite() -> None:
    """The conftest guard's red proof: the real binary raises before anything launches.

    Every other test in this module points the spawn at a stub executable, which the guard
    passes through — this one proves the arrangement that used to cost real money (a
    forgotten stub on a machine with a live seat) now fails loudly instead.
    """
    spawn = HeadlessSpawn()

    with pytest.raises(RuntimeError, match='real agent spawn'):
        spawn.spawn(_request(), cwd=Path('.'))


def test_a_spawn_naming_the_real_binary_by_absolute_path_is_unreachable() -> None:
    """The guard's second arm: an absolute path to the real binary is the same spawn.

    Only provable on a machine that has the real binary; elsewhere the literal-default
    arm is the whole surface and this skips rather than vacuously passes.
    """
    real = shutil.which('claude')
    if real is None:
        pytest.skip('no real claude binary on this machine')
    spawn = HeadlessSpawn(claude_bin=real)

    with pytest.raises(RuntimeError, match='real agent spawn'):
        spawn.spawn(_request(), cwd=Path('.'))
