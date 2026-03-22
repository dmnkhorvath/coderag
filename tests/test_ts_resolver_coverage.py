"""Targeted tests to boost TSResolver coverage from 75% to 95%+.

Covers uncovered lines: 241, 307-313, 325-350, 376, 381, 402-403,
425-426, 432-434, 443-445, 452, 481, 487-498, 509-519, 526.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from coderag.core.models import FileInfo, Language, ResolutionResult
from coderag.plugins.typescript.resolver import TSResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fi(abs_path: str, project_root: str) -> FileInfo:
    """Create a FileInfo with correct absolute and relative paths."""
    return FileInfo(
        path=abs_path,
        relative_path=os.path.relpath(abs_path, project_root),
        language=Language.TYPESCRIPT,
        plugin_name="typescript",
        size_bytes=1,
    )


def _build_resolver(project_dir, ts_files: list[str], *, tsconfig=None, package_json=None) -> TSResolver:
    """Build a TSResolver with given files indexed."""
    root = str(project_dir)
    if package_json is not None:
        (project_dir / "package.json").write_text(json.dumps(package_json))
    if tsconfig is not None:
        (project_dir / "tsconfig.json").write_text(json.dumps(tsconfig))

    r = TSResolver()
    r.set_project_root(root)

    files = []
    for rel in ts_files:
        abs_path = os.path.join(root, rel)
        files.append(_make_fi(abs_path, root))
    r.build_index(files)
    return r


# ═══════════════════════════════════════════════════════════════════════
# Tests for _file_exists fallback (line 526)
# ═══════════════════════════════════════════════════════════════════════


class TestFileExistsFallback:
    """When _known_abs is empty, _file_exists falls back to os.path.isfile."""

    def test_file_exists_no_index(self, tmp_path):
        """Line 526: _file_exists uses os.path.isfile when no index built."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.ts").write_text("export const x = 1;")
        (tmp_path / "package.json").write_text("{}")

        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # Do NOT call build_index -> _known_abs is empty
        # Resolve a relative import that exists on disk
        result = r.resolve("./utils", "src/app.ts")
        assert result.resolved_path is not None
        assert result.resolution_strategy == "relative"

    def test_file_exists_no_index_missing_file(self, tmp_path):
        """Line 526: os.path.isfile returns False for missing file."""
        (tmp_path / "src").mkdir()
        (tmp_path / "package.json").write_text("{}")

        r = TSResolver()
        r.set_project_root(str(tmp_path))
        result = r.resolve("./nonexistent", "src/app.ts")
        assert result.resolved_path is None


# ═══════════════════════════════════════════════════════════════════════
# Tests for _load_package_json error handling (lines 402-403)
# ═══════════════════════════════════════════════════════════════════════


class TestLoadPackageJsonError:
    """Test exception handling in _load_package_json."""

    def test_corrupt_package_json(self, tmp_path):
        """Lines 402-403: malformed JSON in package.json triggers warning."""
        (tmp_path / "package.json").write_text("{invalid json!!!}")
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # Should not raise, module_type stays default
        assert r._module_type == "commonjs"

    def test_package_json_read_error(self, tmp_path):
        """Lines 402-403: I/O error reading package.json."""
        (tmp_path / "package.json").write_text("{}")
        real_open = open

        def patched_open(path, *a, **kw):
            if str(path).endswith("package.json") and str(tmp_path) in str(path):
                raise OSError("Permission denied")
            return real_open(path, *a, **kw)

        r = TSResolver()
        with patch("builtins.open", side_effect=patched_open):
            r.set_project_root(str(tmp_path))
        assert r._module_type == "commonjs"


# ═══════════════════════════════════════════════════════════════════════
# Tests for _load_tsconfig error paths (lines 425-426, 432-434, 443-445, 452)
# ═══════════════════════════════════════════════════════════════════════


class TestLoadTsconfigErrors:
    """Test tsconfig loading error paths."""

    def test_circular_extends(self, tmp_path):
        """Lines 425-426: circular extends chain detected."""
        (tmp_path / "package.json").write_text("{}")
        # A extends B, B extends A
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"extends": "./tsconfig.base.json", "compilerOptions": {"baseUrl": "."}})
        )
        (tmp_path / "tsconfig.base.json").write_text(
            json.dumps({"extends": "./tsconfig.json", "compilerOptions": {"strict": True}})
        )
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # Should not raise, just log warning
        assert isinstance(r, TSResolver)

    def test_tsconfig_read_error(self, tmp_path):
        """Lines 432-434: exception reading tsconfig file."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("{}")
        real_open = open

        call_count = 0

        def patched_open(path, *a, **kw):
            nonlocal call_count
            if str(path).endswith("tsconfig.json") and str(tmp_path) in str(path):
                call_count += 1
                if call_count >= 1:
                    raise OSError("Disk error")
            return real_open(path, *a, **kw)

        r = TSResolver()
        # _load_tsconfig checks if file exists with os.path.isfile first,
        # then calls _load_tsconfig_recursive which opens the file.
        # We need the file to exist but open to fail.
        with patch("builtins.open", side_effect=patched_open):
            r._project_root = str(tmp_path)
            r._load_tsconfig()
        assert isinstance(r, TSResolver)

    def test_tsconfig_invalid_json(self, tmp_path):
        """Lines 443-445: JSON decode error in tsconfig."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("{ this is not valid json at all !!!")
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # Should not raise
        assert r._base_url is None

    def test_extends_without_json_suffix(self, tmp_path):
        """Line 452: extends value without .json suffix gets it appended."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.base.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}})
        )
        # extends without .json suffix
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"extends": "./tsconfig.base", "compilerOptions": {"strict": True}})
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.ts").write_text("export const x = 1;")

        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # baseUrl should be loaded from parent config
        assert r._base_url is not None


# ═══════════════════════════════════════════════════════════════════════
# Tests for _apply_tsconfig paths (lines 481, 487-498)
# ═══════════════════════════════════════════════════════════════════════


class TestApplyTsconfigPaths:
    """Test various tsconfig paths patterns."""

    def test_empty_targets_skipped(self, tmp_path):
        """Line 481: paths entry with empty targets array is skipped."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@empty/*": [], "@valid/*": ["src/*"]}}})
        )
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # @empty should not be in aliases
        assert "@empty" not in r._aliases
        assert "@valid" in r._aliases

    def test_exact_alias_no_wildcard(self, tmp_path):
        """Lines 487-492: exact alias without wildcard."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"utils": ["src/utils/index"]}}})
        )
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        assert "utils" in r._exact_aliases

    def test_exact_alias_with_trailing_star(self, tmp_path):
        """Lines 490-491: exact alias target ending with *."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"mylib": ["src/lib/*"]}}})
        )
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # The trailing * should be stripped
        assert "mylib" in r._exact_aliases
        assert not r._exact_aliases["mylib"].endswith("*")

    def test_other_wildcard_pattern(self, tmp_path):
        """Lines 493-498: wildcard pattern that is not simple prefix/*."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"lib*": ["src/lib*"]}}})
        )
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # "lib*" -> prefix "lib", stored in _aliases
        assert "lib" in r._aliases

    def test_other_wildcard_empty_prefix(self, tmp_path):
        """Lines 497-498: wildcard pattern with empty prefix after split."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"*": ["src/*"]}}})
        )
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # "*" splits to prefix "" which is falsy -> not added
        assert "" not in r._aliases


# ═══════════════════════════════════════════════════════════════════════
# Tests for _try_alias (lines 376, 381)
# ═══════════════════════════════════════════════════════════════════════


class TestTryAlias:
    """Test alias resolution paths."""

    def test_exact_alias_match(self, tmp_path):
        """Line 376: exact alias match in _exact_aliases."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src" / "utils").mkdir(parents=True)
        (tmp_path / "src" / "utils" / "index.ts").write_text("export const x = 1;")
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"utils": ["src/utils/index"]}}})
        )

        abs_idx = str(tmp_path / "src" / "utils" / "index.ts")
        r = _build_resolver(
            tmp_path,
            ["src/utils/index.ts"],
            tsconfig={"compilerOptions": {"baseUrl": ".", "paths": {"utils": ["src/utils/index"]}}},
            package_json={},
        )

        result = r.resolve("utils", "src/app.ts")
        assert result.resolution_strategy == "tsconfig_paths"
        assert result.resolved_path is not None

    def test_wildcard_alias_exact_match(self, tmp_path):
        """Line 381: import_path exactly equals a wildcard prefix."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src" / "lib").mkdir(parents=True)
        (tmp_path / "src" / "lib" / "index.ts").write_text("export const x = 1;")

        r = TSResolver()
        r._project_root = str(tmp_path)
        # Manually set up alias: prefix "mylib" -> replacement path
        r._aliases["mylib"] = str(tmp_path / "src" / "lib")
        abs_idx = str(tmp_path / "src" / "lib" / "index.ts")
        r._known_abs = {os.path.normpath(abs_idx)}
        r._known_files = {abs_idx}

        # _try_alias with import_path == prefix (not prefix + "/...")
        alias_result = r._try_alias("mylib")
        assert alias_result == str(tmp_path / "src" / "lib")


# ═══════════════════════════════════════════════════════════════════════
# Tests for scoped package resolution (lines 307-313)
# ═══════════════════════════════════════════════════════════════════════


class TestScopedPackageResolution:
    """Test @scope/pkg resolution in _resolve_package."""

    def test_scoped_package_with_subpath(self, tmp_path):
        """Lines 307-310: @scope/pkg/subpath resolution."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        nm = tmp_path / "node_modules" / "@myorg" / "utils"
        nm.mkdir(parents=True)
        (nm / "helpers.ts").write_text("export const x = 1;")

        abs_helpers = str(nm / "helpers.ts")
        r = _build_resolver(tmp_path, [abs_helpers], package_json={})

        result = r.resolve("@myorg/utils/helpers", "src/app.ts")
        assert result.resolution_strategy == "node_modules"
        assert result.resolved_path is not None
        assert result.metadata["package_name"] == "@myorg/utils"

    def test_scoped_package_no_subpath(self, tmp_path):
        """Lines 308-310: @scope/pkg without subpath."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        nm = tmp_path / "node_modules" / "@myorg" / "core"
        nm.mkdir(parents=True)
        (nm / "index.ts").write_text("export const x = 1;")

        abs_idx = str(nm / "index.ts")
        r = _build_resolver(tmp_path, [abs_idx], package_json={})

        result = r.resolve("@myorg/core", "src/app.ts")
        assert result.resolution_strategy == "node_modules"
        assert result.resolved_path is not None

    def test_scoped_package_single_part(self, tmp_path):
        """Lines 311-313: @scope without /pkg (just @scope)."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()

        r = _build_resolver(tmp_path, [], package_json={})
        # "@scope" alone - only 1 part after split by "/"
        result = r.resolve("@scope", "src/app.ts")
        # Should be external (not found in node_modules)
        assert result.resolution_strategy == "external"
        assert result.metadata["package_name"] == "@scope"


# ═══════════════════════════════════════════════════════════════════════
# Tests for node_modules resolution details (lines 325-350)
# ═══════════════════════════════════════════════════════════════════════


class TestNodeModulesResolution:
    """Test node_modules resolution with subpath, main, and index."""

    def test_package_with_subpath(self, tmp_path):
        """Lines 325-333: package with subpath resolved via _resolve_relative."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        nm = tmp_path / "node_modules" / "lodash"
        nm.mkdir(parents=True)
        (nm / "fp.ts").write_text("export const fp = 1;")

        abs_fp = str(nm / "fp.ts")
        r = _build_resolver(tmp_path, [abs_fp], package_json={})

        result = r.resolve("lodash/fp", "src/app.ts")
        assert result.resolution_strategy == "node_modules"
        assert result.resolved_path is not None
        assert result.confidence == 0.85

    def test_package_with_main_entry(self, tmp_path):
        """Lines 336-345: package resolved via package.json main field."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        nm = tmp_path / "node_modules" / "mylib"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text(json.dumps({"main": "lib/index.js"}))
        (nm / "lib").mkdir()
        (nm / "lib" / "index.js").write_text("module.exports = {};")

        abs_main = str(nm / "lib" / "index.js")
        r = _build_resolver(tmp_path, [abs_main], package_json={})

        result = r.resolve("mylib", "src/app.ts")
        assert result.resolution_strategy == "node_modules"
        assert result.resolved_path is not None
        assert result.confidence == 0.85

    def test_package_with_module_entry(self, tmp_path):
        """Lines 336-345: package resolved via package.json module field."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        nm = tmp_path / "node_modules" / "eslib"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text(json.dumps({"module": "dist/esm.js"}))
        (nm / "dist").mkdir()
        (nm / "dist" / "esm.js").write_text("export default {};")

        abs_esm = str(nm / "dist" / "esm.js")
        r = _build_resolver(tmp_path, [abs_esm], package_json={})

        result = r.resolve("eslib", "src/app.ts")
        assert result.resolution_strategy == "node_modules"
        assert result.resolved_path is not None

    def test_package_with_index_fallback(self, tmp_path):
        """Lines 347-355: package resolved via index file when no main."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        nm = tmp_path / "node_modules" / "simple"
        nm.mkdir(parents=True)
        # No package.json in the package, just index.ts
        (nm / "index.ts").write_text("export const x = 1;")

        abs_idx = str(nm / "index.ts")
        r = _build_resolver(tmp_path, [abs_idx], package_json={})

        result = r.resolve("simple", "src/app.ts")
        assert result.resolution_strategy == "node_modules"
        assert result.resolved_path is not None
        assert result.confidence == 0.80

    def test_package_main_not_found_falls_to_index(self, tmp_path):
        """Lines 336-349: main entry doesn't resolve, falls through to index."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        nm = tmp_path / "node_modules" / "broken"
        nm.mkdir(parents=True)
        # package.json points to nonexistent main
        (nm / "package.json").write_text(json.dumps({"main": "nonexistent.js"}))
        (nm / "index.ts").write_text("export const x = 1;")

        abs_idx = str(nm / "index.ts")
        r = _build_resolver(tmp_path, [abs_idx], package_json={})

        result = r.resolve("broken", "src/app.ts")
        assert result.resolution_strategy == "node_modules"
        assert result.resolved_path is not None


# ═══════════════════════════════════════════════════════════════════════
# Tests for _read_package_main (lines 509-519)
# ═══════════════════════════════════════════════════════════════════════


class TestReadPackageMain:
    """Test _read_package_main method."""

    def test_no_package_json(self, tmp_path):
        """Line 510: no package.json in directory."""
        r = TSResolver()
        assert r._read_package_main(str(tmp_path)) is None

    def test_valid_main_field(self, tmp_path):
        """Lines 512-517: reads main field from package.json."""
        (tmp_path / "package.json").write_text(json.dumps({"main": "index.js"}))
        r = TSResolver()
        assert r._read_package_main(str(tmp_path)) == "index.js"

    def test_module_field_preferred(self, tmp_path):
        """Lines 517: module field preferred over main."""
        (tmp_path / "package.json").write_text(json.dumps({"main": "dist/cjs.js", "module": "dist/esm.js"}))
        r = TSResolver()
        assert r._read_package_main(str(tmp_path)) == "dist/esm.js"

    def test_types_field(self, tmp_path):
        """Lines 517: types field returned when no module/main."""
        (tmp_path / "package.json").write_text(json.dumps({"types": "index.d.ts"}))
        r = TSResolver()
        assert r._read_package_main(str(tmp_path)) == "index.d.ts"

    def test_corrupt_package_json(self, tmp_path):
        """Lines 518-519: exception reading package.json returns None."""
        (tmp_path / "package.json").write_text("{invalid json!!!}")
        r = TSResolver()
        assert r._read_package_main(str(tmp_path)) is None

    def test_no_entry_fields(self, tmp_path):
        """Lines 517: no module/main/types/typings returns None."""
        (tmp_path / "package.json").write_text(json.dumps({"name": "empty"}))
        r = TSResolver()
        assert r._read_package_main(str(tmp_path)) is None


# ═══════════════════════════════════════════════════════════════════════
# Tests for unresolved bare import (line 241)
# ═══════════════════════════════════════════════════════════════════════


class TestUnresolvedBareImport:
    """Line 241: bare import where _resolve_package returns None."""

    def test_resolve_package_returns_none(self, tmp_path):
        """Line 241: when _resolve_package returns None, resolve returns unresolved."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()

        r = _build_resolver(tmp_path, [], package_json={})

        # Mock _resolve_package to return None (normally it returns external)
        with patch.object(r, "_resolve_package", return_value=None):
            result = r.resolve("some-package", "src/app.ts")
        assert result.resolution_strategy == "unresolved"
        assert result.confidence == 0.0
        assert result.resolved_path is None


# ═══════════════════════════════════════════════════════════════════════
# Integration: tsconfig extends chain with baseUrl inheritance
# ═══════════════════════════════════════════════════════════════════════


class TestTsconfigExtendsIntegration:
    """Integration tests for tsconfig extends chain."""

    def test_extends_merges_compiler_options(self, tmp_path):
        """Test that child tsconfig merges with parent."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.base.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@base/*": ["base/*"]}}})
        )
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"extends": "./tsconfig.base", "compilerOptions": {"paths": {"@app/*": ["src/*"]}}})
        )

        r = TSResolver()
        r.set_project_root(str(tmp_path))
        # Child paths should override parent paths
        assert "@app" in r._aliases
        # baseUrl from parent should be inherited
        assert r._base_url is not None

    def test_extends_with_comments_and_trailing_commas(self, tmp_path):
        """Test tsconfig with comments and trailing commas."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("""
{
    // This is a comment
    "compilerOptions": {
        "baseUrl": ".",
        /* block comment */
        "paths": {
            "@/*": ["src/*"],
        },
    },
}
""")
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        assert r._base_url is not None
        assert "@" in r._aliases


# ═══════════════════════════════════════════════════════════════════════
# Tests for remaining uncovered lines
# ═══════════════════════════════════════════════════════════════════════


class TestBaseUrlResolution:
    """Lines 209-211: baseUrl resolution success."""

    def test_base_url_resolves_non_relative(self, tmp_path):
        """Lines 209-211: non-relative import resolved via baseUrl."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.ts").write_text("export const x = 1;")
        (tmp_path / "tsconfig.json").write_text(json.dumps({"compilerOptions": {"baseUrl": "."}}))

        abs_utils = str(tmp_path / "src" / "utils.ts")
        r = _build_resolver(tmp_path, ["src/utils.ts"], tsconfig={"compilerOptions": {"baseUrl": "."}}, package_json={})

        result = r.resolve("src/utils", "src/app.ts")
        assert result.resolution_strategy == "base_url"
        assert result.resolved_path is not None
        assert result.confidence == 0.85


class TestResolveSymbol:
    """Line 254: resolve_symbol delegates to resolve."""

    def test_resolve_symbol_delegates(self, tmp_path):
        """Line 254: resolve_symbol calls resolve."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.ts").write_text("export const x = 1;")

        r = _build_resolver(tmp_path, ["src/utils.ts"], package_json={})
        result = r.resolve_symbol("./utils", "src/app.ts")
        assert isinstance(result, ResolutionResult)


class TestDirectoryIndexResolution:
    """Lines 290-293: directory with index file resolution."""

    def test_directory_resolves_to_index(self, tmp_path):
        """Lines 290-293: import of directory resolves to index.ts."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src" / "utils").mkdir(parents=True)
        (tmp_path / "src" / "utils" / "index.ts").write_text("export const x = 1;")

        abs_idx = str(tmp_path / "src" / "utils" / "index.ts")
        r = _build_resolver(tmp_path, [abs_idx], package_json={})

        result = r.resolve("./utils", "src/app.ts")
        assert result.resolved_path is not None
        assert "index" in result.resolved_path
        assert result.resolution_strategy == "relative"


class TestWildcardAliasPrefixSlash:
    """Lines 382-384: wildcard alias with prefix + "/" match."""

    def test_wildcard_alias_with_subpath(self, tmp_path):
        """Lines 382-384: import_path starts with prefix + "/"."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src" / "components").mkdir(parents=True)
        (tmp_path / "src" / "components" / "Button.ts").write_text("export default {};")
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}})
        )

        abs_btn = str(tmp_path / "src" / "components" / "Button.ts")
        r = _build_resolver(
            tmp_path,
            [abs_btn],
            tsconfig={"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}},
            package_json={},
        )

        result = r.resolve("@/components/Button", "src/app.ts")
        assert result.resolution_strategy == "tsconfig_paths"
        assert result.resolved_path is not None


class TestNoPackageJson:
    """Line 393: no package.json file."""

    def test_no_package_json(self, tmp_path):
        """Line 393: _load_package_json returns early when no package.json."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("export const x = 1;")
        # No package.json
        r = TSResolver()
        r.set_project_root(str(tmp_path))
        assert r._module_type == "commonjs"  # default


class TestBuiltinNodePrefix:
    """Line 188: builtin with node: prefix."""

    def test_node_prefix_builtin(self, tmp_path):
        """Line 188: node:fs resolves as builtin."""
        (tmp_path / "package.json").write_text("{}")
        r = _build_resolver(tmp_path, [], package_json={})
        result = r.resolve("node:fs", "src/app.ts")
        assert result.resolution_strategy == "builtin"
        assert result.confidence == 1.0
        assert result.metadata["package_name"] == "fs"
        assert result.metadata["is_external"] is True
