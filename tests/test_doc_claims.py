"""The shipped documents agree with the shipped engine, on the claims that have drifted.

Deliberately narrow, and not a prose linter. It pins the small set of claims the repository
has actually got wrong — the MCP tool count and names, the CLI verb list, and the
`convoy_run` arguments — against the code that provides them, in the shape of
``test_versions_are_locked``.

The class earned a mechanism the third time it recurred. `SKILL.md` stated "there is no
resume" for three releases after `--resume` shipped and documented it 300 lines above; the
server docstring and the serving design both said "two tools" while three were registered;
`marketplace.json` advertised two for three releases; and `convoy clean` appeared zero
times in the manual, which cost two operators a hand-deleted branch that the engine already
deletes. Both earlier fixes for the class were prose — a PR-template line and an AGENTS.md
rule. AGENTS.md already carries the right rule ("if docs and code diverge, code wins"); what
was missing was something that fails.

What it does NOT do: read prose for meaning, count words, or check that a claim is well
phrased. It asks only whether each name the code publishes appears where the document
promises to list them, and whether a stated count matches the real one.
"""

import asyncio
import functools
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import convoy.interface.cli as cli
from convoy.interface.mcp.server import build_server

_ROOT = Path(__file__).resolve().parent.parent

# The number words a count claim is written with. Any of them followed by "tools" is a
# stated tool count, and exactly one of them is allowed to appear.
_COUNT_WORDS = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six'}


def _text(*parts: str) -> str:
    return (_ROOT.joinpath(*parts)).read_text(encoding='utf-8')


def _mcp_tool_names() -> set[str]:
    return {tool.name for tool in asyncio.run(build_server().list_tools())}


def _mcp_run_parameters() -> set[str]:
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    return set(tools['convoy_run'].input_schema['properties'])


def _cli_verbs() -> set[str]:
    """Every verb ``convoy <verb>`` accepts, from the registered typer commands."""
    return {
        (command.name or command.callback.__name__).replace('_', '-')
        for command in cli.app.registered_commands
        if command.callback is not None
    }


# Documents that promise to list every MCP tool: the shipped manual, the serving design,
# the marketplace entry an installer reads, the front page, and the server's own docstring.
_TOOL_LISTING_DOCS = (
    ('skills', 'convoy', 'SKILL.md'),
    ('docs', 'design', '03-serving.md'),
    ('.claude-plugin', 'marketplace.json'),
    ('README.md',),
    ('src', 'convoy', 'interface', 'mcp', 'server.py'),
)

# Documents that promise to list every CLI verb.
_VERB_LISTING_DOCS = (
    ('docs', 'design', '03-serving.md'),
    ('README.md',),
)


def test_the_names_being_pinned_are_actually_discovered() -> None:
    """Non-vacuity guard: every assertion below is empty-set-true if discovery breaks.

    A check that cannot fail is worse than no check, and this whole module is a set
    difference against two registries. If either stops answering — a typer internal moves,
    the MCP SDK renames ``list_tools`` — the assertions all pass while checking nothing.
    """
    assert _cli_verbs() >= {'run', 'validate', 'gate', 'clean', 'status', 'init'}
    assert _mcp_tool_names() == {'convoy_run', 'convoy_gate', 'convoy_init', 'convoy_status'}
    assert {'resume', 'detach'} <= _mcp_run_parameters()


@pytest.mark.parametrize('parts', _TOOL_LISTING_DOCS, ids=lambda parts: parts[-1])
def test_every_registered_mcp_tool_is_named_where_the_tools_are_listed(
    parts: tuple[str, ...],
) -> None:
    """`convoy_status` shipped unadvertised for three releases in exactly this way."""
    body = _text(*parts)
    missing = sorted(name for name in _mcp_tool_names() if name not in body)
    assert not missing, f'{parts[-1]} does not name {missing}'


@pytest.mark.parametrize('parts', _TOOL_LISTING_DOCS, ids=lambda parts: parts[-1])
def test_a_stated_tool_count_matches_the_registered_one(parts: tuple[str, ...]) -> None:
    """ "two tools" survived in two documents while three were registered."""
    body = _text(*parts)
    actual = len(_mcp_tool_names())
    wrong = [
        word
        for count, word in _COUNT_WORDS.items()
        if count != actual and re.search(rf'\b{word} tools\b', body)
    ]
    assert not wrong, f'{parts[-1]} states a tool count of {wrong} but {actual} are registered'


@pytest.mark.parametrize('parts', _VERB_LISTING_DOCS, ids=lambda parts: parts[-1])
def test_every_cli_verb_is_named_where_the_verbs_are_listed(parts: tuple[str, ...]) -> None:
    """`convoy clean` shipped in 0.4.0 and appeared zero times in the manual."""
    body = _text(*parts)
    missing = sorted(verb for verb in _cli_verbs() if f'convoy {verb}' not in body)
    assert not missing, f'{parts[-1]} does not name {missing}'


def test_the_manual_documents_every_convoy_run_argument() -> None:
    """`resume` and `detach` are the arguments a halted run's recovery depends on."""
    body = _text('skills', 'convoy', 'SKILL.md')
    missing = sorted(name for name in _mcp_run_parameters() if f'`{name}`' not in body)
    assert not missing, f'SKILL.md does not document {missing}'


def test_the_manual_names_the_recovery_verb() -> None:
    """The manual is where an operator meets a halt, and `clean` is what it needs then."""
    assert 'convoy clean' in _text('skills', 'convoy', 'SKILL.md')


def test_the_marketplace_entry_is_the_one_the_installer_reads() -> None:
    """The tool-name assertion above reads the whole file; this pins where it must appear."""
    marketplace = json.loads(_text('.claude-plugin', 'marketplace.json'))
    convoy = next(plugin for plugin in marketplace['plugins'] if plugin['name'] == 'convoy')
    missing = sorted(name for name in _mcp_tool_names() if name not in convoy['description'])
    assert not missing, f'the marketplace plugin description does not name {missing}'


# The gate a contributor reproduces is the pipeline railform runs for this repository's frame
# (railform.toml over the python-package preset), not a list in the workflow file: ci.yml only
# calls railform's reusable workflow at a pinned commit. So the expectation is read from the
# effective frame, `railform frame --json`, run at the commit ci.yml pins.
#
# The documents spell the commands the way a contributor types them: no `--frozen` (a CI
# flag) and `uv run pytest` for the test command (pytest's `-q` is in pyproject.toml).

_RAILFORM_REPOSITORY = 'git+https://github.com/grimaldost/railform'


def _railform_pin() -> str:
    """The railform commit ci.yml's `railform` job passes as `railform-sha`.

    Read from the workflow, the file `railform adopt --pin` rewrites, so the pin has no copy
    here that could lag behind it.
    """
    workflow = _text('.github', 'workflows', 'ci.yml')
    match = re.search(r'^\s*railform-sha: ([0-9a-f]{40})\s*$', workflow, re.M)
    assert match is not None, 'ci.yml passes no 40-hex `railform-sha` to the railform job'
    return match.group(1)


def _run_railform(*args: str, env: dict[str, str] | None = None) -> str:
    """Run ``railform <args>`` at the pinned commit, through an interpreter launch (never a
    console-script shim), and return its output without the closing verdict line.

    Needs the network the first time a commit is installed, like the CI jobs that do the same.
    """
    uv = shutil.which('uv')
    assert uv is not None, 'uv is not on PATH'
    done = subprocess.run(
        [
            uv,
            'run',
            '--no-project',
            '--with',
            f'{_RAILFORM_REPOSITORY}@{_railform_pin()}',
            'python',
            '-m',
            'railform',
            *args,
        ],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, f'railform {" ".join(args)} failed:\n{done.stdout}{done.stderr}'
    return '\n'.join(
        line for line in done.stdout.splitlines() if not line.startswith('railform-verdict:')
    )


@functools.cache
def _effective_frame() -> dict:
    return json.loads(_run_railform('frame', '--json'))


def _documented(command: str) -> str:
    """The form a contributor document spells a pipeline command in."""
    spelled = command.replace(' --frozen', '')
    return re.sub(r'\bpython -m pytest( -q)?$', 'pytest', spelled)


def _ci_gate_commands() -> list[str]:
    """Every command the CI pipeline runs for this repository, in its order, as documented.

    Built from the effective frame in the order of railform's python-package pipeline: the
    lock check, the sync, the extra installs, the format check, the lint, the type check and
    the test command. ``test_the_commands_read_from_the_frame_are_the_pipeline_ci_runs`` holds
    this list to the pipeline railform itself writes, so the two cannot part.
    """
    frame = _effective_frame()
    python = frame['python']
    installs = frame['ci']['setup']['extra_installs']
    lint = ' '.join(python['lint_paths'])
    commands = ['uv lock --check', ' '.join(['uv', 'sync', *python['sync_args']])]
    if installs:
        commands.append(' '.join(['uv', 'pip', 'install', *installs]))
    commands += [f'uv run ruff format --check {lint}', f'uv run ruff check {lint}']
    if python['type_check']:
        commands.append(f'uv run ty check {python["type_check"]}')
    commands += [_documented(line) for line in python['test_command'].splitlines() if line.strip()]
    return commands


def test_the_commands_read_from_the_frame_are_the_pipeline_ci_runs(tmp_path: Path) -> None:
    """The list above is a reading of the frame; this holds it to the pipeline itself.

    `railform frame --github-output` writes the `pipeline` output the reusable workflow's
    `checks` job runs line by line. Both are read at the commit ci.yml pins.
    """
    output = tmp_path / 'github-output'
    output.write_text('', encoding='utf-8')
    _run_railform('frame', '--github-output', env={**os.environ, 'GITHUB_OUTPUT': str(output)})
    text = output.read_text(encoding='utf-8')
    block = re.search(r'^pipeline<<(\S+)\n(.*?)\n\1$', text, re.M | re.S)
    assert block is not None, f'no multi-line `pipeline` output in {text!r}'
    pipeline = block.group(2).splitlines()
    assert [_documented(line) for line in pipeline] == _ci_gate_commands()


def _gate_block(body: str) -> str | None:
    """The document's fenced block that lists the gate, or ``None`` if no block lists it all.

    The block, not the whole document: `uv sync` appears in a setup section too, and a
    document-wide search would read that mention as the gate's first step and call the order
    wrong.
    """
    commands = _ci_gate_commands()
    for block in re.findall(r'^```[^\n]*\n(.*?)^```', body, re.M | re.S):
        if all(command in block for command in commands):
            return block
    return None


# Documents that promise to list the gate a contributor must pass. CONTRIBUTING said "the
# same set CI runs" while listing four of the six.
_GATE_LISTING_DOCS = (('CONTRIBUTING.md',), ('AGENTS.md',))

# Documents whose gate list must also keep the pipeline's order. AGENTS.md is left out until
# 2026-11-08 (§21 of the development-rails spec, railform adoption): Claude Code sessions load
# it, so it may not change before then, and it still lists `ruff check` before
# `ruff format --check` while the pipeline runs the format check first. Put it back in this
# tuple, with its commands reordered, in the change that edits AGENTS.md after that date.
_ORDERED_GATE_DOCS = (('CONTRIBUTING.md',),)


@pytest.mark.parametrize('parts', _GATE_LISTING_DOCS, ids=lambda parts: parts[-1])
def test_the_documented_gate_names_every_command_ci_runs(parts: tuple[str, ...]) -> None:
    """CONTRIBUTING listed four commands and said CI ran "the same set"; CI ran six.

    The missing one was `uv lock --check` — the step whose position the same document
    elsewhere calls load-bearing, and whose absence from a cut is why `uv.lock` recorded
    `convoy-engine 0.1.1` through the whole of `0.2.0`. A contributor working from that list
    runs everything except the one check that cannot repair what it measures.
    """
    body = _text(*parts)
    missing = [command for command in _ci_gate_commands() if command not in body]
    assert _gate_block(body) is not None, (
        f'{parts[-1]} has no fenced block listing every CI step; absent from the file: {missing}'
    )


@pytest.mark.parametrize('parts', _ORDERED_GATE_DOCS, ids=lambda parts: parts[-1])
def test_the_documented_gate_keeps_cis_order(parts: tuple[str, ...]) -> None:
    """`uv lock --check` before `uv sync` is the whole reason it can ever fail.

    Naming every command is not enough on its own: a list carrying `uv sync` first would
    satisfy the check above while documenting the one arrangement in which the lock check is
    guaranteed to pass.
    """
    block = _gate_block(_text(*parts))
    assert block is not None  # the check above owns this failure
    positions = [block.index(command) for command in _ci_gate_commands()]
    assert positions == sorted(positions), (
        f'{parts[-1]} lists the gate commands in a different order than the pipeline runs them'
    )


def test_the_ci_gate_is_not_empty() -> None:
    """Non-vacuity guard: an unread frame would make both checks above pass silently."""
    commands = _ci_gate_commands()
    assert len(commands) >= 4, commands
    assert 'uv lock --check' in commands
    assert commands.index('uv lock --check') < commands.index('uv sync')


# The commit-time lane (.pre-commit-config.yaml) mirrors the fast half of the gate. The
# mirror is the drift risk: CONTRIBUTING once said "the same set CI runs" over four of six
# commands, and a hook lane can rot the same way while looking armed.


def _commit_lane_commands() -> list[str]:
    """Every hook ``entry`` in .pre-commit-config.yaml that runs the project's tooling.

    Read from the config in file order, same line-regex approach as ``_ci_gate_commands``
    and for the same reason. The ``uv `` prefix is the boundary between the gate mirror
    (which must match CI) and the commit-message lane (subject shape, attribution ban —
    checks CI has no seat for).
    """
    config = _text('.pre-commit-config.yaml')
    entries = [match.group(1).strip() for match in re.finditer(r'^\s*entry: (.+)$', config, re.M)]
    return [entry for entry in entries if entry.startswith('uv ')]


def test_every_commit_lane_command_is_a_ci_gate_command() -> None:
    """The hook lane may only run what CI runs; a hook-only command would gate commits on
    something no PR is ever gated on, and a reworded one would drift from the gate silently."""
    unknown = [command for command in _commit_lane_commands() if command not in _ci_gate_commands()]
    assert not unknown, f'.pre-commit-config.yaml runs commands CI does not: {unknown}'


def test_the_commit_lane_keeps_cis_order() -> None:
    """`uv lock --check` before anything that would repair the lock — the pipeline's argument."""
    gate = _ci_gate_commands()
    positions = [gate.index(command) for command in _commit_lane_commands()]
    assert positions == sorted(positions), (
        '.pre-commit-config.yaml runs the gate commands in a different order than the pipeline'
    )


def test_the_commit_lane_is_not_empty() -> None:
    """Non-vacuity guard: an unparsed config would make both checks above pass silently."""
    commands = _commit_lane_commands()
    assert 'uv lock --check' in commands
    assert len(commands) >= 3, commands


def test_the_required_status_check_context_is_a_plain_job_named_gate() -> None:
    """The branch ruleset requires one context, `gate`, and only a plain job reports it.

    A matrix job reports one check per leg (`gate (ubuntu-latest)`), never the bare `gate`
    context; when the gate gained its second operating system the context stopped existing
    and the pull request that made the change sat unmergeable with all eight of its checks
    green. `railform adopt` now writes the `gate` job, after the `railform` job that calls
    the reusable workflow (whose matrix lives inside the called workflow and reports under
    that job's name). What is asserted here is the set of properties the ruleset silently
    depends on — the ruleset lives in repository settings and is invisible from the tree, so
    the next person to reshape this file has no way to know it is watching.
    """
    workflow = _text('.github', 'workflows', 'ci.yml')
    job = re.search(r'^  gate:\n(.*?)(?=^  \S|\Z)', workflow, re.M | re.S)
    assert job is not None, (
        'ci.yml declares no job named `gate`, so the required status check is never reported '
        'and every pull request blocks with its checks green'
    )
    body = job.group(1)
    assert 'strategy:' not in body and 'matrix:' not in body, (
        'the `gate` job is a matrix, so it reports `gate (<leg>)` per leg and never the bare '
        '`gate` context the ruleset requires'
    )
    needs = re.search(r'^    needs: \[?([^\n\]]+)\]?$', body, re.M)
    assert needs is not None and 'railform' in [n.strip() for n in needs.group(1).split(',')], (
        'the `gate` aggregate must depend on the `railform` job, or it reports success without '
        'the pipeline having run'
    )
    assert re.search(r'^    if: always\(\)$', body, re.M), (
        'without `if: always()` a red job leaves the aggregate SKIPPED, and a skipped '
        'required check never fails a pull request — it just never arrives'
    )


# A model id: a family name (`claude-haiku-5-5`, `claude-opus-5-5`) or a numbered id
# (`claude-3-5-sonnet`). `claude-plugin` and `claude -p` are not model ids.
_MODEL_ID = re.compile(r'claude-(?:haiku|sonnet|opus|\d|[a-z]+-\d)')


def test_the_skill_names_no_model_id() -> None:
    """The manual points at the resolution chain; it does not copy the lineup.

    ADR-0010: a model id written in prose goes stale between releases with nothing to say
    so. The skill named a Haiku id in three places after that model became a
    legacy one, which is the drift the ADR describes. The lineup lives in code
    (`DEFAULT_TIER_MODELS`, which raises a `lineup` advisory when a run resolves through it)
    and in the series file (`[governance.tier_models]`), and the skill says where to look.
    """
    found = _MODEL_ID.findall(_text('skills', 'convoy', 'SKILL.md'))
    assert found == [], (
        f'skills/convoy/SKILL.md names model ids {found}; say "an explicit `model`" or use '
        'a tier, and point at the resolution chain instead (ADR-0010)'
    )


# `[governance.budgets]` and `[governance.tools]` are keyed by the governance role
# (implementation / review / fix); "phase" is the `[[prs]].phase` grouping tag. These files
# say so. skills/convoy/SKILL.md and the plugin manifests join this list once the CONV-B75
# branch has landed.
_ROLE_TABLE_DOCS = ('README.md', 'docs/design/02-formats.md', 'docs/authoring-series.md')
_PER_PHASE = re.compile(r'(?i)per[- ]phase')
_ROLE_TABLE_WORDS = re.compile(r'(?i)budget|cap|ceiling|allow-list|tool')


@pytest.mark.parametrize('doc', _ROLE_TABLE_DOCS)
def test_the_role_tables_are_not_called_per_phase(doc: str) -> None:
    """The budget and tool tables are per role; "phase" is the grouping tag, a different thing."""
    offenders = [
        f'{doc}:{number}: {line.strip()}'
        for number, line in enumerate(_text(*doc.split('/')).splitlines(), start=1)
        if _PER_PHASE.search(line) and _ROLE_TABLE_WORDS.search(line)
    ]
    assert offenders == [], (
        'the budget and tool tables are keyed by the governance role (implementation / '
        'review / fix), not by phase; say "per role":\n' + '\n'.join(offenders)
    )


def test_the_convoy_gate_section_names_the_per_check_timeout_key() -> None:
    """An operator who reads ``timed out after`` in a result must find the key that bounds it."""
    body = _text('skills', 'convoy', 'SKILL.md')
    section = body.split('### `convoy_gate`', 1)[1].split('### `convoy_status`', 1)[0]
    assert '[governance] timeout_seconds' in section


def test_the_unreleased_changelog_states_what_trust_pins_in_a_linked_worktree() -> None:
    text = _text('CHANGELOG.md')
    unreleased = text.split('## [Unreleased]', 1)[1].split('\n## [', 1)[0]
    flat = ' '.join(unreleased.split())
    assert any('linked worktree' in s and 'judge.lock.' in s for s in flat.split('. '))
