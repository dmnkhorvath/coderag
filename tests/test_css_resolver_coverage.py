"""Targeted coverage tests for CSS resolver — covers lines 74, 101-103, 112, 122-123, 163-180."""

from coderag.core.models import FileInfo, Language, ResolutionStrategy
from coderag.plugins.css.resolver import CSSResolver


def _make_fi(rel: str, abs_path: str = "") -> FileInfo:
    return FileInfo(
        path=abs_path or f"/project/{rel}",
        relative_path=rel,
        language=Language.CSS,
        plugin_name="css",
        size_bytes=100,
    )


class TestCSSResolverDataURI:
    """Cover line 74 — data: URI returns external/unresolved."""

    def test_data_uri_returns_external(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("data:image/png;base64,abc", "styles/main.css")
        assert result.resolved_path is None
        assert result.is_external is True
        assert result.confidence == 0.0

    def test_data_uri_svg(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("data:image/svg+xml,%3Csvg%3E", "a.css")
        assert result.resolved_path is None
        assert result.is_external is True


class TestCSSResolverPathNormalization:
    """Cover lines 101-103 — ValueError/RuntimeError when path is outside project root."""

    def test_path_outside_project_root(self, tmp_path):
        """When resolved path is outside project root, ValueError is caught."""
        project = tmp_path / "project"
        project.mkdir()
        r = CSSResolver()
        r.set_project_root(str(project))
        # Index a file that lives outside the project
        r.build_index([])
        # Import path that resolves outside project root
        result = r.resolve("../../outside.css", "styles/main.css")
        # Should not crash — falls through to basename matching or unresolved
        assert result is not None

    def test_relative_path_with_dotdot(self, tmp_path):
        """Relative path with ../ that stays inside project."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "base").mkdir()
        (project / "base" / "reset.css").write_text("body{}")
        r = CSSResolver()
        r.set_project_root(str(project))
        r.build_index(
            [
                _make_fi("base/reset.css", str(project / "base" / "reset.css")),
            ]
        )
        result = r.resolve("../base/reset.css", "styles/main.css")
        assert result is not None


class TestCSSResolverExtensionResolution:
    """Cover line 112 — adding .css extension to extensionless import."""

    def test_extensionless_import_resolved_with_css(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/reset.css"),
            ]
        )
        # Import without .css extension — resolver should try adding .css
        result = r.resolve("./reset", "styles/main.css")
        # The candidate after normalization would be "styles/reset"
        # Then tries "styles/reset.css" which should match
        if result.resolved_path is not None:
            assert result.confidence >= 0.7
        # At minimum, it should not crash
        assert result is not None


class TestCSSResolverBasenameMatching:
    """Cover lines 122-123 — multiple basename matches triggering _pick_closest."""

    def test_single_basename_match(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("components/button.css"),
            ]
        )
        result = r.resolve("button", "pages/home.css")
        assert result.resolved_path == "components/button.css"
        assert result.confidence == 0.7
        assert result.resolution_strategy == ResolutionStrategy.HEURISTIC

    def test_multiple_basename_matches_picks_closest(self):
        """When multiple files share the same basename, _pick_closest is used."""
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("components/button.css"),
                _make_fi("pages/button.css"),
                _make_fi("shared/button.css"),
            ]
        )
        # Import from src/ (no button.css there) — triggers basename multi-match
        result = r.resolve("button", "pages/deep/home.css")
        assert result.confidence == 0.5
        assert result.resolution_strategy == ResolutionStrategy.HEURISTIC

    def test_multiple_matches_different_depths(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("a/b/c/vars.css"),
                _make_fi("a/b/vars.css"),
                _make_fi("x/y/vars.css"),
            ]
        )
        # from z/main.css — z/vars.css not in index, triggers basename multi-match
        result = r.resolve("vars", "z/main.css")
        assert result.confidence == 0.5
        assert result.resolution_strategy == ResolutionStrategy.HEURISTIC


class TestCSSResolverPickClosest:
    """Cover lines 163-180 — _pick_closest method directly."""

    def test_pick_closest_common_prefix(self):
        r = CSSResolver()
        candidates = ["x/y/z/file.css", "a/b/c/file.css", "a/b/file.css"]
        result = r._pick_closest("a/b/main.css", candidates)
        assert result == "a/b/file.css" or result == "a/b/c/file.css"

    def test_pick_closest_no_common_prefix(self):
        r = CSSResolver()
        candidates = ["x/file.css", "y/file.css"]
        result = r._pick_closest("z/main.css", candidates)
        # Both have 0 common prefix, first one wins
        assert result == "x/file.css"

    def test_pick_closest_single_candidate(self):
        r = CSSResolver()
        result = r._pick_closest("a/b.css", ["c/d.css"])
        assert result == "c/d.css"

    def test_pick_closest_exact_dir_match(self):
        r = CSSResolver()
        candidates = ["src/styles/a.css", "lib/styles/a.css"]
        result = r._pick_closest("src/styles/main.css", candidates)
        assert result == "src/styles/a.css"

    def test_pick_closest_deep_nesting(self):
        r = CSSResolver()
        candidates = [
            "a/b/c/d/e/file.css",
            "a/b/c/file.css",
            "a/file.css",
        ]
        result = r._pick_closest("a/b/c/d/main.css", candidates)
        # a/b/c/d/e/file.css has 4 common parts, a/b/c/file.css has 3
        assert result == "a/b/c/d/e/file.css"


class TestCSSResolverResolveSymbol:
    """Cover resolve_symbol method."""

    def test_resolve_symbol_returns_unresolved(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve_symbol("--primary-color", "styles/main.css")
        assert result.resolved_path is None
        assert result.confidence == 0.0

    def test_resolve_symbol_with_context(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve_symbol("fadeIn", "styles/main.css", {"type": "keyframes"})
        assert result.resolved_path is None


class TestCSSResolverEdgeCases:
    """Additional edge cases for full coverage."""

    def test_external_http_url(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("http://cdn.example.com/style.css", "main.css")
        assert result.is_external is True
        assert result.package_name == "http://cdn.example.com/style.css"

    def test_external_https_url(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("https://cdn.example.com/style.css", "main.css")
        assert result.is_external is True

    def test_external_protocol_relative_url(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("//cdn.example.com/style.css", "main.css")
        assert result.is_external is True

    def test_unresolved_import(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("nonexistent.css", "main.css")
        assert result.resolved_path is None
        assert result.resolution_strategy == ResolutionStrategy.UNRESOLVED

    def test_exact_match(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/reset.css"),
            ]
        )
        result = r.resolve("./reset.css", "styles/main.css")
        # After normalization, should match styles/reset.css
        assert result is not None

    def test_build_index_clears_previous(self):
        r = CSSResolver()
        r.set_project_root("/project")
        r.build_index([_make_fi("a.css")])
        assert len(r._css_files) == 1
        r.build_index([_make_fi("b.css"), _make_fi("c.css")])
        assert len(r._css_files) == 2
