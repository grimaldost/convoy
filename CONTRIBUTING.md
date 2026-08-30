# Contributing

convoy is developed largely by coding agents working under the playbook in
[AGENTS.md](AGENTS.md); humans follow the same rules. This file adds the
mechanics: setup, workflow, and the release discipline.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/):

```
uv sync
git config core.hooksPath scripts/git-hooks
```

The second line arms the commit-time lane: tracked hook scripts that run the
fast half of the gate (`uv lock --check`, both ruff checks) before each commit,
and check the message shape (conventional subject, no attribution trailers) at
commit time. The scripts go through `uv run python -m pre_commit`, never the
bare `pre-commit` shim — on a machine that blocks unmanaged executable shims,
the shim-installed form silently never runs (see `.pre-commit-config.yaml`).
Run the whole lane by hand with `uv run python -m pre_commit run --all-files`.

## Quality gates

Every one of these must pass locally before opening a PR. This is the same set CI
runs, **in this order**:

```
uv lock --check
uv sync
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check src
uv run pytest
```

The order is load-bearing at the top: `uv lock --check` reports a stale lockfile,
while `uv sync` — and every later `uv run` — silently repairs one, so running it
first is the only arrangement in which it can ever say no. Running the checks
without it is how a release shipped a lockfile pinning a version three releases
old.

The unit suite spends no money and spawns no real agent — if it suddenly takes
much longer than ~30 s, a real spawn has leaked past the `tests/conftest.py`
guard; treat the runtime jump as a failure.

## Workflow

Branch from `main` (`<type>/<short-slug>`, e.g. `fix/windows-locale-decode`)
and follow the process and git conventions in [AGENTS.md](AGENTS.md) — that is
the single statement of the PR discipline (one concern per PR, tests with
behavior changes, docs and CHANGELOG in the same change, the
**(consumer-affecting)** marker, ADR and backlog updates, conventional commit
subjects, no attribution trailers). The PR template carries the checklist; CI
runs the same gates as above.

The CHANGELOG half of that discipline is machine-enforced: the `changelog`
workflow fails a PR whose diff touches `src/` without touching `CHANGELOG.md`,
unless a commit in the range carries the trailer `Changelog: none (<reason>)`
— the opt-out for a change nothing a changelog reader could notice. It also
warns, without failing, when a contract-surface file changes and the entry
never says **(consumer-affecting)**; `scripts/changelog_gate.py` carries the
policy.

## Release discipline

Pre-1.0, changes accumulate under `[Unreleased]` and are cut into tagged
releases. **A shipped change is not done until a tagged release serves it** —
the plugin marketplace serves tags, so anything sitting in `[Unreleased]` is
invisible to every installed consumer, and production keeps re-discovering
already-fixed defects.

Cadence: cut a release after each backlog build round (a batch of
`docs/backlog.md` rows landing). To cut:

1. Move `[Unreleased]` into a new `## [0.x.y] - <date>` section in
   `CHANGELOG.md`.
2. Bump the version in all FOUR locations. Three are hand-edited —
   `pyproject.toml`, `.claude-plugin/plugin.json`, and `__version__` in
   `src/convoy/__init__.py` (`.claude-plugin/marketplace.json` carries no version
   field) — and `tests/test_manifest.py::test_versions_are_locked` asserts they
   agree, so a missed one fails the gate instead of shipping a split-brain version.
   The fourth is **`uv.lock`**, updated by running `uv sync` (or `uv lock`). It is
   named here because it was named nowhere: it recorded `convoy-engine 0.1.1`
   through the whole of `0.2.0`. No test can guard it — `uv run` re-locks before it
   runs pytest, so the file is repaired before a test could read it — which is why
   CI runs `uv lock --check` ahead of every step that would rewrite it.
3. Tag `v0.x.y` on the **release PR's merge commit**, never `main`'s tip (the tip
   may already carry post-release work) — annotated, so the tag records its own
   tagger and date: `git tag -a v0.x.y <release-merge-commit>` — and push the
   tag. Shape the message like the existing tags: `convoy 0.x.y`, a blank line, then what it serves and which
   parts are consumer-affecting.
4. Publish the GitHub release for that tag, with the version's `CHANGELOG.md`
   section as the body:
   `gh release create v0.x.y --verify-tag --title 'convoy 0.x.y' --notes-file <section>`.
   The tag is what the marketplace serves; the release is what the repository's own
   front page advertises, and it drifted independently — every version from `0.2.0`
   through `0.6.0` had a tag and no release, so the front page said `0.1.2` for six
   versions.

**Why the tag is the step that matters.** The marketplace serves tags, so an
untagged release is invisible to every installed consumer no matter how correct
the merge was. That is not hypothetical: `0.2.0` was bumped, changelogged and
merged while consumers went on being served `0.1.2` for ten days. The mechanized
half of this checklist held and the unmechanized half did not, which is why the
`release-tag` workflow now checks daily that `main`'s version has **both** a
matching tag and a published release — scheduled rather than push-triggered, since
both are created *after* the merge and a push gate would fail every release by
construction. It checks the two separately: a tag with no release page is exactly
the state five versions sat in, so one passing must not vouch for the other.

## The feedback loop

Dogfooding and consumer feedback reports land in `docs/feedback/` — deliberately
**local-only** (untracked; see the `.gitignore` there). Periodic triage passes
cluster the reports by cause, verify mechanisms against source, and promote what
clears the gate into the tracked [docs/backlog.md](docs/backlog.md) ledger. The
ledger is the canonical record: each row is written so a maintainer can build it
without the source reports. Decisions promoted along the way become ADRs or
guardrails, which are tracked.
