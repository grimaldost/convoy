"""What a spawn wrote outside the workspace — the external-write scanner (pure; no I/O).

A run integrates locally and never pushes, so a remote ref or a pull request a spawned agent
creates is outside what the run governs and outside what its gate judged. In one recorded
run an implementer opened a branch and a PR in a repository the workspace depends on, and
the orchestrator learned of it from a commit body. This module reads one spawn's own
stream-json text and reports the shell commands it issued that write to a remote, so the run
can record them and say so. It reports; it does not enforce — nothing here changes an
outcome.

What it reads: every ``tool_use`` block of an ``assistant`` message whose ``input.command``
is a string — which covers the Bash and PowerShell tools without keying on a tool name —
paired with the later ``tool_result`` block of the same id to learn whether it errored. What
it cannot see: a push made by a script the agent ran (``./release.sh``), by a tool with no
``command`` input, or by a process that outlived the spawn; and a typed write outside the
three patterns (``gh api -X POST ...``, a ``gh repo create`` naming its repository
positionally). The scan is a record of matching commands the agent typed, not of the
network.
"""

import json
import re
import shlex
from dataclasses import dataclass

from convoy.core.preflight import Advisory

# The kinds a finding can carry. A consumer branches on these, so they are a closed set.
GIT_PUSH = 'git_push'
GH_PR_CREATE = 'gh_pr_create'
GH_REPO_WRITE = 'gh_repo_write'

# The advisory kind a finding is reported under in the result envelope.
ADVISORY_KIND = 'external_write'

# The ``gh`` verbs that write. A ``gh`` command that names a repository with ``-R`` /
# ``--repo`` is recorded only when its verb is one of these, so ``gh pr view -R x`` — a
# read — is not. ``gh pr create`` is recorded with or without a repository, as its own kind.
WRITE_VERBS = frozenset(
    {
        'archive',
        'close',
        'comment',
        'create',
        'delete',
        'edit',
        'fork',
        'merge',
        'ready',
        'reopen',
        'review',
        'transfer',
        'upload',
    }
)

# The longest ``command`` a finding carries. Long enough for any push or ``gh`` call a
# reviewer needs to recognise; short enough that one runaway heredoc does not fill a line.
COMMAND_MAX_CHARS = 300
_ELLIPSIS = '...'

# git's global options that take their value as the next token (``-C <dir>``).
_GIT_VALUE_OPTIONS = frozenset(
    {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env'}
)
# ``git push`` options that take their value as the next token.
_PUSH_VALUE_OPTIONS = frozenset({'-o', '--push-option', '--receive-pack', '--exec'})
_GH_REPO_OPTIONS = frozenset({'-R', '--repo'})
_GH_HEAD_OPTIONS = frozenset({'-H', '--head'})

_ENV_ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
# Leading tokens that run the command after them rather than being it: PowerShell's call
# operator, the POSIX prefixes an agent puts in front of a command, and the shell keywords
# that open a compound statement's body (``for d in a b; do git -C $d push; done``).
_PREFIX_TOKENS = frozenset(
    {
        '!',
        '&',
        'command',
        'do',
        'elif',
        'else',
        'env',
        'exec',
        'if',
        'nohup',
        'then',
        'time',
        'until',
        'while',
    }
)
# A redirection token (``>``, ``2>&1``, ``>>log``, ``2>$null``, ``*>&1``): never a remote or a
# refspec. When nothing follows the operator, the next token is its operand.
_REDIRECTION = re.compile(r'^(?:\d+|&|\*)?(?:>>?|<)[&|]?(.*)$', re.DOTALL)
# The opening of a POSIX heredoc: ``<<EOF``, ``<<-EOF``, ``<< 'EOF'``, ``<<"EOF"``. A bare
# delimiter starts with a letter or underscore, so the shift in ``$((1<<2))`` is not one.
_HEREDOC = re.compile(r"""<<(-?)[ \t]*(?:'([^'\n]+)'|"([^"\n]+)"|([A-Za-z_][A-Za-z0-9_.-]*))""")
# The characters after which an unquoted ``#`` starts a comment (it must begin a word).
_COMMENT_AFTER = frozenset(' \t\r\n;|&(')
# The characters after which ``\"`` inside double quotes closes the quote rather than
# escaping it: a Windows path ending in a backslash (``"C:\dep\"``), which PowerShell, having
# no backslash escape, reads that way.
_CLOSES_AFTER_BACKSLASH = frozenset(' \t\r\n;|&)')

_PHRASES = {
    GIT_PUSH: 'pushes to a remote',
    GH_PR_CREATE: 'opens a pull request',
    GH_REPO_WRITE: 'writes to a GitHub repository',
}


@dataclass(frozen=True)
class ExternalWrite:
    """One command a spawn issued that writes outside the workspace.

    ``kind`` is one of ``git_push``, ``gh_pr_create``, ``gh_repo_write``. ``command`` is the
    simple command as issued, whitespace collapsed and cut to :data:`COMMAND_MAX_CHARS`.
    ``target`` is what it wrote to, as far as the command line says — for a push the ``-C``
    directory and then the remote (or ``--repo`` value) and refspec tokens, redirections
    left out, for ``gh`` the ``-R`` / ``--repo``
    value (plus ``--head`` on a PR) — and empty when the command names none (the current
    repository). ``failed`` is ``True`` when the paired tool result reported an error,
    ``False`` when it did not, and ``None`` when the stream carries no result for it.
    """

    kind: str
    command: str
    target: str
    failed: bool | None


def scan_external_writes(stream: str) -> tuple[ExternalWrite, ...]:
    """Every external write ``stream`` (one spawn's stream-json NDJSON) issued, in stream order.

    Defensive throughout: a line that is not JSON, a message whose content is not a list, a
    block that is not an object, a command that is not a string — each is skipped, never
    raised on. The spawn's stdout and stderr arrive concatenated, so non-JSON lines are
    expected.
    """
    found: list[tuple[str, ExternalWrite]] = []
    seen_ids: set[str] = set()
    errored: dict[str, bool] = {}
    for raw_line in stream.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        message = obj.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        kind = obj.get('type')
        for block in content:
            if not isinstance(block, dict):
                continue
            if kind == 'assistant' and block.get('type') == 'tool_use':
                tool_input = block.get('input')
                command = tool_input.get('command') if isinstance(tool_input, dict) else None
                if not isinstance(command, str):
                    continue
                tool_id = block.get('id')
                tool_id = tool_id if isinstance(tool_id, str) else ''
                if tool_id:
                    seen_ids.add(tool_id)
                found.extend((tool_id, write) for write in _writes_in(command))
            elif kind == 'user' and block.get('type') == 'tool_result':
                tool_id = block.get('tool_use_id')
                # Only a result that answers a use already seen pairs with it: the result is
                # the later of the two by construction, so an earlier one is not its answer.
                if isinstance(tool_id, str) and tool_id in seen_ids and tool_id not in errored:
                    errored[tool_id] = block.get('is_error') is True
    return tuple(
        ExternalWrite(
            kind=write.kind,
            command=write.command,
            target=write.target,
            failed=errored.get(tool_id) if tool_id else None,
        )
        for tool_id, write in found
    )


def external_write_advisory(pr_id: str, role: str, write: ExternalWrite) -> Advisory:
    """The one-line advisory a finding is reported under, on the envelope and on stderr.

    ``where`` names the PR and the spawn role, in the located shape the pre-flight advisories
    use (``[[prs]] 'pr-1'``), so a reader meets one shape for one idea.
    """
    phrase = _PHRASES.get(write.kind, 'writes outside the workspace')
    target = f' ({write.target})' if write.target else ''
    error = '; the command reported an error' if write.failed else ''
    return Advisory(
        kind=ADVISORY_KIND,
        where=f'[[prs]] {pr_id!r} {role}',
        message=f'`{write.command}` {phrase}{target}; it was not gated by this run{error}',
    )


def _writes_in(command: str) -> list[ExternalWrite]:
    """The external writes among ``command``'s simple commands (``failed`` left unknown)."""
    writes: list[ExternalWrite] = []
    for simple in _simple_commands(command):
        tokens = _without_redirections(_tokens(simple))
        while tokens and (_ENV_ASSIGNMENT.match(tokens[0]) or tokens[0] in _PREFIX_TOKENS):
            tokens = tokens[1:]
        if not tokens:
            continue
        program = _program(tokens[0])
        found = None
        if program == 'git':
            found = _git_push(tokens[1:])
        elif program == 'gh':
            found = _gh_write(tokens[1:])
        if found is not None:
            kind, target = found
            writes.append(
                ExternalWrite(kind=kind, command=_shown(simple), target=target, failed=None)
            )
    return writes


def _simple_commands(command: str) -> list[str]:
    """``command`` split on the shell separators (newline, ``;``, ``&&``, ``||``, ``|``, ``&``).

    Quote-aware, so a separator inside a quoted commit message does not split it. Inside
    double quotes a backslash escapes the next character, except that ``\\"`` followed by
    whitespace, a separator or the end closes the quote (a Windows path ending in a
    backslash); outside quotes a backslash is literal. A quote that never closes is read as
    a literal character, so a stray apostrophe does not swallow the rest of the command.

    What is data rather than commands is dropped: an unquoted ``#`` that begins a word runs
    to the end of its line, and a heredoc body (``<<EOF`` to the line ``EOF``) and a
    PowerShell here-string body (``@'`` to a line starting ``'@``) are skipped. A lone ``&``
    separates (a background job) except at the start of a command, where it is PowerShell's
    call operator, and inside a redirection (``2>&1``). Leading ``(`` / ``{`` and trailing
    ``)`` / ``}`` are stripped, so a subshell's commands are seen.
    """
    literal: set[int] = set()
    while True:
        parts, unclosed = _split(command, literal)
        if unclosed is None:
            stripped = (part.strip().lstrip('({').rstrip(')}').strip() for part in parts)
            return [part for part in stripped if part]
        literal.add(unclosed)


def _split(command: str, literal: set[int]) -> tuple[list[str], int | None]:
    """One splitting pass: the parts, and where a quote opened that never closed (or ``None``).

    A quote character at a position in ``literal`` is read as an ordinary character.
    """
    parts: list[str] = []
    current: list[str] = []
    heredocs: list[tuple[str, bool]] = []
    quote = ''
    opened = 0
    size = len(command)
    i = 0
    while i < size:
        char = command[i]
        if quote:
            current.append(char)
            if char == quote:
                quote = ''
            elif char == '\\' and quote == '"' and i + 1 < size:
                after = command[i + 2] if i + 2 < size else '\n'
                if command[i + 1] != '"' or after not in _CLOSES_AFTER_BACKSLASH:
                    current.append(command[i + 1])
                    i += 1
            i += 1
            continue
        here_end = _here_string_end(command, i) if char == '@' else None
        if here_end is not None:
            current.append(command[i:here_end])
            i = here_end
        elif char in '\'"' and i not in literal:
            quote, opened = char, i
            current.append(char)
            i += 1
        elif char == '#' and (i == 0 or command[i - 1] in _COMMENT_AFTER):
            newline = command.find('\n', i)
            i = size if newline == -1 else newline
        elif command.startswith('<<<', i):
            current.append('<<<')
            i += 3
        elif char == '<' and (match := _HEREDOC.match(command, i)):
            heredocs.append((match.group(2) or match.group(3) or match.group(4), match[1] == '-'))
            current.append(match.group(0))
            i = match.end()
        elif char == '\n':
            parts.append(''.join(current))
            current = []
            i = _after_heredocs(command, i + 1, heredocs)
            heredocs = []
        elif char == ';' or command[i : i + 2] in ('&&', '||'):
            parts.append(''.join(current))
            current = []
            i += 1 if char == ';' else 2
        elif char == '|' or (char == '&' and _separates(command, i, current)):
            parts.append(''.join(current))
            current = []
            i += 1
        else:
            current.append(char)
            i += 1
    if quote:
        return parts, opened
    parts.append(''.join(current))
    return parts, None


def _separates(command: str, i: int, current: list[str]) -> bool:
    """Whether the lone ``&`` at ``i`` ends a command (a background job)."""
    if command[i + 1 : i + 2] == '>' or (i > 0 and command[i - 1] in '<>'):
        return False  # a redirection: ``&>file``, ``2>&1``, ``<&3``
    return bool(''.join(current).strip())  # at a command's start it is the call operator


def _after_heredocs(command: str, i: int, heredocs: list[tuple[str, bool]]) -> int:
    """The index after the bodies of ``heredocs``, which start at ``i``, each to its delimiter.

    ``heredocs`` holds ``(delimiter, strip_tabs)`` pairs in the order they opened. A body
    whose delimiter never comes runs to the end, as in a POSIX shell.
    """
    for delimiter, strip_tabs in heredocs:
        while i < len(command):
            newline = command.find('\n', i)
            end = len(command) if newline == -1 else newline
            line = command[i:end].rstrip('\r')
            i = end + 1
            if (line.lstrip('\t') if strip_tabs else line) == delimiter:
                break
    return min(i, len(command))


def _here_string_end(command: str, i: int) -> int | None:
    """The index after the PowerShell here-string opening at ``i``, or ``None`` if none opens.

    A here-string opens with ``@'`` or ``@"`` at the end of a line and closes at a line
    starting ``'@`` or ``"@``; what is between is data. One that never closes runs to the end.
    """
    quote = command[i + 1 : i + 2]
    if quote not in ('"', "'"):
        return None
    body = i + 2
    if command.startswith('\r\n', body):
        body += 1
    if not command.startswith('\n', body):
        return None
    close = command.find(f'\n{quote}@', body)
    return len(command) if close == -1 else close + 3


def _without_redirections(tokens: list[str]) -> list[str]:
    """``tokens`` without redirection operators and their operands."""
    kept: list[str] = []
    operand_next = False
    for token in tokens:
        if operand_next:
            operand_next = False
        elif match := _REDIRECTION.match(token):
            operand_next = not match.group(1)
        else:
            kept.append(token)
    return kept


def _tokens(simple: str) -> list[str]:
    """``simple``'s words: ``shlex`` in POSIX mode, falling back to whitespace splitting.

    Backslash is not an escape character here: a Windows path (``C:\\work\\dep``) is a path,
    and PowerShell's escape is the backtick anyway. An unbalanced quote falls back to a plain
    split rather than raising.
    """
    lexer = shlex.shlex(simple, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ''
    lexer.commenters = ''
    try:
        return list(lexer)
    except ValueError:
        return simple.split()


def _program(token: str) -> str:
    """The program a command token names: its base name, lower-cased, without ``.exe``."""
    name = token.replace('\\', '/').rsplit('/', 1)[-1].lower()
    return name.removesuffix('.exe')


def _git_push(args: list[str]) -> tuple[str, str] | None:
    """``(kind, target)`` when ``git <args>`` is a push, else ``None``."""
    directories: list[str] = []
    i = 0
    while i < len(args) and args[i].startswith('-'):
        option = args[i]
        if option in _GIT_VALUE_OPTIONS:
            if option == '-C' and i + 1 < len(args):
                directories.append(args[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(args) or args[i] != 'push':
        return None
    positional: list[str] = []
    rest = args[i + 1 :]
    j = 0
    while j < len(rest):
        token = rest[j]
        if token == '--repo' and j + 1 < len(rest):
            positional.append(rest[j + 1])
            j += 2
        elif token.startswith('--repo='):
            positional.append(token.split('=', 1)[1])
            j += 1
        elif token in _PUSH_VALUE_OPTIONS:
            j += 2
        elif token.startswith('-'):
            j += 1
        else:
            positional.append(token)
            j += 1
    return GIT_PUSH, ' '.join([*directories, *positional])


def _gh_write(args: list[str]) -> tuple[str, str] | None:
    """``(kind, target)`` when ``gh <args>`` writes per the documented contract, else ``None``."""
    repo = ''
    head = ''
    words: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        option, has_value, value = token.partition('=')
        if option in _GH_REPO_OPTIONS or option in _GH_HEAD_OPTIONS:
            if not has_value:
                value = args[i + 1] if i + 1 < len(args) else ''
                i += 1
            if option in _GH_REPO_OPTIONS:
                repo = value
            else:
                head = value
        elif not token.startswith('-'):
            words.append(token)
        i += 1
    noun, verb = (words + ['', ''])[:2]
    if noun == 'pr' and verb == 'create':
        return GH_PR_CREATE, ' '.join(part for part in (repo, head) if part)
    if repo and verb in WRITE_VERBS:
        return GH_REPO_WRITE, repo
    return None


def _shown(simple: str) -> str:
    """``simple`` with its whitespace collapsed, cut to :data:`COMMAND_MAX_CHARS`."""
    text = ' '.join(simple.split())
    if len(text) > COMMAND_MAX_CHARS:
        text = text[: COMMAND_MAX_CHARS - len(_ELLIPSIS)] + _ELLIPSIS
    return text
