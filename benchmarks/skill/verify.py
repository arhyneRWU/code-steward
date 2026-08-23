"""Adjudicate answers the graph's key does not contain.

The answer key is built from resolved `CALLS` edges, and resolution
reaches 22.5% of edges on Django. Validated against an independent
AST scan on six `impact` questions, the key was a **strict subset**
of the callers that genuinely exist every time -- precise, and
incomplete.

That breaks naive precision. An arm that names a real caller the
graph missed is right, and scoring it as a false positive measures
the index rather than the agent. The first run of this experiment
had exactly that flaw.

So a claim outside the key is not counted wrong until it has been
checked against the source. The check is deliberately simple and
conservative: parse the claimed unit and look for a call whose callee
name matches the target's name. It can be fooled by a name collision
-- two different `create` methods -- so it **confirms** a claim
rather than refuting one, and an unconfirmable claim is reported as
unverified rather than as an error.
"""

from __future__ import annotations

import ast
from pathlib import Path

from code_steward.models import CodeUnit


def _callee_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def confirms_call(root: Path, caller: CodeUnit, target_name: str) -> bool:
    """Say whether ``caller``'s source really calls ``target_name``."""
    try:
        source = (root / caller.path).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.lineno != caller.start_line and not (
            caller.start_line <= node.lineno <= caller.end_line
        ):
            continue
        if target_name in _callee_names(node):
            return True
    return False


def adjudicate(
    root: Path,
    units: dict[str, CodeUnit],
    target: str,
    extras: list[str],
) -> tuple[list[str], list[str]]:
    """Split claims outside the key into confirmed and unverified."""
    target_name = target.split("::")[-1].split(".")[-1]
    confirmed: list[str] = []
    unverified: list[str] = []
    for unit_id in extras:
        unit = units.get(unit_id)
        if unit is not None and confirms_call(root, unit, target_name):
            confirmed.append(unit_id)
        else:
            unverified.append(unit_id)
    return sorted(confirmed), sorted(unverified)
