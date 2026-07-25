"""``python -m convoy`` — the same entry point as the ``convoy`` console script.

Named explicitly so a caller that knows the interpreter but not the console script's
install location can still invoke the CLI: ``sys.executable -m convoy`` resolves through
the installed package rather than through ``PATH``, which the MCP server cannot assume
anything about when it launches a detached run.
"""

from convoy.interface.cli import main

if __name__ == '__main__':
    main()
