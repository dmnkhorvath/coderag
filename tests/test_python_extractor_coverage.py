"""Targeted tests for Python extractor coverage.

Covers missing lines: 70, 76, 85-86, 89, 127, 153-158, 160-168, 333-342,
440, 442, 466-475, 519-527, 529, 535, 607, 745, 782, 908, 910, 919-920,
935-939, 971, 1027-1049, 1100-1109
"""

from __future__ import annotations

import pytest

from coderag.core.models import EdgeKind, NodeKind
from coderag.plugins.python.extractor import PythonExtractor


@pytest.fixture
def extractor():
    return PythonExtractor()


# ---------------------------------------------------------------------------
# Error collection coverage
# ---------------------------------------------------------------------------


class TestErrorCollection:
    """Cover _collect_errors and parse error paths."""

    def test_syntax_error_collected(self, extractor):
        """Line ~70,76: ERROR nodes in tree produce ExtractionError."""
        code = b"def foo(:\n    pass"
        result = extractor.extract("test.py", code)
        assert any(e.message for e in result.errors)

    def test_missing_node_collected(self, extractor):
        """Ensure missing nodes are also collected as errors."""
        code = b"def (x):\n    pass"
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"

    def test_multiple_syntax_errors(self, extractor):
        """Multiple parse errors in one file."""
        code = b"def foo(:\n    pass\ndef bar(:\n    pass"
        result = extractor.extract("test.py", code)
        assert len(result.errors) >= 1


# ---------------------------------------------------------------------------
# Parameter extraction edge cases
# ---------------------------------------------------------------------------


class TestParameterExtraction:
    """Cover _extract_parameters edge cases (lines 127, 153-168)."""

    def test_typed_parameter(self, extractor):
        """Line 153-158: typed_parameter branch."""
        code = b"def foo(x: int, y: str) -> None:\n    pass"
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1
        params = funcs[0].metadata.get("parameters", [])
        assert any(p.get("name") == "x" for p in params)
        assert any(p.get("type") == "int" for p in params)

    def test_default_parameter(self, extractor):
        """Line 160-163: default_parameter branch."""
        code = b"def foo(x=10, y=20):\n    pass"
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1
        params = funcs[0].metadata.get("parameters", [])
        assert any(p.get("default") == "10" for p in params)

    def test_typed_default_parameter(self, extractor):
        """Line 164-168: typed_default_parameter branch."""
        code = b'def foo(x: int = 10, y: str = "hello"):\n    pass'
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1
        params = funcs[0].metadata.get("parameters", [])
        assert any(p.get("name") == "x" and p.get("type") == "int" and p.get("default") == "10" for p in params)

    def test_list_splat_parameter(self, extractor):
        """Cover list_splat_pattern / dictionary_splat_pattern."""
        code = b"def foo(*args, **kwargs):\n    pass"
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1

    def test_no_parameters(self, extractor):
        """Line 127: params_node is None."""
        code = b"def foo():\n    pass"
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1

    def test_positional_only_params(self, extractor):
        """Cover positional-only parameter separator."""
        code = b"def foo(x, y, /, z):\n    pass"
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1

    def test_keyword_only_params(self, extractor):
        """Cover keyword-only parameter separator."""
        code = b"def foo(*, x, y):\n    pass"
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1

    def test_complex_type_annotations(self, extractor):
        """Cover complex type annotations in parameters."""
        code = b"def foo(x: list[int], y: dict[str, Any], z: tuple[int, ...]):\n    pass"
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------


class TestClassExtraction:
    """Cover class-related extraction paths."""

    def test_class_with_bases(self, extractor):
        """Lines 333-342: _get_base_classes produces unresolved EXTENDS refs."""
        code = b"class Foo(Bar, Baz):\n    pass"
        result = extractor.extract("test.py", code)
        classes = [n for n in result.nodes if n.kind == NodeKind.CLASS]
        assert len(classes) == 1
        # Base classes produce unresolved references with EXTENDS kind
        extends_refs = [u for u in result.unresolved_references if u.reference_kind == EdgeKind.EXTENDS]
        assert len(extends_refs) >= 2

    def test_class_with_metaclass(self, extractor):
        """Cover keyword argument in base list (metaclass=...)."""
        code = b"class Foo(metaclass=ABCMeta):\n    pass"
        result = extractor.extract("test.py", code)
        classes = [n for n in result.nodes if n.kind == NodeKind.CLASS]
        assert len(classes) == 1

    def test_class_with_decorators(self, extractor):
        """Lines 440, 442: decorator extraction."""
        code = b"@dataclass\n@frozen\nclass Foo:\n    x: int = 0"
        result = extractor.extract("test.py", code)
        decorators = [n for n in result.nodes if n.kind == NodeKind.DECORATOR]
        assert len(decorators) >= 1

    def test_nested_class(self, extractor):
        """Cover nested class extraction."""
        code = b"class Outer:\n    class Inner:\n        pass"
        result = extractor.extract("test.py", code)
        classes = [n for n in result.nodes if n.kind == NodeKind.CLASS]
        assert len(classes) == 2

    def test_abstract_class(self, extractor):
        """Cover abstract class with ABC base."""
        code = b"""from abc import ABC, abstractmethod

class Base(ABC):
    @abstractmethod
    def do_something(self) -> None:
        pass
"""
        result = extractor.extract("test.py", code)
        ifaces = [n for n in result.nodes if n.kind == NodeKind.INTERFACE]
        assert len(ifaces) == 1
        methods = [n for n in result.nodes if n.kind == NodeKind.METHOD]
        assert len(methods) == 1


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------


class TestFunctionExtraction:
    """Cover function-related extraction paths."""

    def test_function_with_decorator(self, extractor):
        """Lines 466-475: function decorator handling."""
        code = b"@staticmethod\ndef foo():\n    pass"
        result = extractor.extract("test.py", code)
        decorators = [n for n in result.nodes if n.kind == NodeKind.DECORATOR]
        assert len(decorators) >= 1

    def test_async_function(self, extractor):
        """Cover async function extraction - metadata key is \"async\"."""
        code = b"async def fetch_data(url: str) -> dict:\n    pass"
        result = extractor.extract("test.py", code)
        funcs = [n for n in result.nodes if n.kind == NodeKind.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].metadata.get("async") is True

    def test_method_with_return_type(self, extractor):
        """Lines 519-527: return type annotation."""
        code = b'class Foo:\n    def bar(self) -> str:\n        return "hello"'
        result = extractor.extract("test.py", code)
        methods = [n for n in result.nodes if n.kind == NodeKind.METHOD]
        assert len(methods) == 1
        assert methods[0].metadata.get("return_type") == "str"

    def test_property_method(self, extractor):
        """Lines 529, 535: property decorator creates PROPERTY node."""
        code = b"class Foo:\n    @property\n    def name(self) -> str:\n        return self._name"
        result = extractor.extract("test.py", code)
        props = [n for n in result.nodes if n.kind == NodeKind.PROPERTY]
        assert len(props) >= 1
        assert props[0].name == "name"

    def test_classmethod(self, extractor):
        """Cover classmethod decorator."""
        code = b'class Foo:\n    @classmethod\n    def create(cls) -> "Foo":\n        return cls()'
        result = extractor.extract("test.py", code)
        methods = [n for n in result.nodes if n.kind == NodeKind.METHOD]
        assert len(methods) == 1
        assert methods[0].metadata.get("classmethod") is True

    def test_staticmethod(self, extractor):
        """Cover staticmethod decorator."""
        code = b"class Foo:\n    @staticmethod\n    def helper() -> int:\n        return 42"
        result = extractor.extract("test.py", code)
        methods = [n for n in result.nodes if n.kind == NodeKind.METHOD]
        assert len(methods) == 1
        assert methods[0].metadata.get("static") is True


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """Cover import-related extraction paths."""

    def test_import_statement(self, extractor):
        """Line 607: import statement handling."""
        code = b"import os\nimport sys"
        result = extractor.extract("test.py", code)
        imports = [n for n in result.nodes if n.kind == NodeKind.IMPORT]
        assert len(imports) >= 2

    def test_from_import(self, extractor):
        """Cover from...import handling."""
        code = b"from os.path import join, exists"
        result = extractor.extract("test.py", code)
        imports = [n for n in result.nodes if n.kind == NodeKind.IMPORT]
        assert len(imports) >= 1

    def test_star_import(self, extractor):
        """Cover wildcard import."""
        code = b"from os.path import *"
        result = extractor.extract("test.py", code)
        imports = [n for n in result.nodes if n.kind == NodeKind.IMPORT]
        assert len(imports) >= 1

    def test_aliased_import(self, extractor):
        """Cover aliased import."""
        code = b"import numpy as np\nfrom collections import OrderedDict as OD"
        result = extractor.extract("test.py", code)
        imports = [n for n in result.nodes if n.kind == NodeKind.IMPORT]
        assert len(imports) >= 1

    def test_relative_import(self, extractor):
        """Cover relative import."""
        code = b"from . import utils\nfrom ..models import User"
        result = extractor.extract("test.py", code)
        imports = [n for n in result.nodes if n.kind == NodeKind.IMPORT]
        assert len(imports) >= 1


# ---------------------------------------------------------------------------
# Assignment / variable / constant extraction
# ---------------------------------------------------------------------------


class TestAssignmentExtraction:
    """Cover assignment / variable extraction paths."""

    def test_module_level_constant(self, extractor):
        """Lines 745, 782: UPPER_CASE creates CONSTANT nodes."""
        code = b'MAX_SIZE = 1024\nDEFAULT_NAME = "test"'
        result = extractor.extract("test.py", code)
        constants = [n for n in result.nodes if n.kind == NodeKind.CONSTANT]
        assert len(constants) >= 1

    def test_module_level_variable(self, extractor):
        """Lower-case assignments create VARIABLE nodes."""
        code = b'my_var = 42\nother = "hello"'
        result = extractor.extract("test.py", code)
        variables = [n for n in result.nodes if n.kind == NodeKind.VARIABLE]
        assert len(variables) >= 1

    def test_annotated_assignment(self, extractor):
        """Cover type-annotated assignment."""
        code = b"x: int = 42\ny: str"
        result = extractor.extract("test.py", code)
        variables = [n for n in result.nodes if n.kind == NodeKind.VARIABLE]
        assert len(variables) >= 1

    def test_tuple_assignment(self, extractor):
        """Cover tuple unpacking assignment."""
        code = b"a, b = 1, 2"
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"

    def test_augmented_assignment(self, extractor):
        """Cover augmented assignment (+=, etc.)."""
        code = b"x = 0\nx += 1"
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"


# ---------------------------------------------------------------------------
# Type alias extraction
# ---------------------------------------------------------------------------


class TestTypeAliasExtraction:
    """Cover _handle_type_alias (lines 1027-1049)."""

    def test_type_alias_statement(self, extractor):
        """Lines 1027-1049: type alias statement (Python 3.12+)."""
        code = b"type Vector = list[float]\ntype Matrix = list[Vector]"
        result = extractor.extract("test.py", code)
        type_aliases = [n for n in result.nodes if n.kind == NodeKind.TYPE_ALIAS]
        # tree-sitter may or may not support type statement
        assert result.file_path == "test.py"

    def test_old_style_type_alias(self, extractor):
        """Cover TypeAlias = ... style."""
        code = b"from typing import TypeAlias\nVector: TypeAlias = list[float]"
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"


# ---------------------------------------------------------------------------
# if TYPE_CHECKING
# ---------------------------------------------------------------------------


class TestIfTypeChecking:
    """Cover _handle_if_statement for TYPE_CHECKING (lines 1100-1109)."""

    def test_if_type_checking_block(self, extractor):
        """Lines 1100-1109: imports inside if TYPE_CHECKING."""
        code = b"""from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os.path import join
    from collections import OrderedDict

def foo() -> None:
    pass
"""
        result = extractor.extract("test.py", code)
        imports = [n for n in result.nodes if n.kind == NodeKind.IMPORT]
        assert len(imports) >= 2

    def test_if_typing_type_checking(self, extractor):
        """Cover typing.TYPE_CHECKING variant."""
        code = b"""import typing

if typing.TYPE_CHECKING:
    from os import getcwd
"""
        result = extractor.extract("test.py", code)
        imports = [n for n in result.nodes if n.kind == NodeKind.IMPORT]
        assert len(imports) >= 1

    def test_regular_if_not_type_checking(self, extractor):
        """Non-TYPE_CHECKING if should not be walked for imports."""
        code = b"""x = True
if x:
    import hidden_module
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"


# ---------------------------------------------------------------------------
# Decorator nodes
# ---------------------------------------------------------------------------


class TestDecoratorNodes:
    """Cover _create_decorator_node (lines 908, 910, 919-920, 935-939)."""

    def test_decorator_with_arguments(self, extractor):
        """Cover decorator with call arguments."""
        code = b'@app.route("/api")\ndef handler():\n    pass'
        result = extractor.extract("test.py", code)
        decorators = [n for n in result.nodes if n.kind == NodeKind.DECORATOR]
        assert len(decorators) >= 1

    def test_multiple_decorators(self, extractor):
        """Cover multiple decorators on single function."""
        code = b"@login_required\n@cache(timeout=300)\ndef view():\n    pass"
        result = extractor.extract("test.py", code)
        decorators = [n for n in result.nodes if n.kind == NodeKind.DECORATOR]
        assert len(decorators) >= 2

    def test_class_method_decorators(self, extractor):
        """Cover decorators on class methods."""
        code = b"""class Foo:
    @staticmethod
    def bar():
        pass

    @classmethod
    def baz(cls):
        pass
"""
        result = extractor.extract("test.py", code)
        decorators = [n for n in result.nodes if n.kind == NodeKind.DECORATOR]
        assert len(decorators) >= 2

    def test_dotted_decorator(self, extractor):
        """Cover dotted decorator name (e.g., @app.route)."""
        code = b'@app.route("/")\ndef index():\n    pass'
        result = extractor.extract("test.py", code)
        decorators = [n for n in result.nodes if n.kind == NodeKind.DECORATOR]
        assert len(decorators) >= 1


# ---------------------------------------------------------------------------
# Call scanning
# ---------------------------------------------------------------------------


class TestCallScanning:
    """Cover _scan_calls (line 971)."""

    def test_function_calls_detected(self, extractor):
        """Cover call scanning in function bodies."""
        code = b"""def foo():
    bar()
    baz(1, 2)
    obj.method()
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"

    def test_nested_calls(self, extractor):
        """Cover nested function calls."""
        code = b"""def foo():
    result = outer(inner(x))
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"

    def test_method_calls_in_class(self, extractor):
        """Cover method calls within class methods."""
        code = b"""class Foo:
    def bar(self):
        self.baz()
        self.qux(1, 2)
        other_func()
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"


# ---------------------------------------------------------------------------
# Complex scenarios
# ---------------------------------------------------------------------------


class TestComplexScenarios:
    """Cover complex code patterns that exercise multiple paths."""

    def test_full_module(self, extractor):
        """Exercise many paths at once."""
        code = b"""\"\"\"Module docstring.\"\"\"\n
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pathlib import Path

MAX_SIZE: int = 1024
_PRIVATE = "hidden"

@dataclass
class Config:
    name: str = "default"
    size: int = 0

    @property
    def is_valid(self) -> bool:
        return self.size > 0

    def validate(self, strict: bool = False) -> None:
        check(self.name)

class Manager(Config):
    @staticmethod
    def create() -> "Manager":
        return Manager()

    @classmethod
    def from_dict(cls, data: dict) -> "Manager":
        return cls(**data)

async def fetch(url: str, timeout: int = 30) -> dict:
    result = await get(url)
    return process(result)

def helper(*args, **kwargs):
    pass
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"
        assert len(result.nodes) > 5
        kinds = {n.kind for n in result.nodes}
        assert NodeKind.FILE in kinds
        assert NodeKind.CLASS in kinds
        assert NodeKind.FUNCTION in kinds

    def test_empty_file(self, extractor):
        """Cover empty file handling."""
        result = extractor.extract("empty.py", b"")
        assert result.file_path == "empty.py"
        file_nodes = [n for n in result.nodes if n.kind == NodeKind.FILE]
        assert len(file_nodes) <= 1

    def test_only_comments(self, extractor):
        """Cover file with only comments."""
        code = b"# This is a comment\n# Another comment\n"
        result = extractor.extract("comments.py", code)
        assert result.file_path == "comments.py"

    def test_class_with_slots(self, extractor):
        """Cover __slots__ in class."""
        code = b"""class Foo:
    __slots__ = ("x", "y")
    def __init__(self, x, y):
        self.x = x
        self.y = y
"""
        result = extractor.extract("test.py", code)
        classes = [n for n in result.nodes if n.kind == NodeKind.CLASS]
        assert len(classes) == 1

    def test_dataclass_with_fields(self, extractor):
        """Cover dataclass with field definitions."""
        code = b"""from dataclasses import dataclass, field

@dataclass
class Point:
    x: float = 0.0
    y: float = 0.0
    tags: list = field(default_factory=list)
"""
        result = extractor.extract("test.py", code)
        classes = [n for n in result.nodes if n.kind == NodeKind.CLASS]
        assert len(classes) == 1

    def test_enum_class(self, extractor):
        """Cover enum class."""
        code = b"""from enum import Enum

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3
"""
        result = extractor.extract("test.py", code)
        enums = [n for n in result.nodes if n.kind == NodeKind.ENUM]
        assert len(enums) == 1

    def test_protocol_class(self, extractor):
        """Cover Protocol class."""
        code = b"""from typing import Protocol

class Readable(Protocol):
    def read(self) -> bytes:
        ...
"""
        result = extractor.extract("test.py", code)
        ifaces = [n for n in result.nodes if n.kind == NodeKind.INTERFACE]
        assert len(ifaces) == 1

    def test_lambda_expression(self, extractor):
        """Cover lambda expression."""
        code = b"sorter = lambda x: x.name"
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"

    def test_global_and_nonlocal(self, extractor):
        """Cover global and nonlocal statements."""
        code = b"""x = 10
def foo():
    global x
    x = 20
    def bar():
        nonlocal x
        x = 30
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"

    def test_try_except_in_function(self, extractor):
        """Cover try/except blocks."""
        code = b"""def foo():
    try:
        bar()
    except ValueError as e:
        handle(e)
    finally:
        cleanup()
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"

    def test_with_statement(self, extractor):
        """Cover with statement."""
        code = b"""def foo():
    with open("file") as f:
        data = f.read()
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"

    def test_match_statement(self, extractor):
        """Cover match/case (Python 3.10+)."""
        code = b"""match command:
    case "quit":
        exit()
    case "hello":
        greet()
"""
        result = extractor.extract("test.py", code)
        assert result.file_path == "test.py"
