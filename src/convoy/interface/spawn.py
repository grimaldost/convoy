"""The agent-spawn port — "run an agent against a brief → result + economy" (shell).

This is the seam that lets one core serve both a headless driver (v1) and, later, an
in-session driver (v2): a :class:`Protocol` describing a single ``spawn`` call, plus the
value types that cross it. A :class:`SpawnRequest` pins everything a reproducible run
needs (model, effort, permission mode, budget, tools, timeout); a :class:`SpawnResult`
carries the agent's output plus its :class:`SpawnEconomy` and a coarse ``classification``
separating a normal task result from an infrastructure failure.

Concrete implementations live behind this port; :class:`FakeSpawn` is the deterministic
one that drives the drivers' tests without a real agent.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SpawnRequest:
    """Everything a single agent spawn needs — the reproducibility-pinned inputs."""

    brief: str
    model: str
    effort: str
    permission_mode: str
    budget_usd: float
    tools: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class SpawnEconomy:
    """The per-spawn economy an implementation reports back for the telemetry record."""

    input_tokens: int
    output_tokens: int
    num_turns: int
    duration_s: float
    cost_usd: float
    effective_model: str


@dataclass(frozen=True)
class SpawnResult:
    """An agent spawn's outcome: exit code, output, economy, and a coarse classification.

    ``classification`` is ``'ok'`` for a normal task result (whatever the exit code) or
    ``'infrastructure'`` when the spawn failed for a transient/auth/usage reason rather
    than the task itself — the distinction a driver needs to halt cleanly on a bad matrix.
    """

    exit_code: int
    output: str
    economy: SpawnEconomy
    classification: str


class AgentSpawn(Protocol):
    """The port: run an agent against a request in ``cwd`` and return its result."""

    def spawn(self, request: SpawnRequest, cwd: Path) -> SpawnResult: ...


class FakeSpawn:
    """A deterministic :class:`AgentSpawn` for tests.

    Returns the scripted results in order and records every ``(request, cwd)`` it was
    called with. Raises :class:`AssertionError` if called more times than it has scripted
    results. Not frozen — it accumulates :attr:`calls` — while the value dataclasses it
    hands back are.
    """

    calls: list[tuple[SpawnRequest, Path]]

    def __init__(self, results: Sequence[SpawnResult]) -> None:
        self._results: list[SpawnResult] = list(results)
        self._index = 0
        self.calls = []

    def spawn(self, request: SpawnRequest, cwd: Path) -> SpawnResult:
        """Record the call and return the next scripted result, or assert if exhausted."""
        self.calls.append((request, cwd))
        assert self._index < len(self._results), (
            f'FakeSpawn called {self._index + 1} times but only {len(self._results)} '
            'result(s) were scripted'
        )
        result = self._results[self._index]
        self._index += 1
        return result


def ok_result(
    cost_usd: float = 0.01, model: str = 'test-model', output: str = 'done'
) -> SpawnResult:
    """An ``ok``-classified :class:`SpawnResult` with ``exit_code`` 0 and a filled-in economy."""
    return SpawnResult(
        exit_code=0,
        output=output,
        economy=SpawnEconomy(
            input_tokens=100,
            output_tokens=50,
            num_turns=1,
            duration_s=1.0,
            cost_usd=cost_usd,
            effective_model=model,
        ),
        classification='ok',
    )
