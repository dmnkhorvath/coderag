import pytest

from coderag.core.models import EdgeKind, NodeKind
from coderag.plugins.go.extractor import GoExtractor
from coderag.plugins.go.plugin import GoPlugin


def _kinds(nodes, kind):
    return [n for n in nodes if n.kind == kind]


class TestGoExtractor:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.extractor = GoExtractor()

    def test_basic_extraction_and_calls(self):
        source = b"""package main
import "fmt"
func main() { fmt.Println("hello") }"""
        result = self.extractor.extract("main.go", source)
        assert len(result.errors) == 0
        assert result.language == "go"
        assert len(_kinds(result.nodes, NodeKind.PACKAGE)) == 1
        assert len(_kinds(result.nodes, NodeKind.IMPORT)) == 1
        assert len(_kinds(result.nodes, NodeKind.FUNCTION)) == 1
        assert len(result.unresolved_references) >= 1
        call_ref = result.unresolved_references[0]
        assert call_ref.reference_name == "fmt.Println"
        assert call_ref.reference_kind == EdgeKind.CALLS

    def test_struct_embedding(self):
        source = b"""package models
type Base struct { ID int }
type User struct {
    Base
    Name string
}"""
        result = self.extractor.extract("models.go", source)
        assert len(result.errors) == 0
        assert len(_kinds(result.nodes, NodeKind.CLASS)) == 2
        user_node = next(n for n in result.nodes if n.name == "User")
        extends_refs = [
            ref
            for ref in result.unresolved_references
            if ref.source_node_id == user_node.id and ref.reference_kind == EdgeKind.EXTENDS
        ]
        assert len(extends_refs) == 1
        assert extends_refs[0].reference_name == "Base"

    def test_interface(self):
        source = b"""package repo
type Repository interface { Find(id int) error }"""
        result = self.extractor.extract("repo.go", source)
        assert len(_kinds(result.nodes, NodeKind.INTERFACE)) == 1


class TestGoPlugin:
    def test_plugin_properties(self):
        plugin = GoPlugin()
        assert plugin.name == "go"
        assert ".go" in plugin.file_extensions
