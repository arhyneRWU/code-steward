from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Iterable

from .gitmeta import file_last_commit
from .markers import parse_regions_text
from .models import CodeUnit, Endpoint

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def _expr(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _call_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _hash_source(lines: list[str], start: int, end: int) -> str:
    body = "\n".join(lines[start - 1 : end]).replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(body).hexdigest()[:12]


def _module_key(rel_path: str) -> str:
    value = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    return value.replace("/", ".").replace("\\", ".")


def _purpose(node: ast.AST, fallback: str) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        doc = ast.get_docstring(node, clean=True)
        if doc:
            return doc.strip().splitlines()[0][:240]
    return fallback.replace("_", " ")


def _parameter_rows(args: ast.arguments) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(positional, defaults):
        rows.append({"name": arg.arg, "type": _expr(arg.annotation), "default": _expr(default)})
    if args.vararg:
        rows.append({"name": f"*{args.vararg.arg}", "type": _expr(args.vararg.annotation), "default": ""})
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        rows.append({"name": arg.arg, "type": _expr(arg.annotation), "default": _expr(default)})
    if args.kwarg:
        rows.append({"name": f"**{args.kwarg.arg}", "type": _expr(args.kwarg.annotation), "default": ""})
    return rows


def _signature(name: str, args: ast.arguments, returns: ast.AST | None, is_async: bool = False) -> str:
    parts: list[str] = []
    for row in _parameter_rows(args):
        value = row["name"]
        if row["type"]:
            value += f": {row['type']}"
        if row["default"]:
            value += f" = {row['default']}"
        parts.append(value)
    ret = f" -> {_expr(returns)}" if returns else ""
    prefix = "async " if is_async else ""
    return f"{prefix}{name}({', '.join(parts)}){ret}"


def _dependencies(node: ast.AST) -> list[str]:
    deps: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _call_name(child.func).split(".")[-1] == "Depends":
            if child.args:
                deps.add(_expr(child.args[0]))
    return sorted(dep for dep in deps if dep)


def _route_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str, str]]:
    routes: list[tuple[str, str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.lower()
        if method not in HTTP_METHODS:
            continue
        route = ""
        if decorator.args and isinstance(decorator.args[0], ast.Constant):
            if isinstance(decorator.args[0].value, str):
                route = decorator.args[0].value
        response_model = ""
        for keyword in decorator.keywords:
            if keyword.arg == "response_model":
                response_model = _expr(keyword.value)
        routes.append((method.upper(), route, response_model))
    return routes


class UnitVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, lines: list[str], git_commit: str):
        self.rel_path = rel_path
        self.lines = lines
        self.git_commit = git_commit
        self.module = _module_key(rel_path)
        self.stack: list[str] = []
        self.units: list[CodeUnit] = []
        self.endpoints: list[Endpoint] = []

    def _qualname(self, name: str) -> str:
        return ".".join([*self.stack, name]) if self.stack else name

    def _add_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = self._qualname(node.name)
        unit_id = f"{self.module}::{qualname}"
        unit = CodeUnit(
            unit_id=unit_id,
            path=self.rel_path,
            kind="async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
            name=node.name,
            qualname=qualname,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=_signature(node.name, node.args, node.returns, isinstance(node, ast.AsyncFunctionDef)),
            parameters=_parameter_rows(node.args),
            returns=_expr(node.returns),
            purpose=_purpose(node, node.name),
            concepts=sorted({node.name, *node.name.split("_")}),
            decorators=[_expr(decorator) for decorator in node.decorator_list],
            dependencies=_dependencies(node),
            body_hash=_hash_source(self.lines, node.lineno, node.end_lineno or node.lineno),
            git_file_commit=self.git_commit,
        )
        self.units.append(unit)
        for method, route, response_model in _route_info(node):
            self.endpoints.append(
                Endpoint(
                    unit_id=unit_id,
                    path=self.rel_path,
                    method=method,
                    route=route,
                    response_model=response_model,
                    dependencies=unit.dependencies,
                )
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add_function(node)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._add_function(node)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualname = self._qualname(node.name)
        bases = [_expr(base) for base in node.bases]
        self.units.append(
            CodeUnit(
                unit_id=f"{self.module}::{qualname}",
                path=self.rel_path,
                kind="class",
                name=node.name,
                qualname=qualname,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                signature=f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
                purpose=_purpose(node, node.name),
                concepts=sorted({node.name, *node.name.split("_")}),
                decorators=[_expr(decorator) for decorator in node.decorator_list],
                body_hash=_hash_source(self.lines, node.lineno, node.end_lineno or node.lineno),
                git_file_commit=self.git_commit,
            )
        )
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def index_python_file(project_root: Path, path: Path) -> tuple[list[CodeUnit], list[Endpoint]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    rel = path.resolve().relative_to(project_root.resolve()).as_posix()
    tree = ast.parse(text, filename=str(path))
    commit = file_last_commit(project_root, path)

    visitor = UnitVisitor(rel, lines, commit)
    visitor.visit(tree)

    for region in parse_regions_text(text):
        visitor.units.append(
            CodeUnit(
                unit_id=region.unit_id,
                path=rel,
                kind="region",
                name=region.unit_id.split(".")[-1],
                qualname=region.unit_id,
                start_line=region.start_line,
                end_line=region.end_line,
                purpose=region.first("purpose", region.unit_id.replace(".", " ")),
                concepts=region.csv("concepts"),
                owns=region.csv("owns"),
                not_owns=region.csv("not-own") + region.csv("not_own"),
                body_hash=_hash_source(lines, region.start_line, region.end_line),
                git_file_commit=commit,
                explicit_region=True,
            )
        )

    return visitor.units, visitor.endpoints


def iter_python_files(project_root: Path, excludes: Iterable[str] = ()) -> Iterable[Path]:
    excluded = set(excludes)
    for path in project_root.rglob("*.py"):
        rel_parts = set(path.relative_to(project_root).parts)
        if rel_parts & {".git", ".venv", "venv", "__pycache__", ".code-steward", ".code-review-graph"}:
            continue
        if any(value in path.as_posix() for value in excluded):
            continue
        yield path
