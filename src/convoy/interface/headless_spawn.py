"""Headless agent spawn — drive the ``claude`` CLI as a subprocess (shell).

This is the v1 :class:`~convoy.interface.spawn.AgentSpawn` implementation: it runs
``claude -p <brief> --output-format stream-json`` as a detached child process, streams the
newline-delimited JSON it writes to stdout, and materializes the final ``result`` event
into a :class:`~convoy.interface.spawn.SpawnEconomy` for the telemetry record.

It is written to the non-optional invariants the design pins for a scored, reproducible
spawn:

* **Credential-only config isolation** — the child sees a ``CLAUDE_CONFIG_DIR`` pointing at
  a directory that holds the authenticating credential and nothing else, so no ambient
  project config, memory, or history leaks into the run.
* **Env strip of billing / routing overrides** — API keys, auth tokens, base-URL
  overrides, and alternate-backend routing flags are removed from the child environment, so
  a stray host variable cannot silently re-route the spawn to a different backend or change
  who pays (which would break both the isolation claim and cost comparability).
* **Whole-process-tree kill on timeout** — the CLI spawns tool grandchildren; a naive
  ``run`` timeout kills only the direct child and orphans them into the scored workspace.
  The child is launched in its own session/group (POSIX) or process group (Windows) so the
  whole tree can be reaped via :func:`~convoy.interface.proc.kill_process_tree`.
* **Partial-stream economy recovery** — a stream cut off mid-line (a timeout kill, a crash)
  still yields whatever economy the assistant messages carried before it ended.
* **Infrastructure-failure classification** — an auth-expired, usage-limit, or
  retry-exhausted signature is reported as ``'infrastructure'`` so a driver halts cleanly
  instead of scoring the run.

The reported ``cost_usd`` is exactly what the CLI reports; it may be ``0`` under
subscription auth, and a later layer fills the estimate — this adapter does not estimate.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from convoy.interface.proc import kill_process_tree
from convoy.interface.spawn import SpawnEconomy, SpawnRequest, SpawnResult

# Host environment variables that would divert a spawn off the isolated credential: an API
# key or auth token bills a different account, and a base-URL override or alternate-backend
# routing flag sends the request to a different backend entirely. Any of these present in
# the host env would silently change who pays and which backend answers — breaking both the
# isolation guarantee and USD comparability — so they are stripped from every spawn env.
_ENV_STRIP: frozenset[str] = frozenset(
    {
        'ANTHROPIC_API_KEY',
        'ANTHROPIC_AUTH_TOKEN',
        'ANTHROPIC_BASE_URL',
        'ANTHROPIC_BEDROCK_BASE_URL',
        'ANTHROPIC_VERTEX_BASE_URL',
        'CLAUDE_CODE_USE_BEDROCK',
        'CLAUDE_CODE_USE_VERTEX',
        'AWS_BEARER_TOKEN_BEDROCK',
    }
)

# Auth / credential failures: the login is broken or expired. Never a task outcome, and no
# number of retries can fix it — classified infrastructure so a driver halts cleanly.
_AUTH_RE = re.compile(
    r'(invalid api key'
    r'|authentication.{0,20}fail'
    r'|not logged ?in'
    r'|please run.{0,20}/?login'
    r'|unauthorized'
    r'|invalid.{0,20}credential'
    r'|oauth.{0,20}(expired|invalid)'
    r'|credit balance is too low)',
    re.IGNORECASE,
)

# Usage-limit / quota exhaustion: a hard cap distinct from a transient rate limit. Includes
# the CLI's rolling-window "session limit — resets HH:MM" wording. Classified infrastructure
# so a matrix stops cleanly instead of scoring the refusal.
_USAGE_LIMIT_RE = re.compile(
    r'(usage limit'
    r'|usage cap'
    r'|reached your (usage |monthly |weekly )?limit'
    r'|limit reached'
    r'|quota (exceeded|exhausted)'
    r'|out of (credits|quota)'
    r'|session limit'
    r'|upgrade to (pro|max))',
    re.IGNORECASE,
)

# Retry exhaustion: transient failures were retried until the attempt budget ran out. The
# spawn never produced a task result, so it is infrastructure, not a task outcome.
_RETRY_EXHAUSTED_RE = re.compile(
    r'(retr(y|ies).{0,20}(exhausted|exceeded)'
    r'|max.{0,12}retr(y|ies)'
    r'|exhausted.{0,12}retr(y|ies)'
    r'|giving up after.{0,20}(attempt|retr))',
    re.IGNORECASE,
)


def _is_infrastructure_signature(text: str) -> bool:
    """True when ``text`` carries an auth / usage-limit / retry-exhausted signature."""
    return bool(
        _AUTH_RE.search(text) or _USAGE_LIMIT_RE.search(text) or _RETRY_EXHAUSTED_RE.search(text)
    )


@dataclass
class _Parsed:
    """Economy and outcome fields recovered from one spawn's stream-json output."""

    result_text: str = ''
    cost_usd: float = 0.0
    num_turns: int = 0
    duration_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ''
    is_error: bool = False
    saw_result: bool = False


def _tokens(usage: Mapping[str, Any]) -> tuple[int, int]:
    """``(input, output)`` token counts from a CLI usage mapping, defensively.

    Input folds in the cache read / creation buckets the CLI reports separately so a
    cached-heavy run is not undercounted to near zero.
    """
    tin = int(usage.get('input_tokens') or 0)
    tin += int(usage.get('cache_read_input_tokens') or 0)
    tin += int(usage.get('cache_creation_input_tokens') or 0)
    tout = int(usage.get('output_tokens') or 0)
    return tin, tout


def _parse_stream(stdout: str) -> _Parsed:
    """Parse ``--output-format stream-json`` NDJSON into economy fields, defensively.

    Each non-empty line is one JSON object. A line that fails to parse (the fragment a
    timeout kill leaves mid-write) is skipped. The terminal ``result`` event carries the
    authoritative economy; when the stream ends before it arrives, usage and turn count are
    recovered from the last assistant message so a partial run still reports what it burned.
    """
    parsed = _Parsed()
    last_assistant_usage: dict[str, Any] = {}
    assistant_turns = 0
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            continue  # a line cut off mid-write — tolerate it
        if not isinstance(obj, dict):
            continue
        kind = obj.get('type')
        if kind == 'system' and obj.get('subtype') == 'init':
            model = obj.get('model')
            if isinstance(model, str) and model:
                parsed.model = model
        elif kind == 'assistant':
            msg = obj.get('message')
            if isinstance(msg, dict):
                usage = msg.get('usage')
                if isinstance(usage, dict):
                    last_assistant_usage = usage
                    assistant_turns += 1
                model = msg.get('model')
                if isinstance(model, str) and model and not parsed.model:
                    parsed.model = model
        elif kind == 'result':
            parsed.saw_result = True
            result_text = obj.get('result')
            if isinstance(result_text, str):
                parsed.result_text = result_text
            cost = obj.get('total_cost_usd')
            if isinstance(cost, (int, float)):
                parsed.cost_usd = float(cost)
            turns = obj.get('num_turns')
            if isinstance(turns, int):
                parsed.num_turns = turns
            duration = obj.get('duration_ms')
            if isinstance(duration, (int, float)):
                parsed.duration_s = float(duration) / 1000.0
            parsed.is_error = bool(obj.get('is_error', parsed.is_error))
            usage = obj.get('usage')
            if isinstance(usage, dict):
                parsed.input_tokens, parsed.output_tokens = _tokens(usage)
            model = obj.get('model')
            if isinstance(model, str) and model:
                parsed.model = model
    if not parsed.saw_result:
        # Partial stream: recover what economy the assistant messages carried.
        parsed.input_tokens, parsed.output_tokens = _tokens(last_assistant_usage)
        parsed.num_turns = assistant_turns
    return parsed


class HeadlessSpawn:
    """An :class:`~convoy.interface.spawn.AgentSpawn` that drives the ``claude`` CLI headless.

    Each :meth:`spawn` invokes ``claude -p <brief> --output-format stream-json`` in a
    detached child process under an isolated, credential-only ``CLAUDE_CONFIG_DIR``, parses
    the streamed economy from the final ``result`` event, and returns a
    :class:`~convoy.interface.spawn.SpawnResult`.
    """

    def __init__(self, claude_bin: str = 'claude', config_dir: Path | None = None) -> None:
        """Bind the CLI executable and the optional credential-only config directory.

        ``claude_bin`` is the executable (or a stub, for tests). ``config_dir``, when given,
        is passed as ``CLAUDE_CONFIG_DIR`` so the spawn authenticates from it and sees no
        other project config; when ``None`` the child inherits the host's config directory.
        """
        self._claude_bin = claude_bin
        self._config_dir = config_dir

    def _build_argv(self, request: SpawnRequest) -> list[str]:
        """Assemble the ``claude`` argv from ``request``. Pure — no I/O.

        The budget bound is ``--max-budget-usd`` (the installed CLI's spend cap). ``--verbose``
        is required for ``stream-json`` to emit its per-event stream. There is no
        auto-approve flag: the pinned ``--permission-mode`` plus the explicit
        ``--allowed-tools`` allowlist is the boundary.
        """
        argv = [
            self._claude_bin,
            '-p',
            request.brief,
            '--output-format',
            'stream-json',
            '--verbose',
            '--model',
            request.model,
            '--effort',
            request.effort,
            '--permission-mode',
            request.permission_mode,
            '--no-session-persistence',
        ]
        if request.tools:
            argv += ['--allowed-tools', ','.join(request.tools)]
        if request.budget_usd:
            argv += ['--max-budget-usd', str(request.budget_usd)]
        return argv

    def _build_env(self) -> dict[str, str]:
        """The child environment: the host env minus billing/routing diverters, with
        ``CLAUDE_CONFIG_DIR`` pinned to the credential-only directory when one was given."""
        env = os.environ.copy()
        for name in _ENV_STRIP:
            env.pop(name, None)
        if self._config_dir is not None:
            env['CLAUDE_CONFIG_DIR'] = str(self._config_dir)
        return env

    def _economy(self, parsed: _Parsed, fallback_duration_s: float) -> SpawnEconomy:
        """Build the :class:`SpawnEconomy` from parsed fields, falling back on wall time."""
        duration_s = parsed.duration_s if parsed.duration_s else fallback_duration_s
        return SpawnEconomy(
            input_tokens=parsed.input_tokens,
            output_tokens=parsed.output_tokens,
            num_turns=parsed.num_turns,
            duration_s=duration_s,
            cost_usd=parsed.cost_usd,
            effective_model=parsed.model,
        )

    def spawn(self, request: SpawnRequest, cwd: Path) -> SpawnResult:
        """Run the CLI against ``request`` in ``cwd`` and return its result plus economy.

        Launches the child detached (own session on POSIX, own process group on Windows) so
        the whole tree can be reaped, drives it with ``communicate(timeout=...)``, and on a
        :class:`subprocess.TimeoutExpired` kills the process tree, recovers whatever economy
        streamed before the kill, and returns an ``'infrastructure'`` result. Otherwise the
        stream is parsed and the run is classified ``'infrastructure'`` on an
        auth / usage-limit / retry-exhausted signature, or ``'ok'`` on any real task result.
        """
        argv = self._build_argv(request)
        env = self._build_env()

        # Launch detached from convoy's own group/session so the whole tree can be killed on
        # timeout (a naive timeout would orphan the CLI's tool grandchildren into the scored
        # workspace). Both knobs are passed on every platform at their no-op defaults so the
        # Popen overload still resolves; the Windows flag is only read under the win32 guard.
        creationflags = 0
        new_session = False
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            new_session = True

        child = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            creationflags=creationflags,
            start_new_session=new_session,
        )
        try:
            stdout, stderr = child.communicate(timeout=request.timeout_seconds)
        except subprocess.TimeoutExpired:
            kill_process_tree(child.pid)
            # Drain whatever streamed before the kill; the pipes are closed by the kill.
            stdout, stderr = child.communicate()
            parsed = _parse_stream(stdout or '')
            return SpawnResult(
                exit_code=-1,
                output=(stdout or '') + (stderr or ''),
                economy=self._economy(parsed, fallback_duration_s=float(request.timeout_seconds)),
                classification='infrastructure',
            )

        stdout = stdout or ''
        stderr = stderr or ''
        parsed = _parse_stream(stdout)
        exit_code = child.returncode
        success = exit_code == 0 and not parsed.is_error

        # Infrastructure iff a signature is on the CLI's own stderr, or the spawn did not
        # cleanly succeed and carries one in its result text. A cleanly successful spawn that
        # merely mentions "usage limit" (an error handler it wrote, a test name) is task
        # content, not a spawn failure — so it stays 'ok'.
        infrastructure = _is_infrastructure_signature(stderr) or (
            not success and _is_infrastructure_signature(parsed.result_text)
        )
        classification = 'infrastructure' if infrastructure else 'ok'

        return SpawnResult(
            exit_code=exit_code,
            output=stdout + stderr,
            economy=self._economy(parsed, fallback_duration_s=0.0),
            classification=classification,
        )
