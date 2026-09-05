"""The telemetry model — convoy's ``spawns.jsonl`` events (pure; no I/O).

The append-only JSON-lines telemetry is convoy's economy record and primary
observability surface (see ``docs/design/02-formats.md``). This module defines the
five v1 events (``run_start`` / ``spawn_complete`` / ``gate_complete`` / ``pr_skipped`` /
``run_complete``) and how each serializes to one line; the file writing itself lives in
``interface/telemetry_writer.py``. Every line carries ``schema_version`` and an
``event`` tag, so a consumer keys on both and can ignore unknown fields — evolution is
additive.
"""

import dataclasses
import json
from dataclasses import dataclass

SCHEMA_VERSION = 1

# The fraction of a spawn's cap at which its spend is called out. The cap itself is not
# softened — a spawn that busts it is truncated and the PR halts, which is the feature — but
# the halt is the FIRST thing that says the ceiling was in play, and by then the run is
# already forfeit. Two of ten terminal runs on disk halted on overshoots of 0.3% and 0.4%,
# skipping five downstream PRs between them. A tenth of the ceiling is the window left for a
# monitor to raise the cap or stage recovery before the busting turn.
BUDGET_NEARING_FRACTION = 0.9

# The event tag written on each line, keyed by event dataclass. Kept next to the
# classes so ``to_json_line`` never has to branch on ``isinstance``.
_EVENT_TAGS: dict[type, str] = {}


@dataclass(frozen=True)
class AdvisoryLine:
    """One pre-flight advisory inside a ``run_start`` event — not itself an event.

    A plain nested record, like :class:`GateCheckLine` and :class:`HaltDetail`: no
    ``schema_version`` / ``event`` tag of its own. Deliberately telemetry's own type rather
    than ``core.preflight.Advisory``, so the wire model stays independent of the pre-flight
    model — but it serializes to the same ``{kind, where, message}`` object the dry-run
    envelope already returns, because a consumer meeting an advisory on the run path and on
    the dry-run path should not have to parse two shapes for one idea.
    """

    kind: str
    where: str
    message: str


@dataclass(frozen=True)
class RunStart:
    """Emitted once per ``convoy run``, grouping the invocation's events.

    ``advisories`` carries what pre-flight said that did not stop the run — empty on the
    ordinary case. They ride the terminal-of-the-beginning line for the same reason
    ``halt`` rides ``run_complete``: it keeps the fact reconstructible from the ledger
    alone, so every consumer of a run sees it without the value being threaded through the
    engine's control flow. Before this they were computed and dropped, which meant the
    ungated-PR advisory said nothing on the run that actually integrated the unverified PR.
    """

    run_id: str
    series_id: str
    advisories: tuple[AdvisoryLine, ...] = ()
    # The spec this run's series was decomposed from — repo-relative path and the SHA-256
    # of its contents, carried from ``[series]``. Empty when the series pins nothing.
    # Recorded here for the same reason ``advisories`` is: a pin that stops at the series
    # file leaves the run record unable to answer "which version of which spec produced
    # this", which is the one question a later comparison always needs and the ledger is
    # otherwise the only place to look. Pre-flight has already resolved and matched it, so
    # a recorded pin is a verified one, not a claim.
    spec_path: str = ''
    spec_sha256: str = ''


@dataclass(frozen=True)
class SpawnStart:
    """Emitted immediately before an agent spawn is launched — the in-flight marker.

    Carries no economy: nothing has been spent yet, and a line that promised numbers it
    could not have would be worse than none. Its whole job is to make "which PR is convoy
    working on right now" answerable from the ledger while a 30–90 minute spawn runs, which
    previously it was not: the ledger recorded only completions, so a PR in progress was
    indistinguishable from a PR not yet reached. It also separates a driver that is dead
    from one that is alive but stuck — the second leaves a started spawn that never
    completes.

    ``role`` is one of ``implementation``, ``review``, ``fix``, matching
    :class:`SpawnComplete`, so a consumer pairs the two on ``(run_id, pr_id, role)``.
    """

    run_id: str
    pr_id: str
    role: str


@dataclass(frozen=True)
class SpawnComplete:
    """Emitted once per agent spawn — the per-spawn economy record.

    ``role`` is one of ``implementation``, ``review``, ``fix``. ``cost_estimated`` is
    permanently ``False``: it once marked a line whose ``cost_usd`` came from a local
    price table, and that path is gone (the provider reports a real cost, measured over
    76 production spawns and again on 2026-09-05). The field stays because the schema is
    a public contract and removing a key a consumer reads is worse than leaving it.
    ``output_tail`` carries the
    bounded tail of the spawn's combined stdout+stderr on a non-``ok`` classification
    (``''`` on ok lines), so an infrastructure or budget halt is diagnosable from
    telemetry alone instead of demanding a manual re-run of the spawn.
    """

    run_id: str
    pr_id: str
    role: str
    exit_code: int
    input_tokens: int
    output_tokens: int
    num_turns: int
    duration_s: float
    cost_usd: float
    effective_model: str
    # The effort level this spawn was REQUESTED at. Unlike the model, the CLI reports
    # nothing back about effort, so there is no effective counterpart to record — which is
    # exactly why the requested value belongs here. It was previously written down only in
    # the series file, so a run and its ledger could both agree on a level the spawn never
    # ran at. Empty for a caller that does not supply one.
    effort: str = ''
    cost_estimated: bool = False
    output_tail: str = ''
    # The ceiling this spawn ran under — the resolved ``[governance.budgets].<role>`` value,
    # so a fix line reports the fix cap and not the implementation one it repairs — and
    # whether the spend reached :data:`BUDGET_NEARING_FRACTION` of it. ``None`` when the
    # spawn ran uncapped, in which case ``budget_nearing`` is always false. Recorded because
    # the cap was previously invisible in the ledger until it was busted: a reader could see
    # what a spawn cost but not how close that was to stopping the series.
    budget_cap_usd: float | None = None
    budget_nearing: bool = False
    # The adapter's verdict on WHY the spawn ended: ``ok`` | ``infrastructure`` | ``budget``.
    # It drove the run's control flow all along but was never recorded, so a consumer had to
    # infer it from ``exit_code`` plus the shape of ``output_tail`` — an inference that is
    # wrong exactly when it matters, since a budget cut and an auth failure can both exit 1.
    classification: str = 'ok'


@dataclass(frozen=True)
class HaltDetail:
    """Why and where a run stopped — a nested record inside :class:`RunComplete`.

    Present only on a non-``completed`` outcome. A plain nested record like
    :class:`GateCheckLine`: no ``schema_version`` / ``event`` tag of its own.

    ``pr_id`` and ``phase`` locate the halt in the series, and ``role`` names which spawn
    hit it (``implementation`` or ``fix``) — a repair exhausting the fix budget is a
    different diagnosis from the implementation doing so. ``spend_usd`` / ``cap_usd`` are
    the spawn's cost against the ceiling it hit, populated for a ``budget`` outcome; they
    are ``None`` for halts where no ceiling was involved (``blocked``, ``infrastructure``),
    because reporting a cap that did not cause the halt would invite the wrong fix.
    """

    pr_id: str
    phase: str
    role: str
    spend_usd: float | None = None
    cap_usd: float | None = None


@dataclass(frozen=True)
class RunComplete:
    """Emitted once per ``convoy run``. ``outcome`` is one of ``completed``,
    ``blocked``, ``infrastructure``, ``budget``; ``integrated`` records whether the
    result reached the integration branch.

    ``halt`` carries the located reason on any non-``completed`` outcome and is ``None``
    on a clean run. Without it the terminal record said only *that* a run stopped, so
    answering "which PR, in which phase, and how close to which cap" meant hand-reading
    the whole ledger — the one question a halted run always raises.
    """

    run_id: str
    outcome: str
    integrated: bool
    halt: HaltDetail | None = None


@dataclass(frozen=True)
class RunAbandoned:
    """A terminal record written ABOUT a run, by a later process, once it cannot write one.

    Every other event is written by the run itself. This one is written by the recovery path
    that clears a killed run's workspace lock, which is the only moment at which anyone both
    knows the run is over and still has the ledger open. It exists because a live process
    check has a hard limit: a pid is reusable once its process is gone, so nothing asked
    tomorrow can answer for a run that died today. Recording the fact while it is still
    knowable is what turns a permanently-``running`` ledger entry into history.

    Kept distinct from :class:`RunComplete` rather than folded into it as another ``outcome``:
    a consumer should be able to tell an engine's own verdict from a third party's account of
    a run that never reached one, and only the first is evidence about the work.

    ``reason`` is free-form provenance — how the abandonment was established, not a claim
    about what the run had done. No ``halt`` and no ``integrated``: whoever writes this was
    not there, and inventing a located halt would be the one lie the ledger cannot afford.
    """

    run_id: str
    reason: str


@dataclass(frozen=True)
class GateCheckLine:
    """One check's outcome inside a ``gate_complete`` event — not itself an event.

    A plain nested record: no ``schema_version`` / ``event`` tag and no ``_EVENT_TAGS``
    entry. It serializes to a JSON object via ``dataclasses.asdict`` recursion when the
    enclosing :class:`GateComplete` is written.
    """

    name: str
    passed: bool
    blocking: bool
    independent: bool
    detail: str


@dataclass(frozen=True)
class GateComplete:
    """Emitted after every gate evaluation of a PR — the per-check verdict record.

    ``attempt`` is 0 for the initial gate and 1..N after the Nth fix spawn's re-gate.
    ``checks`` carries one :class:`GateCheckLine` per check in run order; ``blocking_red``
    and ``independent_red`` are the derived verdict flags (see ``core.gate``). This makes a
    blocked run self-explaining in telemetry: a consumer sees which check failed and why.
    """

    run_id: str
    pr_id: str
    attempt: int
    blocking_red: bool
    independent_red: bool
    checks: tuple[GateCheckLine, ...]


@dataclass(frozen=True)
class PRSkipped:
    """Emitted for each PR the run never processed because an earlier PR halted the series.

    ``reason`` is free-form provenance (e.g. ``'series halted at pr-a (blocked) before
    this PR started'``): it states why the series stopped, not a claim of a direct
    dependency edge.
    """

    run_id: str
    pr_id: str
    reason: str


Event = (
    RunStart | SpawnStart | SpawnComplete | RunComplete | RunAbandoned | GateComplete | PRSkipped
)

_EVENT_TAGS[RunStart] = 'run_start'
_EVENT_TAGS[SpawnStart] = 'spawn_start'
_EVENT_TAGS[SpawnComplete] = 'spawn_complete'
_EVENT_TAGS[RunComplete] = 'run_complete'
_EVENT_TAGS[RunAbandoned] = 'run_abandoned'
_EVENT_TAGS[GateComplete] = 'gate_complete'
_EVENT_TAGS[PRSkipped] = 'pr_skipped'


def to_json_line(event: Event) -> str:
    """Serialize an event to one compact JSON object (no trailing newline).

    Keys are ``schema_version``, ``event`` (the tag), then all of the event's own
    fields in declaration order.
    """
    payload: dict[str, object] = {
        'schema_version': SCHEMA_VERSION,
        'event': _EVENT_TAGS[type(event)],
    }
    payload.update(dataclasses.asdict(event))
    return json.dumps(payload, separators=(',', ':'))


def budget_is_nearing(cost_usd: float, cap_usd: float | None) -> bool:
    """Whether ``cost_usd`` has reached :data:`BUDGET_NEARING_FRACTION` of ``cap_usd``.

    The threshold itself counts as nearing: the point of the signal is to be heard before
    the busting turn, and a spawn sitting exactly on the line has already spent the part of
    the ceiling that was safe.

    A ``None`` or non-positive cap is no ceiling to near, so the answer is ``False`` rather
    than an error — an uncapped spawn is not close to a cap it does not have, and a
    telemetry helper is the wrong place to raise.
    """
    if cap_usd is None or cap_usd <= 0:
        return False
    return cost_usd >= cap_usd * BUDGET_NEARING_FRACTION


# ``apply_cost_fallback`` lived here. It substituted a token x local-price estimate when
# the provider reported ``0.0``, on the premise that subscription auth reports no cost.
# The premise is false: ``cost_estimated`` was true 0 times across 76 production spawns,
# 0 of 22 more on 2026-09-05, and a direct check against the installed CLI on a
# subscription seat returns a real ``total_cost_usd``. Keeping it meant maintaining a
# second unowned copy of the price list for a branch nothing takes. If a zero-cost
# provider ever reappears, the answer is ``cost_usd: null`` and a consumer that decides
# what to do, not a price table convoy has to keep in sync. (CONV-B29)
