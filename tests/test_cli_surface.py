"""The command surface, asserted rather than accumulated.

A tool is understood through `--help` before it is understood through
its documentation, and this one read as a search engine for longer
than it was one. Pinning the list makes adding or removing a command
a deliberate act with a diff, instead of something that happens.
"""

from __future__ import annotations

from code_steward.cli import build_parser

# Every command, and the one-line reason it exists. Changing this set
# is a product decision; update the list and say why in the commit.
EXPECTED = {
    "build",  # make the index
    "update",  # re-index one file
    "search",  # find a unit when you do not know its name
    "similar",  # compare code to code
    "check",  # compare what you changed to what exists
    "trace",  # the follower: a unit, its path, and the passes over it
    "read",  # extract one unit
    "endpoints",  # list the routes
    "map",  # a compact code map
}


def _commands() -> set[str]:
    parser = build_parser()
    for action in parser._subparsers._group_actions:
        if hasattr(action, "choices") and action.choices:
            return set(action.choices)
    raise AssertionError("no subcommands found")


def test_the_command_surface_is_what_we_intend():
    assert _commands() == EXPECTED


def test_packet_is_gone():
    """The reviewer packet was the pre-write ranking flow's output.

    That flow is retired: a reviewer handed a ranked packet took a
    wrong candidate on a third of clean cases, and attaching more
    evidence to it changed no verdicts (p = 0.549). `packet.py`
    stays, because the benchmarks that measured all of that still
    import it, but it is no longer something a user is offered.
    """
    assert "packet" not in _commands()
