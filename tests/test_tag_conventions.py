from __future__ import annotations

import ast
import io
import textwrap
import tokenize


def _source(value: str) -> str:
    return textwrap.dedent(value).lstrip()


def _comment_tokens(source: str) -> list[tokenize.TokenInfo]:
    return [
        token
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]


def _functions(source: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def test_unit_tag_does_not_change_function_documentation() -> None:
    source = _source(
        '''
        # code-steward: unit taxonomy.normalize
        def normalize(name: str) -> str:
            """Normalize a supplied name."""
            return name.strip()
        '''
    )

    function = _functions(source)[0]

    assert ast.get_docstring(function) == "Normalize a supplied name."
    assert [token.string for token in _comment_tokens(source)] == [
        "# code-steward: unit taxonomy.normalize"
    ]


def test_conceptual_region_comments_are_ast_neutral() -> None:
    source = _source(
        '''
        # code-steward: begin taxonomy.validation

        def normalize(name: str) -> str:
            """Normalize a supplied name."""
            return name.strip()

        # code-steward: end taxonomy.validation
        '''
    )
    without_tags = _source(
        '''
        def normalize(name: str) -> str:
            """Normalize a supplied name."""
            return name.strip()
        '''
    )

    assert ast.dump(ast.parse(source), include_attributes=False) == ast.dump(
        ast.parse(without_tags), include_attributes=False
    )


def test_function_alias_can_live_before_decorators() -> None:
    source = _source(
        '''
        # code-steward: unit api.organisms.create
        @router.post("/organisms")
        async def create_organism(name: str) -> str:
            """Create an organism."""
            return name
        '''
    )

    function = _functions(source)[0]

    assert function.lineno == 3
    assert function.decorator_list[0].lineno == 2
    assert ast.get_docstring(function) == "Create an organism."


def test_complete_ast_unit_starts_at_first_decorator() -> None:
    source = _source(
        '''
        @first
        @second("value")
        def decorated(value: str) -> str:
            """Return the supplied value."""
            return value
        '''
    )

    function = _functions(source)[0]
    decorator_lines = [decorator.lineno for decorator in function.decorator_list]

    assert min([function.lineno, *decorator_lines]) == 1
    assert function.lineno == 3


def test_indented_machine_tags_follow_python_scope_indentation() -> None:
    source = _source(
        '''
        class Normalizer:
            # code-steward: unit taxonomy.normalizer.normalize
            def normalize(self, name: str) -> str:
                """Normalize a supplied name."""
                return name.strip()
        '''
    )

    comments = _comment_tokens(source)

    assert [token.start[1] for token in comments] == [4]
    assert ast.get_docstring(_functions(source)[0]) == "Normalize a supplied name."


def test_comment_inside_function_does_not_replace_docstring() -> None:
    source = _source(
        '''
        def normalize(name: str) -> str:
            # A comment is ignored when Python determines the function docstring.
            """Normalize a supplied name."""
            return name.strip()
        '''
    )

    assert ast.get_docstring(_functions(source)[0]) == "Normalize a supplied name."
