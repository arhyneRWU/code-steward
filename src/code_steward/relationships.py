from __future__ import annotations

import ast
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from .db import all_units, replace_hard_relationships_for_provenance
from .models import CodeUnit, HardRelationship

PYTHON_AST_PROVENANCE = "python-ast"
_CALLER_KINDS = {"function", "async_function", "class"}


def _module_key(path: str) -> str:
    value = path[:-3] if path.endswith(".py") else path
    if value.endswith("/__init__"):
        value = value[: -len("/__init__")]
    return value.replace("/", ".").replace("\\", ".")


def _attribute_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [*_attribute_parts(node.value), node.attr]
    return []


def _expression(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _import_module(current_module: str, module: str | None, level: int) -> str:
    if level <= 0:
        return module or ""

    package = current_module.split(".")[:-1]
    keep = max(0, len(package) - (level - 1))
    parts = package[:keep]
    if module:
        parts.extend(module.split("."))
    return ".".join(parts)


def _import_aliases(
    tree: ast.Module,
    current_module: str,
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    module_aliases: dict[str, str] = {}
    symbol_aliases: dict[str, tuple[str, str]] = {}

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                module_aliases[bound] = alias.name if alias.asname else bound
            continue

        if isinstance(node, ast.ImportFrom):
            module = _import_module(current_module, node.module, node.level)
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                symbol_aliases[bound] = (module, alias.name)

    return module_aliases, symbol_aliases


def _top_level_symbols(units: list[CodeUnit]) -> dict[tuple[str, str], str]:
    symbols: dict[tuple[str, str], str] = {}
    for unit in units:
        if unit.kind not in _CALLER_KINDS or unit.qualname != unit.name:
            continue
        symbols[(_module_key(unit.path), unit.name)] = unit.unit_id
    return symbols


def _caller_for_line(units: list[CodeUnit], lineno: int) -> CodeUnit | None:
    candidates = [
        unit
        for unit in units
        if unit.kind in _CALLER_KINDS and unit.start_line <= lineno <= unit.end_line
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda unit: (unit.end_line - unit.start_line, unit.start_line, unit.unit_id),
    )


def _resolved_unit(
    func: ast.AST,
    current_module: str,
    top_level_symbols: dict[tuple[str, str], str],
    module_aliases: dict[str, str],
    symbol_aliases: dict[str, tuple[str, str]],
) -> tuple[str | None, str]:
    if isinstance(func, ast.Name):
        local = top_level_symbols.get((current_module, func.id))
        if local is not None:
            return local, "same-module"

        imported = symbol_aliases.get(func.id)
        if imported is not None:
            module, symbol = imported
            target = top_level_symbols.get((module, symbol))
            if target is not None:
                return target, "from-import"
        return None, "unresolved"

    parts = _attribute_parts(func)
    if len(parts) < 2:
        return None, "unresolved"

    first = parts[0]
    symbol = parts[-1]
    intermediate = parts[1:-1]

    module = ""
    resolution = "module-path"
    if first in module_aliases:
        module = ".".join([module_aliases[first], *intermediate])
        resolution = "module-import"
    elif first in symbol_aliases:
        base_module, imported_symbol = symbol_aliases[first]
        module = ".".join([base_module, imported_symbol, *intermediate])
        resolution = "from-import-module"
    else:
        module = ".".join(parts[:-1])

    target = top_level_symbols.get((module, symbol))
    if target is not None:
        return target, resolution
    return None, "unresolved"


def extract_python_call_relationships(
    project_root: Path,
    units: list[CodeUnit],
) -> tuple[dict[str, list[HardRelationship]], set[str]]:
    """Extract conservative Python call edges from indexed files."""
    units_by_path: dict[str, list[CodeUnit]] = defaultdict(list)
    for unit in units:
        units_by_path[unit.path].append(unit)

    top_level_symbols = _top_level_symbols(units)
    aggregated: dict[
        tuple[str, str, str],
        dict[str, Any],
    ] = {}
    parsed_sources: set[str] = set()

    for rel_path in sorted(units_by_path):
        path = project_root / rel_path
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        path_units = units_by_path[rel_path]
        parsed_sources.update(unit.unit_id for unit in path_units if unit.kind in _CALLER_KINDS)
        current_module = _module_key(rel_path)
        module_aliases, symbol_aliases = _import_aliases(tree, current_module)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            caller = _caller_for_line(path_units, node.lineno)
            if caller is None:
                continue

            expression = _expression(node.func)
            target_unit_id, resolution = _resolved_unit(
                node.func,
                current_module,
                top_level_symbols,
                module_aliases,
                symbol_aliases,
            )
            if target_unit_id is None:
                target_kind = "symbol"
                target_ref = expression or "<unknown>"
            else:
                target_kind = "unit"
                target_ref = target_unit_id

            key = (caller.unit_id, target_kind, target_ref)
            evidence = aggregated.setdefault(
                key,
                {
                    "path": rel_path,
                    "lines": set(),
                    "expressions": set(),
                    "resolutions": set(),
                },
            )
            evidence["lines"].add(node.lineno)
            evidence["expressions"].add(expression or "<unknown>")
            evidence["resolutions"].add(resolution)

    relationships: dict[str, list[HardRelationship]] = defaultdict(list)
    for (source_unit_id, target_kind, target_ref), evidence in sorted(aggregated.items()):
        relationships[source_unit_id].append(
            HardRelationship(
                source_unit_id=source_unit_id,
                relation="CALLS",
                target_kind=target_kind,
                target_ref=target_ref,
                provenance=PYTHON_AST_PROVENANCE,
                evidence={
                    "path": evidence["path"],
                    "lines": sorted(evidence["lines"]),
                    "expressions": sorted(evidence["expressions"]),
                    "resolutions": sorted(evidence["resolutions"]),
                },
            )
        )

    return dict(relationships), parsed_sources


def refresh_python_call_relationships(
    conn: sqlite3.Connection,
    project_root: Path,
) -> int:
    """Refresh Python AST call edges for parsable source files."""
    units = all_units(conn)
    relationships, parsed_sources = extract_python_call_relationships(
        project_root,
        units,
    )
    count = 0
    for source_unit_id in sorted(parsed_sources):
        edges = relationships.get(source_unit_id, [])
        replace_hard_relationships_for_provenance(
            conn,
            source_unit_id,
            PYTHON_AST_PROVENANCE,
            edges,
        )
        count += len(edges)
    return count
