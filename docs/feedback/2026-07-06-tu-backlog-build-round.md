# convoy feedback — backlog build round (T1, T8a, T3b, T2a+T2b)

- **Date:** 2026-07-06
- **Tool/version:** convoy 0.1.1 + Unreleased (`pyproject.toml`); worked at `main` `c9e3155` → PRs #11 (UTF-8 boundaries), #12 (repair_hint), #13 (truthful skip reason), #14 (seat probe + output_tail)
- **Context:** maintenance session — built the top of the 2026-07-06 triage backlog as four independent PRs, TDD throughout (every change red-green'd on this cp1252 Windows machine). The engine itself was not run (`convoy_run`/CLI untouched); this report covers the maintainability surface the build exercised.
- **Outcome:** all four items shipped from the triage rows alone; the codebase's own patterns made each build mechanical.

## Cost / economy

No engine runs this session (build-only; the per-run economy table does not apply).

## What worked (confirmed wins)

- **W-BB-1 — the triage→build pipeline held its bar.** All four backlog items were built PR-to-PR directly from `TRIAGE-2026-07-06.md` / the delta doc's promotion rows — verified seams, named homes — without re-reading any source feedback report. The "maintainer can pick the top item and build it without re-reading the reports" precision bar is not aspirational; it was exercised four times today.
- **W-BB-2 — house patterns paid for themselves.** `asset`'s optional-field pattern was cloned wholesale for `repair_hint` (dataclass default, `_optional_str`, omit-on-dump, hypothesis strategy); `GIT_HERMETIC_FLAGS`'s module-constant-with-rationale style hosted the new `TEXT_ENCODING`/`TEXT_ERRORS` decode policy; the `monkeypatch.setattr(run_service, 'run_series', ...)` seam extended naturally to `seat_problem`. Zero new test infrastructure was needed for four features.
- **W-BB-3 — the `_fix_brief` seam was exactly where the triage said it was.** `repair_hint` threading needed no new plumbing: the brief already iterates failing checks with the full `Check` in hand.

## Friction

- **[LOW] `SpawnResult.output` is combined stdout+stderr with no accessor for "the diagnostic part".** T2a wanted the failure text; the combined stream means an infra halt's tail can interleave NDJSON with the stderr message. Acceptable (the tail is for a human), but a future consumer wanting structured stderr would need the adapter to keep the streams apart.

## Misses

- **[MED] The seat-probe build leaked real spawns into the unit suite — and local green masked it (phase: the build's own verify step).** The five CLI `run` tests stub `run_series` but reach the new `seat_problem` through `run_series_headless`; on a machine with a live seat they silently ran five real `claude` spawns per suite pass, and on CI's claude-less runner they failed with a `kind: seat` problem (PR #14's red CI). The signal existed locally — the suite jumped 27s → 74s — and was misread as "more git fixtures". Fixed structurally in the same PR: a `tests/conftest.py` autouse guard makes the real probe unreachable from any test by default (a wiring test overrides it explicitly; the probe's own unit tests call the module function directly). Suite back to 28.8s — the runtime itself is the regression signal. Lesson: a suite-runtime delta is verification evidence, not noise.

## Vacuous gates

- none observed — the new PLW1514 lint gate was probe-verified to fire on a bare `read_text()` before being trusted (PR #11), precisely to avoid shipping a vacuous gate.

## Proposed promotions / changes

1. **[LOW]** The seat probe (PR #14) spends a few cents per run **unmetered** — it precedes the telemetry file, so campaign cost tables reconcile to convoy-metered totals minus probe costs. If a consumer ever needs to-the-cent truth, meter the probe (a `role: "preflight"` spawn line or a dedicated event — both consumer-affecting). Parked as a candidate; no consumer needs it today.
