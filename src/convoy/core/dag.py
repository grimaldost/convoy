"""Dependency ordering for a series' PRs (pure; no I/O).

``order`` topologically sorts PRs so each appears after everything in its
``depends_on``. The sort is stable: among PRs with no ordering constraint between
them, the input order is preserved. A cycle or an unknown ``depends_on`` id is a
``DagError`` — the graph cannot be executed.
"""

from collections.abc import Sequence

from convoy.core.spec import PR


class DagError(ValueError):
    """A PR dependency graph is invalid (a cycle, or an unknown dependency)."""


def order(prs: Sequence[PR]) -> tuple[PR, ...]:
    """Return ``prs`` in a dependency-respecting, stable topological order.

    Every PR appears after all PRs named in its ``depends_on``. Among PRs with no
    constraint between them, the input order is preserved (Kahn's algorithm, ready
    nodes taken in input order). Raises ``DagError`` on a cycle or if any
    ``depends_on`` id is not among the given PRs' ids.
    """
    by_id: dict[str, PR] = {}
    index_of: dict[str, int] = {}
    for position, pr in enumerate(prs):
        if pr.id in by_id:
            raise DagError(f'duplicate PR id {pr.id!r}')
        by_id[pr.id] = pr
        index_of[pr.id] = position

    # Validate edges up front so an unknown dependency is reported plainly rather
    # than surfacing later as a phantom cycle.
    for pr in prs:
        for dependency in pr.depends_on:
            if dependency not in by_id:
                raise DagError(f'PR {pr.id!r}: unknown dependency {dependency!r}')

    # Kahn's algorithm. remaining_deps counts each PR's unsatisfied dependencies;
    # dependents maps a PR to those that depend on it. A PR is ready when its count
    # reaches zero. ``set(depends_on)`` collapses a repeated edge so it is counted
    # once. Choosing the input-earliest ready node each step keeps the sort stable.
    remaining_deps: dict[str, int] = {pr.id: len(set(pr.depends_on)) for pr in prs}
    dependents: dict[str, list[str]] = {pr.id: [] for pr in prs}
    for pr in prs:
        for dependency in set(pr.depends_on):
            dependents[dependency].append(pr.id)

    ordered: list[PR] = []
    # ``ready`` is used as an ordered set (dict keys); membership matters, values do not.
    ready: dict[str, None] = {pr.id: None for pr in prs if remaining_deps[pr.id] == 0}
    while ready:
        current_id = min(ready, key=lambda pr_id: index_of[pr_id])
        del ready[current_id]
        ordered.append(by_id[current_id])
        for dependent_id in dependents[current_id]:
            remaining_deps[dependent_id] -= 1
            if remaining_deps[dependent_id] == 0:
                ready[dependent_id] = None

    if len(ordered) != len(by_id):
        unresolved = sorted(pr.id for pr in prs if remaining_deps[pr.id] > 0)
        raise DagError(f'dependency cycle among PRs: {unresolved}')

    return tuple(ordered)
