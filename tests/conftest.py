"""Suite-wide guards.

No unit test may reach a real agent spawn. ``run_series`` is stubbed per test by
convention; the seat probe is the one other spawn-reaching path inside
``run_series_headless``, so it is neutralized here for every test by default — a test
that exercises the probe's wiring overrides this with its own monkeypatch, and the
probe's own unit tests call ``seat_probe.seat_problem`` directly, which this does not
touch. Without this guard, a machine with a live ``claude`` seat silently spends real
money per CLI test, and a machine without one (CI) fails them with a seat problem.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_real_seat_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('convoy.interface.run_service.seat_problem', lambda *_a, **_k: None)
