"""Model pricing — resolve a model name to a per-token rate and estimate cost (pure).

Used only for the telemetry ``cost_usd`` fallback: when a provider reports ``0.0``
under a subscription auth, convoy substitutes a token-count estimate so a consumer
never silently reads a real run as free (see ``docs/design/02-formats.md``). Rates
are USD per 1,000,000 tokens; the default is a conservative opus-tier fallback so an
unknown model is over- rather than under-counted.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    """A model's price in USD per 1,000,000 tokens, split by direction."""

    input_per_mtok: float
    output_per_mtok: float


DEFAULT_RATE: Rate = Rate(5.0, 25.0)  # conservative (opus-tier) fallback

# Family substring -> rate, checked case-insensitively against the model name.
# Ordering does not matter: the families are disjoint substrings.
_FAMILY_RATES: tuple[tuple[str, Rate], ...] = (
    ('opus', Rate(5.0, 25.0)),
    ('sonnet', Rate(3.0, 15.0)),
    ('haiku', Rate(1.0, 5.0)),
    ('fable', Rate(10.0, 50.0)),
)


def resolve_rate(model: str) -> Rate:
    """Resolve a model name to a ``Rate`` by case-insensitive family substring.

    ``"opus"`` -> 5/25, ``"sonnet"`` -> 3/15, ``"haiku"`` -> 1/5, ``"fable"`` -> 10/50.
    A name matching no known family returns ``DEFAULT_RATE``.
    """
    lowered = model.lower()
    for family, rate in _FAMILY_RATES:
        if family in lowered:
            return rate
    return DEFAULT_RATE


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate spawn cost in USD from token counts and the model's resolved rate."""
    rate = resolve_rate(model)
    return input_tokens / 1e6 * rate.input_per_mtok + output_tokens / 1e6 * rate.output_per_mtok
