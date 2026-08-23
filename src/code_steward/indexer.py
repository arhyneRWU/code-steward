from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterable
from pathlib import Path

from .gitmeta import file_last_commit
from .markers import ParsedMarkers, UnitAlias, parse_markers_text
from .models import CodeUnit, Endpoint

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
Declaration = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


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


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        _call_name(decorator).split(".")[-1] == "overload" for decorator in node.decorator_list
    )


# A property accessor shares its qualified name with the getter by
# design -- `@property def x` and `@x.setter def x` are the same
# attribute, not a redefinition. Without a suffix they collide, and
# the collision is fatal: it stops the whole index build. Django,
# Airflow, and Home Assistant each carry a few dozen of these, so the
# effect was that Code Steward could not index them at all.
ACCESSOR_SUFFIXES = ("setter", "deleter", "getter")


def _accessor_role(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Name the property accessor a decorator marks this as, if any.

    Matches `@<name>.setter` and its siblings, where `<name>` is the
    function's own name. That last condition matters: an unrelated
    decorator that happens to end in `.setter` is not an accessor for
    this function and must not be renamed as though it were.
    """
    for decorator in node.decorator_list:
        parts = _call_name(decorator).split(".")
        if len(parts) == 2 and parts[0] == node.name and parts[1] in ACCESSOR_SUFFIXES:
            return parts[1]
    return ""


def _hash_source(
    lines: list[str],
    start: int,
    end: int,
    ignored_lines: frozenset[int],
) -> str:
    selected = (
        line
        for lineno, line in enumerate(lines[start - 1 : end], start)
        if lineno not in ignored_lines
    )
    body = "\n".join(selected).replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(body).hexdigest()[:12]


def _module_key(rel_path: str) -> str:
    value = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    return value.replace("/", ".").replace("\\", ".")


DOC_TEXT_LIMIT = 4000


def _purpose(node: ast.AST, fallback: str) -> str:
    """Summarize a declaration from its docstring first line."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        doc = ast.get_docstring(node, clean=True)
        if doc:
            return doc.strip().splitlines()[0][:240]
    return fallback.replace("_", " ")


def _doc_text(node: ast.AST) -> str:
    """Return the whole docstring for retrieval scoring.

    ``purpose`` stays a short summary because it is emitted into
    reviewer packets. The body is indexed separately so a searcher's
    behavioural wording can match text that never reaches a packet.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        doc = ast.get_docstring(node, clean=True)
        if doc:
            return " ".join(doc.split())[:DOC_TEXT_LIMIT]
    return ""


def _concepts(*values: str) -> list[str]:
    concepts: set[str] = set()
    for value in values:
        if not value:
            continue
        concepts.add(value)
        concepts.update(token.lower() for token in re.split(r"[^A-Za-z0-9]+", value) if token)
    return sorted(concepts)


def _parameter_rows(args: ast.arguments) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(positional, defaults, strict=True):
        rows.append({"name": arg.arg, "type": _expr(arg.annotation), "default": _expr(default)})
    if args.vararg:
        rows.append(
            {"name": f"*{args.vararg.arg}", "type": _expr(args.vararg.annotation), "default": ""}
        )
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        rows.append({"name": arg.arg, "type": _expr(arg.annotation), "default": _expr(default)})
    if args.kwarg:
        rows.append(
            {"name": f"**{args.kwarg.arg}", "type": _expr(args.kwarg.annotation), "default": ""}
        )
    return rows


def _signature(
    name: str,
    args: ast.arguments,
    returns: ast.AST | None,
    is_async: bool = False,
) -> str:
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
        if (
            isinstance(child, ast.Call)
            and _call_name(child.func).split(".")[-1] == "Depends"
            and child.args
        ):
            deps.add(_expr(child.args[0]))
    return sorted(dep for dep in deps if dep)


def _route_info(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[str, str, str]]:
    routes: list[tuple[str, str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.lower()
        if method not in HTTP_METHODS:
            continue
        route = ""
        if (
            decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and isinstance(decorator.args[0].value, str)
        ):
            route = decorator.args[0].value
        response_model = ""
        for keyword in decorator.keywords:
            if keyword.arg == "response_model":
                response_model = _expr(keyword.value)
        routes.append((method.upper(), route, response_model))
    return routes


def _node_start_line(node: Declaration) -> int:
    decorator_lines = [decorator.lineno for decorator in node.decorator_list]
    return min([node.lineno, *decorator_lines])


def _line_indent(lines: list[str], lineno: int) -> str:
    line = lines[lineno - 1]
    return line[: len(line) - len(line.lstrip(" \t"))]


class UnitVisitor(ast.NodeVisitor):
    """Collect code units and endpoints from one module AST."""

    def __init__(
        self,
        rel_path: str,
        lines: list[str],
        git_commit: str,
        markers: ParsedMarkers,
    ):
        self.rel_path = rel_path
        self.lines = lines
        self.git_commit = git_commit
        self.module = _module_key(rel_path)
        self.stack: list[str] = []
        self.units: list[CodeUnit] = []
        self.endpoints: list[Endpoint] = []
        self._aliases_by_line: dict[int, UnitAlias] = {
            alias.line: alias for alias in markers.aliases
        }
        self._used_alias_lines: set[int] = set()
        self._unit_ids: set[str] = set()
        self._hash_ignored_lines = markers.control_lines

    def _qualname(self, name: str) -> str:
        return ".".join([*self.stack, name]) if self.stack else name

    def _unit_id(self, node: Declaration, qualname: str) -> tuple[str, bool]:
        """Return the unit ID and whether a tag supplied it."""
        start_line = _node_start_line(node)
        alias = self._aliases_by_line.get(start_line - 1)
        if alias is None:
            return f"{self.module}::{qualname}", False

        expected_indent = _line_indent(self.lines, start_line)
        if alias.indent != expected_indent:
            raise ValueError(
                f"Code Steward unit tag {alias.unit_id!r} at line {alias.line} "
                f"must use the declaration indentation"
            )
        self._used_alias_lines.add(alias.line)
        return alias.unit_id, True

    def _append_unit(self, unit: CodeUnit, *, tagged: bool = False) -> None:
        """Store a unit, disambiguating a generated ID that collides.

        Two collisions are not the same problem. A duplicated
        `# code-steward: unit <id>` tag is a mistake someone made and
        has to fix, so it still raises. A duplicated *generated* ID is
        the language behaving normally: sync and async variants of the
        same nested helper in exclusive branches, or two functions of
        the same name defined under `if TYPE_CHECKING`. Refusing to
        index a repository over that is the wrong trade -- Django hits
        it, and the whole build used to fail.

        The disambiguator is an ordinal rather than a line number.
        Line numbers move whenever anything above them changes; the
        ordinal only moves if the declarations themselves are
        reordered.
        """
        if unit.unit_id in self._unit_ids:
            if tagged:
                raise ValueError(f"Duplicate Code Steward unit ID: {unit.unit_id!r}")
            base = unit.unit_id
            ordinal = 2
            while f"{base}#{ordinal}" in self._unit_ids:
                ordinal += 1
            unit.unit_id = f"{base}#{ordinal}"
        self._unit_ids.add(unit.unit_id)
        self.units.append(unit)

    def _add_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = self._qualname(node.name)
        start_line = _node_start_line(node)
        unit_id, tagged = self._unit_id(node, qualname)
        # The getter keeps the plain ID so existing indexes and any
        # committed benchmark case that names one do not churn.
        role = "" if tagged else _accessor_role(node)
        if role:
            unit_id = f"{unit_id}@{role}"
        unit = CodeUnit(
            unit_id=unit_id,
            path=self.rel_path,
            kind="async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
            name=node.name,
            qualname=qualname,
            start_line=start_line,
            end_line=node.end_lineno or node.lineno,
            signature=_signature(
                node.name,
                node.args,
                node.returns,
                isinstance(node, ast.AsyncFunctionDef),
            ),
            parameters=_parameter_rows(node.args),
            returns=_expr(node.returns),
            purpose=_purpose(node, node.name),
            doc_text=_doc_text(node),
            concepts=_concepts(node.name, unit_id),
            decorators=[_expr(decorator) for decorator in node.decorator_list],
            dependencies=_dependencies(node),
            body_hash=_hash_source(
                self.lines,
                start_line,
                node.end_lineno or node.lineno,
                self._hash_ignored_lines,
            ),
            git_file_commit=self.git_commit,
        )
        self._append_unit(unit, tagged=tagged)
        unit_id = unit.unit_id
        # A decorator stack can name the same route twice -- a test
        # exercising two aliases of one handler, or a re-registration
        # under a second prefix. The storage layer treats
        # (unit, method, route) as unique, so a repeat used to abort
        # the build. It is the same endpoint; record it once.
        seen_routes: set[tuple[str, str]] = set()
        for method, route, response_model in _route_info(node):
            if (method, route) in seen_routes:
                continue
            seen_routes.add((method, route))
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
        if _is_overload(node):
            return
        self._add_function(node)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if _is_overload(node):
            return
        self._add_function(node)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualname = self._qualname(node.name)
        start_line = _node_start_line(node)
        unit_id, tagged = self._unit_id(node, qualname)
        bases = [_expr(base) for base in node.bases]
        self._append_unit(
            CodeUnit(
                unit_id=unit_id,
                path=self.rel_path,
                kind="class",
                name=node.name,
                qualname=qualname,
                start_line=start_line,
                end_line=node.end_lineno or node.lineno,
                signature=(
                    f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
                ),
                purpose=_purpose(node, node.name),
                doc_text=_doc_text(node),
                concepts=_concepts(node.name, unit_id),
                decorators=[_expr(decorator) for decorator in node.decorator_list],
                body_hash=_hash_source(
                    self.lines,
                    start_line,
                    node.end_lineno or node.lineno,
                    self._hash_ignored_lines,
                ),
                git_file_commit=self.git_commit,
            ),
            tagged=tagged,
        )
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def add_region(self, unit_id: str, start_line: int, end_line: int) -> None:
        """Record a tagged region spanning several declarations."""
        self._append_unit(
            CodeUnit(
                unit_id=unit_id,
                path=self.rel_path,
                kind="region",
                name=re.split(r"[.:/-]", unit_id)[-1],
                qualname=unit_id,
                start_line=start_line,
                end_line=end_line,
                purpose=" ".join(_concepts(unit_id)),
                concepts=_concepts(unit_id),
                body_hash=_hash_source(
                    self.lines,
                    start_line,
                    end_line,
                    self._hash_ignored_lines,
                ),
                git_file_commit=self.git_commit,
                explicit_region=True,
            ),
            # A region is always declared by a tag, so a duplicate is
            # always someone's mistake.
            tagged=True,
        )

    def validate_aliases(self) -> None:
        """Reject unit tags that precede no declaration."""
        unused = [
            alias
            for alias in self._aliases_by_line.values()
            if alias.line not in self._used_alias_lines
        ]
        if not unused:
            return
        alias = unused[0]
        raise ValueError(
            f"Code Steward unit tag {alias.unit_id!r} at line {alias.line} must "
            "immediately precede a function, async function, class, or its first decorator"
        )


def index_python_file(project_root: Path, path: Path) -> tuple[list[CodeUnit], list[Endpoint]]:
    """Extract code units and FastAPI endpoints from one file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    rel = path.resolve().relative_to(project_root.resolve()).as_posix()
    tree = ast.parse(text, filename=str(path))
    commit = file_last_commit(project_root, path)
    markers = parse_markers_text(text)

    visitor = UnitVisitor(rel, lines, commit, markers)
    visitor.visit(tree)
    visitor.validate_aliases()

    for region in markers.regions:
        visitor.add_region(region.unit_id, region.start_line, region.end_line)

    return visitor.units, visitor.endpoints


SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".code-steward",
        ".code-review-graph",
        # Agent tooling keeps git worktrees under .claude/worktrees,
        # which are copies of this repo and would duplicate every ID.
        ".claude",
    }
)


def is_excluded(project_root: Path, path: Path, excludes: Iterable[str] = ()) -> bool:
    """Report whether a path is outside the indexable source tree."""
    try:
        rel_parts = set(path.relative_to(project_root).parts)
    except ValueError:
        return True
    if rel_parts & SKIPPED_DIRECTORIES:
        return True
    return any(value in path.as_posix() for value in excludes)


def iter_python_files(project_root: Path, excludes: Iterable[str] = ()) -> Iterable[Path]:
    """Walk a project tree for indexable Python source files."""
    excluded = tuple(excludes)
    for path in project_root.rglob("*.py"):
        if is_excluded(project_root, path, excluded):
            continue
        yield path
