"""Tests for the external-write scanner: what a spawn wrote outside the workspace.

The scanner reads one spawn's stream-json text and reports the shell commands it issued
that write to a remote — a push, a PR, a write to a named GitHub repository. A run never
pushes, so whatever these record is outside what the run governs and outside what its gate
judged. The tests drive it through the stream shape the agent CLI emits: an ``assistant``
message carrying ``tool_use`` blocks, answered by a ``user`` message carrying the
``tool_result`` of the same id.
"""

import json

from convoy.core.external_writes import (
    COMMAND_MAX_CHARS,
    WRITE_VERBS,
    ExternalWrite,
    external_write_advisory,
    scan_external_writes,
)


def _use(tool_id: str, command: object, name: str = 'Bash') -> str:
    return json.dumps(
        {
            'type': 'assistant',
            'message': {
                'content': [
                    {'type': 'tool_use', 'id': tool_id, 'name': name, 'input': {'command': command}}
                ]
            },
        }
    )


def _result(tool_id: str, is_error: bool | None = False) -> str:
    block: dict[str, object] = {'type': 'tool_result', 'tool_use_id': tool_id, 'content': 'ok'}
    if is_error is not None:
        block['is_error'] = is_error
    return json.dumps({'type': 'user', 'message': {'content': [block]}})


def _stream(*lines: str) -> str:
    return '\n'.join(lines) + '\n'


def _one(command: str, name: str = 'Bash') -> tuple[ExternalWrite, ...]:
    return scan_external_writes(_stream(_use('t1', command, name), _result('t1')))


# --- each kind -----------------------------------------------------------------------------


def test_a_git_push_is_recorded_with_its_remote_and_refspec() -> None:
    assert _one('git push origin feat/x') == (
        ExternalWrite(
            kind='git_push', command='git push origin feat/x', target='origin feat/x', failed=False
        ),
    )


def test_a_push_from_another_directory_names_that_directory() -> None:
    (write,) = _one('git -C ../dep push origin b')
    assert write.kind == 'git_push'
    assert write.target == '../dep origin b'


def test_global_options_before_push_do_not_hide_it() -> None:
    (write,) = _one('git -c credential.helper= --no-pager push --force-with-lease -u origin HEAD')
    assert write.kind == 'git_push'
    assert write.target == 'origin HEAD'


def test_a_push_after_cd_is_its_own_simple_command() -> None:
    (write,) = _one('cd ../dep && git push')
    assert write.command == 'git push'
    assert write.target == ''


def test_gh_pr_create_names_the_repository_and_the_head() -> None:
    (write,) = _one('gh pr create -R other-owner/other-repo --head feat/x --fill')
    assert write.kind == 'gh_pr_create'
    assert write.target == 'other-owner/other-repo feat/x'


def test_gh_pr_create_without_a_repository_targets_the_current_one() -> None:
    (write,) = _one('gh pr create --title "Add the thing" --body "x"')
    assert write.kind == 'gh_pr_create'
    assert write.target == ''


def test_gh_pr_create_accepts_the_long_and_equals_forms() -> None:
    (write,) = _one('gh pr create --repo=o/r -H feat/y --fill')
    assert write.target == 'o/r feat/y'


def test_a_writing_gh_verb_against_a_named_repository_is_recorded() -> None:
    (write,) = _one('gh pr merge 12 -R o/r --squash')
    assert write.kind == 'gh_repo_write'
    assert write.target == 'o/r'


def test_every_documented_write_verb_is_recorded() -> None:
    for verb in sorted(WRITE_VERBS):
        (write,) = _one(f'gh issue {verb} 3 --repo o/r')
        assert write.kind == 'gh_repo_write', verb


# --- what is not recorded -------------------------------------------------------------------


def test_a_gh_read_against_a_named_repository_is_not_recorded() -> None:
    assert _one('gh pr view -R x') == ()
    assert _one('gh pr list --repo o/r --state open') == ()


def test_a_writing_gh_verb_without_a_repository_is_not_recorded() -> None:
    """Only ``pr create`` is recorded without ``-R``; the contract names the rest by repo."""
    assert _one('gh pr merge 12 --squash') == ()


def test_ordinary_git_commands_are_not_recorded() -> None:
    assert _one('git status') == ()
    assert _one('git commit -m "then git push"') == ()
    assert _one('git log --oneline -- push') == ()


def test_a_separator_inside_quotes_does_not_split_the_command() -> None:
    assert _one('git commit -m "wip; git push later" && echo "a | git push"') == ()


# --- shells and chains ---------------------------------------------------------------------


def test_a_push_inside_a_longer_chain_is_found_alone() -> None:
    (write,) = _one(
        'uv run pytest -q && git add -A && git commit -m "x" && git push -u origin HEAD | tee log'
    )
    assert write.command == 'git push -u origin HEAD'
    assert write.target == 'origin HEAD'


def test_every_shell_separator_splits() -> None:
    command = 'true; git push a\ngit push b || git push c && git push d | cat'
    writes = _one(command)
    assert [w.target for w in writes] == ['a', 'b', 'c', 'd']


def test_a_powershell_command_line_with_windows_paths() -> None:
    """Backslashes stay literal: a Windows path is a path, not a run of escapes."""
    (write,) = _one(
        r'Set-Location C:\work\dep; & git.exe -C "C:\work\dep" push origin feat/x',
        name='PowerShell',
    )
    assert write.kind == 'git_push'
    assert write.target == r'C:\work\dep origin feat/x'


def test_the_tool_name_is_not_what_is_keyed_on() -> None:
    (write,) = _one('git push', name='SomeFutureShell')
    assert write.kind == 'git_push'


def test_an_unbalanced_quote_does_not_crash_it() -> None:
    (write,) = _one('git push origin "feat/x')
    assert write.kind == 'git_push'


def test_a_subshell_is_seen_through() -> None:
    (write,) = _one('(cd ../dep && git push origin main)')
    assert write.command == 'git push origin main'


def test_an_environment_prefix_is_seen_through() -> None:
    (write,) = _one('GIT_SSH_COMMAND="ssh -i k" git push origin main')
    assert write.target == 'origin main'


# --- pairing with the tool result ----------------------------------------------------------


def test_failed_comes_from_the_paired_tool_result() -> None:
    stream = _stream(
        _use('a', 'git push origin one'),
        _use('b', 'git push origin two'),
        _use('c', 'git push origin three'),
        _result('b', is_error=None),
        _result('a', is_error=True),
    )

    writes = scan_external_writes(stream)

    assert [(w.target, w.failed) for w in writes] == [
        ('origin one', True),
        ('origin two', False),
        ('origin three', None),
    ]


def test_a_result_that_precedes_its_use_is_not_paired() -> None:
    stream = _stream(_result('a', is_error=True), _use('a', 'git push'))
    (write,) = scan_external_writes(stream)
    assert write.failed is None


def test_findings_come_back_in_stream_order() -> None:
    stream = _stream(
        _use('a', 'gh pr create -R o/r --fill'),
        _result('a'),
        _use('b', 'git push origin x'),
        _result('b'),
    )
    assert [w.kind for w in scan_external_writes(stream)] == ['gh_pr_create', 'git_push']


def test_several_tool_uses_in_one_message_are_all_read() -> None:
    message = {
        'type': 'assistant',
        'message': {
            'content': [
                {'type': 'text', 'text': 'pushing'},
                {'type': 'tool_use', 'id': 'a', 'name': 'Bash', 'input': {'command': 'git push'}},
                {
                    'type': 'tool_use',
                    'id': 'b',
                    'name': 'Bash',
                    'input': {'command': 'gh pr create'},
                },
            ]
        },
    }
    writes = scan_external_writes(json.dumps(message))
    assert [w.kind for w in writes] == ['git_push', 'gh_pr_create']


# --- defensive reading ---------------------------------------------------------------------


def test_malformed_lines_and_odd_shapes_are_tolerated() -> None:
    stream = _stream(
        'not json at all',
        '[1, 2, 3]',
        '{"type": "assistant", "message": "a string"}',
        '{"type": "assistant", "message": {"content": "plain text"}}',
        '{"type": "assistant", "message": {"content": [1, "x", null]}}',
        '{"type": "assistant", "message": {"content": [{"type": "tool_use", "input": "x"}]}}',
        _use('n', ['git', 'push']),
        '{"type": "user", "message": {"content": "a user string"}}',
        '{"type": "user", "message": {"content": [{"type": "tool_result"}]}}',
        '{"type": "assistant", "message": {"content": [{"type": "tool_use"',
        'stderr: something went wrong',
        _use('ok', 'git push origin main'),
        _result('ok'),
    )

    (write,) = scan_external_writes(stream)

    assert write.target == 'origin main'
    assert write.failed is False


def test_an_empty_stream_has_no_writes() -> None:
    assert scan_external_writes('') == ()


def test_a_long_command_is_cut() -> None:
    long_message = 'x' * 400
    (write,) = _one(f'git push origin main --push-option={long_message}')
    assert len(write.command) == COMMAND_MAX_CHARS == 300
    assert write.command.startswith('git push origin main --push-option=xxx')


def test_the_command_is_whitespace_collapsed() -> None:
    (write,) = _one('git    push\torigin   main')
    assert write.command == 'git push origin main'


# --- the advisory -------------------------------------------------------------------------


def test_the_advisory_names_the_pr_the_role_the_command_and_the_target() -> None:
    write = ExternalWrite(
        kind='git_push', command='git push origin feat/x', target='origin feat/x', failed=False
    )

    advisory = external_write_advisory('pr-1', 'implementation', write)

    assert advisory.kind == 'external_write'
    assert advisory.where == "[[prs]] 'pr-1' implementation"
    assert 'git push origin feat/x' in advisory.message
    assert 'origin feat/x' in advisory.message
    assert 'not gated by this run' in advisory.message
    assert '\n' not in advisory.message


def test_the_advisory_says_when_the_command_reported_an_error() -> None:
    write = ExternalWrite(kind='gh_pr_create', command='gh pr create', target='', failed=True)
    advisory = external_write_advisory('pr-2', 'fix', write)
    assert advisory.where == "[[prs]] 'pr-2' fix"
    assert 'error' in advisory.message


# --- comments, heredocs and here-strings ---------------------------------------------------


def test_an_apostrophe_in_a_comment_does_not_hide_a_later_push() -> None:
    (write,) = _one("# don't push from the wrong dir\ncd ../dep\ngit push origin feat/x")
    assert write.command == 'git push origin feat/x'


def test_a_trailing_comment_is_not_part_of_the_target() -> None:
    (write,) = _one("git push origin x # it's fine")
    assert write.command == 'git push origin x'
    assert write.target == 'origin x'


def test_a_hash_inside_a_word_is_not_a_comment() -> None:
    (write,) = _one('git push origin feat/x#2')
    assert write.target == 'origin feat/x#2'


def test_an_apostrophe_in_a_heredoc_body_does_not_hide_a_later_push() -> None:
    (write,) = _one("cat > NOTES.md <<'EOF'\nit's done\nEOF\ngit push origin feat/x")
    assert write.command == 'git push origin feat/x'


def test_a_heredoc_body_is_data_not_commands() -> None:
    assert (
        _one("cat > deploy.sh <<'EOF'\ngit push origin main\ngh pr create -R o/r --fill\nEOF") == ()
    )
    assert _one('cat <<EOF\ngit push\nEOF') == ()
    assert _one('cat <<-"END"\n\tgit push\n\tEND\necho done') == ()


def test_a_command_after_a_heredoc_on_its_own_line_is_scanned() -> None:
    (write,) = _one('git commit -F - <<EOF\nmsg; git push\nEOF\ngit push origin b')
    assert write.target == 'origin b'


def test_a_shift_in_arithmetic_is_not_a_heredoc() -> None:
    (write,) = _one('echo $((1<<2))\ngit push origin b')
    assert write.target == 'origin b'


def test_a_powershell_here_string_body_is_data_not_commands() -> None:
    command = "@'\nit's done; git push\n'@ | Set-Content notes.md\ngit push origin b"
    (write,) = _one(command, name='PowerShell')
    assert write.target == 'origin b'


def test_a_quote_that_never_closes_is_read_as_a_literal() -> None:
    (write,) = _one("echo it's\ngit push origin b")
    assert write.target == 'origin b'


def test_a_windows_path_ending_in_a_backslash_inside_quotes() -> None:
    (write,) = _one(r'cd "C:\dep\"; git push origin x', name='PowerShell')
    assert write.target == 'origin x'


def test_an_escaped_quote_inside_double_quotes_still_escapes() -> None:
    assert _one(r'git commit -m "say \"hi; git push\" now"') == ()


# --- compound statements -------------------------------------------------------------------


def test_a_push_inside_a_loop_is_found() -> None:
    writes = _one('for d in a b; do git -C $d push; done')
    assert [w.target for w in writes] == ['$d']


def test_a_push_inside_a_conditional_is_found() -> None:
    assert [w.kind for w in _one('if true; then git push; fi')] == ['git_push']
    assert [w.kind for w in _one('if git push; then echo ok; else git push -f; fi')] == [
        'git_push',
        'git_push',
    ]
    assert [w.kind for w in _one('! git push')] == ['git_push']
    assert [w.kind for w in _one('while false; do :; done; until git push; do sleep 1; done')] == [
        'git_push'
    ]


# --- redirections and background jobs -----------------------------------------------------


def test_redirections_are_not_part_of_the_target() -> None:
    (write,) = _one('git push origin feat/x 2>&1 | tail -5')
    assert write.target == 'origin feat/x'
    (write,) = _one('git push > out.txt')
    assert write.target == ''
    (write,) = _one('cd ../dep; git push origin feat/x 2>$null', name='PowerShell')
    assert write.target == 'origin feat/x'
    (write,) = _one('git push origin x >>log 2>>err &>all *>&1')
    assert write.target == 'origin x'


def test_a_background_ampersand_separates_commands() -> None:
    writes = _one('git push origin x & git push other y')
    assert [w.target for w in writes] == ['origin x', 'other y']


def test_the_powershell_call_operator_is_not_a_separator() -> None:
    (write,) = _one('& git push origin x', name='PowerShell')
    assert write.command == '& git push origin x'
    assert write.target == 'origin x'


def test_a_pipe_ampersand_still_splits() -> None:
    (write,) = _one('git push origin x |& tee log')
    assert write.target == 'origin x'
