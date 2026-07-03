"""Tests for the fail-closed isolation guard (``convoy.interface.fs_probe``).

``tmp_path`` is the scored workspace throughout. A check only gets guarded when it
is *both* blocking and independent; otherwise the probe waves it through. A guarded
check passes the probe only when its ``asset`` genuinely lives out-of-tree and
exists — every other case fails closed with a failing ``CheckResult``, so the pure
verdict never runs a self-graded check as if it were independent.
"""

from pathlib import Path

import pytest

from convoy.core.gate import CheckResult
from convoy.core.spec import Check
from convoy.interface.fs_probe import isolation_result


def _check(*, blocking: bool, independent: bool, asset: str = '') -> Check:
    return Check(
        name='oracle',
        run='python -c "pass"',
        blocking=blocking,
        independent=independent,
        asset=asset,
    )


@pytest.mark.parametrize(
    ('blocking', 'independent'),
    [(False, False), (True, False), (False, True)],
)
def test_non_blocking_or_non_independent_is_waved_through(
    tmp_path: Path, blocking: bool, independent: bool
) -> None:
    # Only a blocking AND independent check is guarded; anything else returns None
    # regardless of asset (here: none declared).
    check = _check(blocking=blocking, independent=independent)
    assert isolation_result(tmp_path, check) is None


def test_blocking_independent_with_no_asset_fails_closed(tmp_path: Path) -> None:
    result = isolation_result(tmp_path, _check(blocking=True, independent=True))
    assert isinstance(result, CheckResult)
    assert result.passed is False
    assert result.detail != ''


def test_asset_inside_workspace_fails_closed(tmp_path: Path) -> None:
    # An asset that lives under the scored workspace is reachable by the
    # implementer, so independence cannot hold: fail closed. The asset exists, to
    # prove containment — not existence — is what trips the guard.
    asset = tmp_path / 'oracles' / 'probe.py'
    asset.parent.mkdir(parents=True)
    asset.write_text('# in-tree oracle\n', encoding='utf-8')
    result = isolation_result(tmp_path, _check(blocking=True, independent=True, asset=str(asset)))
    assert isinstance(result, CheckResult)
    assert result.passed is False


def test_asset_equal_to_workspace_fails_closed(tmp_path: Path) -> None:
    # The workspace directory itself is trivially in-tree.
    result = isolation_result(
        tmp_path, _check(blocking=True, independent=True, asset=str(tmp_path))
    )
    assert isinstance(result, CheckResult)
    assert result.passed is False


def test_nonexistent_out_of_tree_asset_fails_closed(tmp_path: Path) -> None:
    # Out-of-tree but missing: still fail closed — there is no oracle to trust.
    missing = tmp_path.parent / 'does-not-exist-oracle' / 'probe.py'
    assert not missing.exists()
    result = isolation_result(tmp_path, _check(blocking=True, independent=True, asset=str(missing)))
    assert isinstance(result, CheckResult)
    assert result.passed is False


def test_real_out_of_tree_asset_is_isolated(tmp_path: Path) -> None:
    # A real file OUTSIDE the workspace is the one case that runs normally: the
    # probe returns None. Use a sibling dir so it shares no ancestry with tmp_path.
    outside = tmp_path.parent / f'{tmp_path.name}-oracle'
    outside.mkdir(exist_ok=True)
    asset = outside / 'probe.py'
    asset.write_text('# out-of-tree oracle\n', encoding='utf-8')
    check = _check(blocking=True, independent=True, asset=str(asset))
    assert isolation_result(tmp_path, check) is None
