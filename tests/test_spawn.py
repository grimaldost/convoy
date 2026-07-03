"""Tests for the agent-spawn port: FakeSpawn's scripted-result discipline, structural
conformance to the AgentSpawn Protocol, the ok_result helper, and frozen value types.
"""

import dataclasses
from pathlib import Path

import pytest

from convoy.interface.spawn import (
    AgentSpawn,
    FakeSpawn,
    SpawnEconomy,
    SpawnRequest,
    SpawnResult,
    ok_result,
)


def _request(brief: str = 'do the thing') -> SpawnRequest:
    return SpawnRequest(
        brief=brief,
        model='test-model',
        effort='medium',
        permission_mode='default',
        budget_usd=1.0,
        tools=('read', 'write'),
        timeout_seconds=60,
    )


def test_fake_returns_scripted_results_in_order() -> None:
    first = ok_result(output='first')
    second = ok_result(output='second')
    fake = FakeSpawn([first, second])

    assert fake.spawn(_request(), Path('/a')) is first
    assert fake.spawn(_request(), Path('/b')) is second


def test_fake_records_each_call_with_request_and_cwd() -> None:
    fake = FakeSpawn([ok_result(), ok_result()])
    req_a = _request('a')
    req_b = _request('b')

    fake.spawn(req_a, Path('/one'))
    fake.spawn(req_b, Path('/two'))

    assert fake.calls == [(req_a, Path('/one')), (req_b, Path('/two'))]


def test_fake_raises_when_called_past_the_script() -> None:
    fake = FakeSpawn([ok_result()])
    fake.spawn(_request(), Path('/a'))

    with pytest.raises(AssertionError):
        fake.spawn(_request(), Path('/b'))

    # The over-call is still recorded before the assertion fires.
    assert len(fake.calls) == 2


def test_fake_with_no_results_raises_on_first_call() -> None:
    fake = FakeSpawn([])
    with pytest.raises(AssertionError):
        fake.spawn(_request(), Path('/a'))


def _drive(spawn: AgentSpawn, request: SpawnRequest, cwd: Path) -> SpawnResult:
    """A function annotated to take the Protocol — a FakeSpawn must satisfy it structurally."""
    return spawn.spawn(request, cwd)


def test_fakespawn_conforms_to_agentspawn_protocol() -> None:
    result = ok_result()
    fake = FakeSpawn([result])

    got = _drive(fake, _request(), Path('/work'))

    assert got is result
    assert fake.calls == [(_request(), Path('/work'))]


def test_ok_result_is_ok_classified_with_populated_economy() -> None:
    result = ok_result()

    assert isinstance(result, SpawnResult)
    assert result.classification == 'ok'
    assert result.exit_code == 0
    assert isinstance(result.economy, SpawnEconomy)
    assert result.economy.input_tokens > 0
    assert result.economy.output_tokens > 0
    assert result.economy.effective_model == 'test-model'


def test_ok_result_honors_overrides() -> None:
    result = ok_result(cost_usd=0.5, model='big-model', output='custom')

    assert result.output == 'custom'
    assert result.economy.cost_usd == 0.5
    assert result.economy.effective_model == 'big-model'


def _mutate(obj: object, attr: str, value: object) -> None:
    """Assign ``value`` to ``obj.attr`` dynamically.

    Routing the mutation through ``setattr`` with a non-constant attribute name exercises
    the runtime ``FrozenInstanceError`` on the value dataclasses without a static
    read-only-assignment error (``ty``) and without a constant-``setattr`` lint (``B010``).
    """
    setattr(obj, attr, value)


def test_spawn_request_is_frozen() -> None:
    request = _request()
    with pytest.raises(dataclasses.FrozenInstanceError):
        _mutate(request, 'model', 'other')


def test_spawn_economy_is_frozen() -> None:
    economy = ok_result().economy
    with pytest.raises(dataclasses.FrozenInstanceError):
        _mutate(economy, 'cost_usd', 9.9)


def test_spawn_result_is_frozen() -> None:
    result = ok_result()
    with pytest.raises(dataclasses.FrozenInstanceError):
        _mutate(result, 'exit_code', 1)
