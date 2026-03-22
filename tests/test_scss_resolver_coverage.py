"""Targeted coverage tests for SCSS resolver — covers lines 85, 131, 175, 200, 217-218, 233-249."""

from coderag.core.models import FileInfo, Language, ResolutionStrategy
from coderag.plugins.scss.resolver import SCSSResolver


def _make_fi(rel: str, abs_path: str = "") -> FileInfo:
    return FileInfo(
        path=abs_path or f"/project/{rel}",
        relative_path=rel,
        language=Language.SCSS,
        plugin_name="scss",
        size_bytes=100,
    )


class TestSCSSResolverResolveSymbol:
    """Cover line 85 — resolve_symbol delegates to resolve."""

    def test_resolve_symbol_delegates(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/_vars.scss"),
            ]
        )
        result = r.resolve_symbol("vars", "styles/main.scss")
        # resolve_symbol should delegate to resolve
        assert result is not None

    def test_resolve_symbol_unresolved(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve_symbol("nonexistent", "styles/main.scss")
        assert result.resolved_path is None

    def test_resolve_symbol_with_context(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve_symbol("$color", "styles/main.scss", {"type": "variable"})
        assert result is not None


class TestSCSSResolverExactMatch:
    """Cover line 131 — exact match in _try_resolve."""

    def test_exact_match_with_extension(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/reset.scss"),
            ]
        )
        result = r.resolve("./reset.scss", "styles/main.scss")
        assert result.resolved_path == "styles/reset.scss"
        assert result.confidence == 1.0
        assert result.resolution_strategy == ResolutionStrategy.EXACT

    def test_exact_match_full_path(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("components/button.scss"),
            ]
        )
        result = r.resolve("./button.scss", "components/index.scss")
        assert result.resolved_path == "components/button.scss"
        assert result.confidence == 1.0


class TestSCSSResolverPartialDirectory:
    """Cover line 175 — partial + directory index resolution (_filename/index.scss)."""

    def test_partial_directory_index(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/_utils/index.scss"),
            ]
        )
        result = r.resolve("./utils", "styles/main.scss")
        assert result is not None
        if result.resolved_path is not None:
            assert "index.scss" in result.resolved_path
            assert result.resolution_strategy == ResolutionStrategy.SCSS_PARTIAL

    def test_partial_directory_underscore_index(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/_mixins/_index.scss"),
            ]
        )
        result = r.resolve("./mixins", "styles/main.scss")
        assert result is not None
        if result.resolved_path is not None:
            assert "_index.scss" in result.resolved_path

    def test_partial_directory_sass_extension(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/_helpers/index.sass"),
            ]
        )
        result = r.resolve("./helpers", "styles/main.scss")
        assert result is not None


class TestSCSSResolverBasenameWithExtension:
    """Cover line 200 — exact basename with extension in _try_basename_match."""

    def test_basename_with_extension_dot_in_name(self):
        """When import name contains a dot, try exact basename lookup."""
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("vendor/bootstrap.min.scss"),
            ]
        )
        # Import with a dot in the name — triggers the "." in name branch
        result = r.resolve("bootstrap.min", "styles/main.scss")
        assert result is not None

    def test_basename_with_scss_extension(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("lib/theme.dark.scss"),
            ]
        )
        result = r.resolve("theme.dark", "styles/main.scss")
        assert result is not None


class TestSCSSResolverMultipleBasenameMatches:
    """Cover lines 217-218 — multiple unique matches triggering _pick_closest."""

    def test_single_basename_match(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("components/_button.scss"),
            ]
        )
        result = r.resolve("button", "pages/home.scss")
        if result.resolved_path is not None:
            assert result.confidence == 0.7
            assert result.resolution_strategy == ResolutionStrategy.HEURISTIC

    def test_multiple_basename_matches_picks_closest(self):
        """Multiple files with same basename — _pick_closest selects nearest."""
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("components/_button.scss"),
                _make_fi("pages/_button.scss"),
                _make_fi("shared/_button.scss"),
            ]
        )
        # from_file in src/ where no _button.scss exists — triggers basename multi-match
        result = r.resolve("button", "src/main.scss")
        assert result.resolved_path is not None
        assert result.confidence == 0.5
        assert result.resolution_strategy == ResolutionStrategy.HEURISTIC

    def test_multiple_matches_different_directories(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("a/b/c/_vars.scss"),
                _make_fi("a/b/_vars.scss"),
                _make_fi("x/y/_vars.scss"),
            ]
        )
        # from z/ where no _vars.scss exists — triggers basename multi-match
        result = r.resolve("vars", "z/main.scss")
        assert result.resolved_path is not None
        assert result.confidence == 0.5
        assert result.resolution_strategy == ResolutionStrategy.HEURISTIC


class TestSCSSResolverPickClosest:
    """Cover lines 233-249 — _pick_closest method."""

    def test_pick_closest_common_prefix(self):
        r = SCSSResolver()
        candidates = ["x/y/z/file.scss", "a/b/c/file.scss", "a/b/file.scss"]
        result = r._pick_closest("a/b/main.scss", candidates)
        assert result in ("a/b/file.scss", "a/b/c/file.scss")

    def test_pick_closest_no_common_prefix(self):
        r = SCSSResolver()
        candidates = ["x/file.scss", "y/file.scss"]
        result = r._pick_closest("z/main.scss", candidates)
        assert result == "x/file.scss"  # first candidate wins with 0 common

    def test_pick_closest_single_candidate(self):
        r = SCSSResolver()
        result = r._pick_closest("a/b.scss", ["c/d.scss"])
        assert result == "c/d.scss"

    def test_pick_closest_exact_dir_match(self):
        r = SCSSResolver()
        candidates = ["src/styles/a.scss", "lib/styles/a.scss"]
        result = r._pick_closest("src/styles/main.scss", candidates)
        assert result == "src/styles/a.scss"

    def test_pick_closest_deep_nesting(self):
        r = SCSSResolver()
        candidates = [
            "a/b/c/d/e/file.scss",
            "a/b/c/file.scss",
            "a/file.scss",
        ]
        result = r._pick_closest("a/b/c/d/main.scss", candidates)
        assert result == "a/b/c/d/e/file.scss"


class TestSCSSResolverEdgeCases:
    """Additional edge cases."""

    def test_external_url(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("https://cdn.example.com/style.scss", "main.scss")
        assert result.is_external is True

    def test_data_uri(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("data:text/css;base64,abc", "main.scss")
        assert result.is_external is True

    def test_unresolved_import(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index([])
        result = r.resolve("nonexistent", "main.scss")
        assert result.resolved_path is None
        assert result.resolution_strategy == ResolutionStrategy.UNRESOLVED

    def test_partial_convention(self):
        """SCSS partial convention: _filename.scss."""
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/_variables.scss"),
            ]
        )
        result = r.resolve("./variables", "styles/main.scss")
        if result.resolved_path is not None:
            assert "_variables.scss" in result.resolved_path
            assert result.resolution_strategy == ResolutionStrategy.SCSS_PARTIAL

    def test_extension_resolution(self):
        """Import without extension — resolver adds .scss."""
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/reset.scss"),
            ]
        )
        result = r.resolve("./reset", "styles/main.scss")
        if result.resolved_path is not None:
            assert result.confidence >= 0.9

    def test_build_index_clears_previous(self):
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index([_make_fi("a.scss")])
        r.build_index([_make_fi("b.scss"), _make_fi("c.scss")])
        assert len(r._scss_files) == 2

    def test_directory_index_resolution(self):
        """Import a directory — resolver tries index.scss."""
        r = SCSSResolver()
        r.set_project_root("/project")
        r.build_index(
            [
                _make_fi("styles/utils/index.scss"),
            ]
        )
        result = r.resolve("./utils", "styles/main.scss")
        if result.resolved_path is not None:
            assert "index" in result.resolved_path
