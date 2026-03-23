from pathlib import Path

from coderag.core.models import EdgeKind, Language, NodeKind, ResolutionStrategy
from coderag.plugins.rust.extractor import RustExtractor
from coderag.plugins.rust.plugin import RustPlugin
from coderag.plugins.rust.resolver import RustResolver


class TestRustExtractor:
    def test_basic_extraction_and_calls(self):
        ext = RustExtractor()
        source = b'''
use std::collections::HashMap;
use crate::foo::Bar;

struct User { id: i32, name: String }

impl User {
    fn new(id: i32) -> Self {
        println!("x");
        helper(id)
    }
}

fn helper(x: i32) -> i32 { x }
const MAX: i32 = 3;
type UserId = i64;
'''
        result = ext.extract("src/lib.rs", source)
        assert result.errors == []
        kinds = {n.kind for n in result.nodes}
        assert NodeKind.FILE in kinds
        assert NodeKind.IMPORT in kinds
        assert NodeKind.CLASS in kinds
        assert NodeKind.METHOD in kinds
        assert NodeKind.FUNCTION in kinds
        assert NodeKind.CONSTANT in kinds
        assert NodeKind.TYPE_ALIAS in kinds
        refs = {(u.reference_kind, u.reference_name) for u in result.unresolved_references}
        assert (EdgeKind.CALLS, "println") in refs or (EdgeKind.CALLS, "println!") in refs
        assert any(kind == EdgeKind.CALLS and "helper" in name for kind, name in refs)

    def test_trait_and_impl(self):
        ext = RustExtractor()
        source = b'''
trait Repo { fn get(&self) -> i32; }
struct User { id: i32 }
impl Repo for User {
    fn get(&self) -> i32 { 1 }
}
'''
        result = ext.extract("src/repo.rs", source)
        assert result.errors == []
        assert any(n.kind == NodeKind.INTERFACE and n.name == "Repo" for n in result.nodes)
        assert any(n.kind == NodeKind.METHOD and n.name == "get" for n in result.nodes)
        assert any(u.reference_kind == EdgeKind.IMPLEMENTS and u.reference_name == "Repo" for u in result.unresolved_references)

    def test_mod_and_enum(self):
        ext = RustExtractor()
        source = b'''
mod inner {}
enum Status { A, B(i32) }
'''
        result = ext.extract("src/status.rs", source)
        assert any(n.kind == NodeKind.PACKAGE and n.name == "inner" for n in result.nodes)
        assert any(n.kind == NodeKind.CLASS and n.name == "Status" for n in result.nodes)


class TestRustPlugin:
    def test_plugin_properties(self):
        plugin = RustPlugin()
        assert plugin.name == "rust"
        assert plugin.language == Language.RUST
        assert ".rs" in plugin.file_extensions


class TestRustResolver:
    def test_resolver_stdlib_and_local(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.rs").write_text("pub struct Foo;", encoding="utf-8")
        resolver = RustResolver()
        resolver.set_project_root(str(tmp_path / "src"))

        std = resolver.resolve("std::collections::HashMap", "lib.rs")
        assert std.resolution_strategy == ResolutionStrategy.HEURISTIC
        assert std.metadata.get("stdlib") is True

        local = resolver.resolve("crate::foo", "lib.rs")
        assert local.resolution_strategy == ResolutionStrategy.EXACT
        assert local.resolved_path.endswith("foo.rs")
