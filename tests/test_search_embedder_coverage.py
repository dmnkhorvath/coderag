"""Tests for search embedder build_node_text to cover missing lines."""
import pytest
from coderag.core.models import Node, NodeKind
from coderag.search.embedder import CodeEmbedder


class TestBuildNodeText:
    """Test CodeEmbedder.build_node_text static method."""

    def _make_node(self, **kwargs):
        defaults = dict(
            id="n1", kind=NodeKind.FUNCTION, name="my_func",
            qualified_name="my_func", file_path="app.py",
            start_line=1, end_line=10, language="python",
        )
        defaults.update(kwargs)
        return Node(**defaults)

    def test_basic_node(self):
        node = self._make_node()
        text = CodeEmbedder.build_node_text(node)
        assert "function" in text.lower() or "my_func" in text
        assert "my_func" in text
        assert "app.py" in text

    def test_with_qualified_name_different(self):
        """Cover line 128: qualified_name != name."""
        node = self._make_node(name="func", qualified_name="mymodule.MyClass.func")
        text = CodeEmbedder.build_node_text(node)
        assert "mymodule.MyClass.func" in text

    def test_with_same_name_and_qualified_name(self):
        """When qualified_name == name, it should NOT appear twice."""
        node = self._make_node(name="func", qualified_name="func")
        text = CodeEmbedder.build_node_text(node)
        # qualified_name bracket notation should not appear
        assert "[func]" not in text

    def test_with_docblock(self):
        node = self._make_node(docblock="This function does something.")
        text = CodeEmbedder.build_node_text(node)
        assert "This function does something" in text

    def test_with_long_docblock_truncated(self):
        """Docblocks > 500 chars should be truncated."""
        long_doc = "A" * 600
        node = self._make_node(docblock=long_doc)
        text = CodeEmbedder.build_node_text(node)
        assert "..." in text
        # Should not contain the full 600 chars
        assert "A" * 600 not in text

    def test_with_parameters_list_of_strings(self):
        """Cover line 136-138: params as list of strings."""
        node = self._make_node(metadata={"parameters": ["x", "y", "z"]})
        text = CodeEmbedder.build_node_text(node)
        assert "Parameters" in text
        assert "x" in text
        assert "y" in text

    def test_with_parameters_list_of_dicts(self):
        """Cover line 138: params as list of dicts with 'name' key."""
        node = self._make_node(metadata={"parameters": [{"name": "arg1", "type": "int"}, {"name": "arg2", "type": "str"}]})
        text = CodeEmbedder.build_node_text(node)
        assert "Parameters" in text
        assert "arg1" in text
        assert "arg2" in text

    def test_with_params_key(self):
        """Cover the meta.get('params') fallback."""
        node = self._make_node(metadata={"params": ["a", "b"]})
        text = CodeEmbedder.build_node_text(node)
        assert "Parameters" in text
        assert "a" in text

    def test_with_parameters_string(self):
        """Cover line 140: params as a plain string."""
        node = self._make_node(metadata={"parameters": "(self, x, y)"})
        text = CodeEmbedder.build_node_text(node)
        assert "Parameters" in text
        assert "(self, x, y)" in text

    def test_with_return_type(self):
        """Cover line 144: return_type metadata."""
        node = self._make_node(metadata={"return_type": "list[str]"})
        text = CodeEmbedder.build_node_text(node)
        assert "Returns" in text
        assert "list[str]" in text

    def test_with_returns_key(self):
        """Cover the meta.get('returns') fallback."""
        node = self._make_node(metadata={"returns": "int"})
        text = CodeEmbedder.build_node_text(node)
        assert "Returns" in text
        assert "int" in text

    def test_with_decorators_list(self):
        """Cover lines 148-150: decorators as list."""
        node = self._make_node(metadata={"decorators": ["@staticmethod", "@cache"]})
        text = CodeEmbedder.build_node_text(node)
        assert "Decorators" in text
        assert "@staticmethod" in text
        assert "@cache" in text

    def test_with_decorators_string(self):
        """Cover line 152: decorators as string."""
        node = self._make_node(metadata={"decorators": "@property"})
        text = CodeEmbedder.build_node_text(node)
        assert "Decorators" in text
        assert "@property" in text

    def test_with_extends(self):
        """Cover extends/superclass metadata."""
        node = self._make_node(kind=NodeKind.CLASS, name="MyClass",
                               qualified_name="MyClass",
                               metadata={"extends": "BaseClass"})
        text = CodeEmbedder.build_node_text(node)
        assert "Extends" in text
        assert "BaseClass" in text

    def test_with_superclass_key(self):
        """Cover the meta.get('superclass') fallback."""
        node = self._make_node(kind=NodeKind.CLASS, name="MyClass",
                               qualified_name="MyClass",
                               metadata={"superclass": "ParentClass"})
        text = CodeEmbedder.build_node_text(node)
        assert "Extends" in text
        assert "ParentClass" in text

    def test_with_implements_list(self):
        """Cover implements as list."""
        node = self._make_node(kind=NodeKind.CLASS, name="MyClass",
                               qualified_name="MyClass",
                               metadata={"implements": ["Serializable", "Comparable"]})
        text = CodeEmbedder.build_node_text(node)
        assert "Implements" in text
        assert "Serializable" in text

    def test_with_implements_string(self):
        """Cover implements as string."""
        node = self._make_node(kind=NodeKind.CLASS, name="MyClass",
                               qualified_name="MyClass",
                               metadata={"implements": "Iterable"})
        text = CodeEmbedder.build_node_text(node)
        assert "Implements" in text
        assert "Iterable" in text

    def test_with_parent_name(self):
        """Cover parent_name parameter."""
        node = self._make_node(name="method", qualified_name="MyClass.method")
        text = CodeEmbedder.build_node_text(node, parent_name="MyClass")
        assert "MyClass" in text

    def test_with_all_metadata(self):
        """Cover all metadata paths at once."""
        node = self._make_node(
            kind=NodeKind.METHOD, name="process",
            qualified_name="Handler.process",
            docblock="Process the request.",
            metadata={
                "parameters": [{"name": "request"}, {"name": "response"}],
                "return_type": "bool",
                "decorators": ["@override"],
                "extends": "BaseHandler",
                "implements": ["Processable"],
            }
        )
        text = CodeEmbedder.build_node_text(node, parent_name="Handler")
        assert "process" in text
        assert "Handler.process" in text
        assert "Process the request" in text
        assert "Parameters" in text
        assert "request" in text
        assert "Returns" in text
        assert "bool" in text
        assert "Decorators" in text
        assert "Extends" in text
        assert "Implements" in text

    def test_no_file_path(self):
        """Node without file_path."""
        node = self._make_node(file_path="")
        text = CodeEmbedder.build_node_text(node)
        assert "my_func" in text

    def test_no_metadata(self):
        """Node with None metadata."""
        node = self._make_node(metadata=None)
        text = CodeEmbedder.build_node_text(node)
        assert "my_func" in text
        assert "Parameters" not in text
