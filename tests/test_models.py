"""Tests for coderag.core.models."""

import pytest

from coderag.core.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    estimate_tokens,
)


class TestNodeKind:
    def test_all_structural_kinds(self):
        assert NodeKind.FILE.value == "file"
        assert NodeKind.DIRECTORY.value == "directory"
        assert NodeKind.PACKAGE.value == "package"

    def test_all_declaration_kinds(self):
        for kind in [
            "class",
            "interface",
            "trait",
            "function",
            "method",
            "property",
            "constant",
            "enum",
            "type_alias",
            "variable",
        ]:
            assert NodeKind(kind).value == kind

    def test_framework_kinds(self):
        for kind in ["route", "component", "hook", "model", "event"]:
            assert NodeKind(kind).value == kind

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError):
            NodeKind("nonexistent")


class TestEdgeKind:
    def test_common_edge_kinds(self):
        for kind in ["calls", "imports", "extends", "implements", "contains"]:
            assert EdgeKind(kind).value == kind

    def test_invalid_edge_kind_raises(self):
        with pytest.raises(ValueError):
            EdgeKind("nonexistent")


class TestNode:
    def test_create_node(self):
        node = Node(
            id="test-id",
            kind=NodeKind.CLASS,
            name="MyClass",
            qualified_name="App\\MyClass",
            file_path="/tmp/app/MyClass.php",
            start_line=1,
            end_line=10,
            language="php",
        )
        assert node.id == "test-id"
        assert node.kind == NodeKind.CLASS
        assert node.name == "MyClass"
        assert node.qualified_name == "App\\MyClass"
        assert node.language == "php"

    def test_node_defaults(self):
        node = Node(
            id="test",
            kind=NodeKind.FILE,
            name="test.php",
            qualified_name="test.php",
            file_path="/tmp/test.php",
            start_line=1,
            end_line=1,
            language="php",
        )
        assert node.metadata == {} or node.metadata is not None


class TestEdge:
    def test_create_edge(self):
        edge = Edge(
            source_id="src",
            target_id="tgt",
            kind=EdgeKind.CALLS,
            confidence=0.9,
        )
        assert edge.source_id == "src"
        assert edge.target_id == "tgt"
        assert edge.kind == EdgeKind.CALLS
        assert edge.confidence == 0.9


class TestEstimateTokens:
    def test_empty_string(self):
        # estimate_tokens may return 1 for empty string (minimum)
        assert estimate_tokens("") >= 0
        assert estimate_tokens("") <= 1

    def test_short_string(self):
        result = estimate_tokens("hello world")
        assert result > 0
        assert result < 10

    def test_longer_string(self):
        text = "word " * 100
        result = estimate_tokens(text)
        assert 20 < result < 200
