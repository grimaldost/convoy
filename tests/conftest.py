"""Suite-wide guards.

No unit test may reach a real agent spawn. Two autouse guards hold that, one per
spawn-reaching path:

- **The seat probe** is the spawn-reaching path inside ``run_series_headless`` that even a
  fully stubbed run crosses, so it is neutralized for every test by default — a test that
  exercises the probe's wiring overrides this with its own monkeypatch, and the probe's
  own unit tests call ``seat_probe.seat_problem`` directly, which this does not touch.
- **The spawn itself**: a :class:`HeadlessSpawn` left on the default ``claude`` binary —
  or pointed at the real installed one by absolute path — raises instead of launching.
  Every legitimate subprocess-path test points the spawn at a
  stub executable (see ``test_headless_spawn.py``), which the guard passes through
  untouched; reaching :meth:`spawn` on the real binary is only ever a forgotten stub. This
  used to be per-test convention — the exact arrangement under which a live seat silently
  turned five CLI tests into five real spawns per suite pass, and a seatless CI runner
  failed the same five.

Without these, a machine with a live ``claude`` seat spends real money per suite run and a
machine without one fails with a seat problem.
"""

import shutil
from pathlib import Path

import pytest

from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.spawn import SpawnRequest, SpawnResult

# Derived from the constructor rather than restated, so a renamed default cannot
# quietly turn this guard into a no-op.
_DEFAULT_BINARY = HeadlessSpawn()._claude_bin

# The literal default is not the only spelling of the real binary: a spawn pointed at
# `shutil.which('claude')` names the same executable by absolute path. Resolved once here,
# so that arm of the guard exists exactly on the machines where the real binary does.
_real = shutil.which(_DEFAULT_BINARY)
_REAL_BINARY = Path(_real).resolve() if _real else None


@pytest.fixture(autouse=True)
def _no_real_convoy_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test reads and writes its trust list and oracles under ``tmp_path``.

    Three scaffold tests once wrote pytest temp paths into the developer's real
    ``~/.convoy/hook-trust.toml`` — live trust entries at re-creatable paths. The home is
    pinned suite-wide so no test can reach the real one again.
    """
    monkeypatch.setenv('CONVOY_HOME', str(tmp_path / '.convoy-home'))
    monkeypatch.delenv('CONVOY_TRUSTED_ROOTS', raising=False)
    monkeypatch.delenv('CONVOY_GATE_SPEC', raising=False)


@pytest.fixture(autouse=True)
def _no_real_seat_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('convoy.interface.run_service.seat_problem', lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def _no_real_agent_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    real_spawn = HeadlessSpawn.spawn

    def guarded(self: HeadlessSpawn, request: SpawnRequest, cwd: Path) -> SpawnResult:
        binary = self._claude_bin
        is_real = binary == _DEFAULT_BINARY or (
            _REAL_BINARY is not None and Path(binary).resolve() == _REAL_BINARY
        )
        if is_real:
            raise RuntimeError(
                'real agent spawn reached from the unit suite: this HeadlessSpawn names the '
                'real binary. Point it at a stub executable, or stub the spawn.'
            )
        return real_spawn(self, request, cwd)

    monkeypatch.setattr(HeadlessSpawn, 'spawn', guarded)
