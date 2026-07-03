"""Tests for pricing: family resolution (substring, case-insensitive) and cost math."""

import pytest

from convoy.core.pricing import DEFAULT_RATE, Rate, estimate_cost_usd, resolve_rate


@pytest.mark.parametrize(
    ('model', 'expected'),
    [
        ('claude-opus-4-8', Rate(5.0, 25.0)),
        ('claude-sonnet-5', Rate(3.0, 15.0)),
        ('claude-haiku-4', Rate(1.0, 5.0)),
        ('fable-1', Rate(10.0, 50.0)),
    ],
)
def test_each_family_resolves_via_substring(model: str, expected: Rate) -> None:
    assert resolve_rate(model) == expected


@pytest.mark.parametrize(
    ('model', 'expected'),
    [
        ('CLAUDE-OPUS-4-8', Rate(5.0, 25.0)),
        ('Claude-Sonnet-5', Rate(3.0, 15.0)),
        ('HAIKU', Rate(1.0, 5.0)),
        ('Fable', Rate(10.0, 50.0)),
    ],
)
def test_resolution_is_case_insensitive(model: str, expected: Rate) -> None:
    assert resolve_rate(model) == expected


def test_unknown_model_returns_default_rate() -> None:
    assert resolve_rate('gpt-9-turbo') == DEFAULT_RATE
    assert resolve_rate('') == DEFAULT_RATE


def test_estimate_cost_for_known_model() -> None:
    # sonnet -> 3/15 per Mtok. 1,000,000 in + 200,000 out = 3.0 + 3.0 = 6.0.
    assert estimate_cost_usd('claude-sonnet-5', 1_000_000, 200_000) == pytest.approx(6.0)


def test_estimate_cost_for_default_model() -> None:
    # Unknown -> DEFAULT_RATE 5/25. 500,000 in + 100,000 out = 2.5 + 2.5 = 5.0.
    assert estimate_cost_usd('gpt-9-turbo', 500_000, 100_000) == pytest.approx(5.0)


def test_estimate_cost_is_zero_for_zero_tokens() -> None:
    assert estimate_cost_usd('claude-opus-4-8', 0, 0) == 0.0
