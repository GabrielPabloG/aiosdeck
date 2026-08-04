"""Autocomplete engine — consumes the Command Registry, returns suggestions.

Shell completion scripts (bash, zsh, fish) delegate to this module via
`aios __complete <current_word> <previous_words...>`. The engine walks the
command tree from the registry and returns matching command names.
"""

from __future__ import annotations

from aios.cli.commands import COMMANDS, Command


def complete(tokens: list[str]) -> list[str]:
    """Return completion suggestions for the given token chain.

    tokens[0] is the current word being completed (possibly empty).
    tokens[1:] are the previous words already typed.
    """
    if not tokens:
        return []

    current = tokens[0]
    previous = tokens[1:]

    node: dict[str, Command] = COMMANDS
    if not previous:
        base = [name for name, cmd in node.items() if not cmd.hidden]
        return _matching(current, base)

    i = 0
    while i < len(previous):
        word = previous[i]
        cmd = node.get(word)
        if cmd is None:
            break
        if cmd.subcommands:
            node = cmd.subcommands
            i += 1
        else:
            break

    return _matching(current, list(node.keys()))


def _matching(prefix: str, options: list[str]) -> list[str]:
    if not prefix:
        return sorted(options)
    return sorted(o for o in options if o.startswith(prefix))
