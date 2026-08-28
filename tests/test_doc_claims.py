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
import json
import re
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
    return set(tools['convoy_run'].inputSchema['properties'])


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
    assert _cli_verbs() >= {'run', 'validate', 'clean', 'status', 'init'}
    assert _mcp_tool_names() == {'convoy_run', 'convoy_init', 'convoy_status'}
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


def _ci_gate_commands() -> list[str]:
    """Every command CI runs, in the order CI runs them.

    Read from the workflow rather than restated here, so the expectation cannot be the thing
    that goes stale. Parsed with a line regex instead of a YAML dependency: the file is one
    job of plain `- run:` steps, and a parser is not what this test is about.
    """
    workflow = _text('.github', 'workflows', 'ci.yml')
    return [match.group(1).strip() for match in re.finditer(r'^\s*- run: (.+)$', workflow, re.M)]


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


@pytest.mark.parametrize('parts', _GATE_LISTING_DOCS, ids=lambda parts: parts[-1])
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
        f'{parts[-1]} lists the gate commands in a different order than ci.yml runs them'
    )


def test_the_ci_gate_is_not_empty() -> None:
    """Non-vacuity guard: an unparsed workflow would make both checks above pass silently."""
    commands = _ci_gate_commands()
    assert len(commands) >= 4, commands
    assert 'uv lock --check' in commands
