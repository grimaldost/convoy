"""Suite-wide guards.

No unit test may reach a real agent spawn. Two autouse guards hold that, one per
spawn-reaching path:

- **The seat probe** is the spawn-reaching path inside ``run_series_headless`` that even a
  fully stubbed run crosses, so it is neutralized for every test by default — a test that
  exercises the probe's wiring overrides this with its own monkeypatch, and the probe's
  own unit tests call ``seat_probe.seat_problem`` directly, which this does not touch.
- **The spawn itself**: a :class:`HeadlessSpawn` left on the default ``claude`` binary
  raises instead of launching. Every legitimate subprocess-path test points the spawn at a
  stub executable (see ``test_headless_spawn.py``), which the guard passes through
  untouched; reaching :meth:`spawn` on the real binary is only ever a forgotten stub. This
  used to be per-test convention — the exact arrangement under which a live seat silently
  turned five CLI tests into five real spawns per suite pass, and a seatless CI runner
  failed the same five.

Without these, a machine with a live ``claude`` seat spends real money per suite run and a
machine without one fails with a seat problem.
"""

from pathlib import Path

import pytest

from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.spawn import SpawnRequest, SpawnResult

# Derived from the constructor rather than restated, so a renamed default cannot
# quietly turn this guard into a no-op.
_DEFAULT_BINARY = HeadlessSpawn()._claude_bin


@pytest.fixture(autouse=True)
def _no_real_seat_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('convoy.interface.run_service.seat_problem', lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def _no_real_agent_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    real_spawn = HeadlessSpawn.spawn

    def guarded(self: HeadlessSpawn, request: SpawnRequest, cwd: Path) -> SpawnResult:
        if self._claude_bin == _DEFAULT_BINARY:
            raise RuntimeError(
                'real agent spawn reached from the unit suite: this HeadlessSpawn was left '
                'on the default binary. Point it at a stub executable, or stub the spawn.'
            )
        return real_spawn(self, request, cwd)

    monkeypatch.setattr(HeadlessSpawn, 'spawn', guarded)
