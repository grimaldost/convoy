## What does this PR do?

<!-- One concern per PR. If the goal has "and" in it, split it. -->

## Checklist

- [ ] Gates pass locally, in order: `uv lock --check`, `uv sync`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run ty check src`, `uv run pytest`
- [ ] Behavior change carries tests (a bugfix leaves a regression test that fails without the fix)
- [ ] Docs that describe the changed behavior are updated in this PR (README / SKILL.md / docs/design/)
- [ ] `CHANGELOG.md` updated under `[Unreleased]`, or the exemption declared with a `Changelog: none (<reason>)` commit trailer; protocol additions marked **(consumer-affecting)**
- [ ] If this ships a backlog row: status flipped in `docs/backlog.md`
- [ ] If this resolves a design question: ADR added under `docs/adr/`
- [ ] No references to other tools/projects; no AI attribution anywhere
