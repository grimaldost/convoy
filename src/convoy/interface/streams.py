"""Std-stream hardening for convoy's process entry points (shell).

Agent- and gate-produced text (check marks, emoji, box drawing) flows through
convoy's own narration and MCP responses. A redirected stream on Windows defaults
to cp1252, where writing that text raises ``UnicodeEncodeError`` — one stray
character kills a run that survived everything else. Entry points call
:func:`harden_std_streams` once, before any output.
"""

import sys


def harden_std_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8 with replacement, where supported.

    UTF-8 is what every consumer of convoy's streams expects (JSON-RPC over stdio
    is UTF-8, logs are read as UTF-8), and ``errors='replace'`` guarantees a write
    never raises for content reasons. A replaced stream without ``reconfigure``
    (StringIO under a capture harness, an exotic shim) is left alone.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            reconfigure(encoding='utf-8', errors='replace')
