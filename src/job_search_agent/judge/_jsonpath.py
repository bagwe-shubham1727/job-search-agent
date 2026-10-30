"""A tiny private JSONPath resolver for the judge validator.

Grammar (the same one the rule uses, PLAN §1.1 ``jsonpath.py``)::

    path    := "$" step*
    step    := "." key | "[" index "]"
    key     := [A-Za-z_][A-Za-z0-9_]*
    index   := "0" | [1-9][0-9]*

There are no wildcards, filters, slices, quoted keys or negative indices. This copy
lives inside ``judge/`` so the validator does not depend on WS1's module; any
resolver with the same ``resolve(path, document)`` contract can be injected instead
(``validator.PathResolver``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_STEP = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(0|[1-9][0-9]*)\]")

Step = str | int
"""A parsed step: a ``str`` object key or an ``int`` array index."""


class PathSyntaxError(ValueError):
    """The path string does not follow the grammar."""


class PathNotFoundError(LookupError):
    """The path is well formed but does not exist in the document."""


def parse_path(path: str) -> tuple[Step, ...]:
    """Parses a path into its steps.

    Args:
        path: For example ``"$.skills.backend[4]"``.

    Returns:
        The steps, e.g. ``("skills", "backend", 4)``; ``()`` for the root ``"$"``.

    Raises:
        PathSyntaxError: If ``path`` is not in the grammar.
    """
    if not isinstance(path, str) or not path.startswith("$"):
        raise PathSyntaxError("path must start with '$'")
    steps: list[Step] = []
    position = 1
    while position < len(path):
        match = _STEP.match(path, position)
        if match is None:
            raise PathSyntaxError(f"bad step at offset {position}")
        key, index = match.group(1), match.group(2)
        steps.append(key if key is not None else int(index))
        position = match.end()
    return tuple(steps)


def resolve(path: str, document: object) -> object:
    """Returns the value at ``path`` inside ``document``.

    Args:
        path: A path in the grammar above.
        document: A parsed JSON value (mappings, sequences, scalars).

    Returns:
        The value found. The root path returns ``document`` itself.

    Raises:
        PathSyntaxError: If the path is malformed.
        PathNotFoundError: If a key is missing, an index is out of range, or a step
            is applied to a value of the wrong kind.
    """
    current = document
    for step in parse_path(path):
        if isinstance(step, str):
            if not isinstance(current, Mapping) or step not in current:
                raise PathNotFoundError(path)
            current = current[step]
        else:
            if (
                isinstance(current, str | bytes)
                or not isinstance(current, Sequence)
                or step >= len(current)
            ):
                raise PathNotFoundError(path)
            current = current[step]
    return current
