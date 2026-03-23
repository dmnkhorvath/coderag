"""Tests for FileScanner — targeting uncovered lines 64, 75-77, 135, 140, 142."""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from coderag.core.models import FileInfo
from coderag.pipeline.scanner import FileScanner, DEFAULT_IGNORE_PATTERNS


class TestScanIgnoredFiles:
    """Cover line 64: continue when file matches ignore pattern."""

    def test_ignored_file_is_skipped(self, tmp_path):
        """A file matching an ignore pattern should not appear in results."""
        # Create a .min.js file which matches DEFAULT_IGNORE_PATTERNS
        src = tmp_path / "app.min.js"
        src.write_text("var x = 1;")
        # Also create a normal file
        normal = tmp_path / "app.js"
        normal.write_text("var y = 2;")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".js"]),
        )
        results = scanner.scan()
        paths = [fi.relative_path for fi in results]
        assert "app.js" in paths
        assert "app.min.js" not in paths

    def test_custom_ignore_pattern(self, tmp_path):
        """Custom ignore patterns should filter files."""
        (tmp_path / "keep.py").write_text("x = 1")
        (tmp_path / "skip_me.py").write_text("x = 2")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=["skip_*"],
        )
        results = scanner.scan()
        names = [fi.relative_path for fi in results]
        assert "keep.py" in names
        assert "skip_me.py" not in names


class TestScanUnreadableFile:
    """Cover lines 75-77: exception when reading a file."""

    def test_unreadable_file_is_skipped(self, tmp_path):
        """Files that raise on read should be skipped with a warning."""
        good = tmp_path / "good.py"
        good.write_text("x = 1")
        bad = tmp_path / "bad.py"
        bad.write_text("y = 2")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=[],
        )

        original_read = FileScanner._read_file

        @staticmethod
        def patched_read(path):
            if "bad.py" in path:
                raise PermissionError("Cannot read")
            return original_read(path)

        with patch.object(FileScanner, "_read_file", patched_read):
            results = scanner.scan()

        names = [fi.relative_path for fi in results]
        assert "good.py" in names
        assert "bad.py" not in names


class TestScanIncremental:
    """Cover lines 135, 140, 142: scan_incremental logic."""

    def test_unchanged_file_marked_not_changed(self, tmp_path):
        """When stored hash matches, file should be marked is_changed=False."""
        f = tmp_path / "main.py"
        f.write_text("hello")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=[],
        )

        # First scan to get the hash
        initial = scanner.scan()
        assert len(initial) == 1
        real_hash = initial[0].content_hash

        # Simulate stored hash matching
        def get_stored_hash(path):
            return real_hash

        results = scanner.scan_incremental(get_stored_hash)
        assert len(results) == 1
        assert results[0].is_changed is False

    def test_new_file_marked_changed(self, tmp_path):
        """When stored hash is None (new file), file should be is_changed=True."""
        f = tmp_path / "new.py"
        f.write_text("new content")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=[],
        )

        def get_stored_hash(path):
            return None  # New file, no stored hash

        results = scanner.scan_incremental(get_stored_hash)
        assert len(results) == 1
        assert results[0].is_changed is True

    def test_changed_file_marked_changed(self, tmp_path):
        """When stored hash differs, file should be is_changed=True."""
        f = tmp_path / "mod.py"
        f.write_text("original")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=[],
        )

        def get_stored_hash(path):
            return "old_hash_that_doesnt_match"

        results = scanner.scan_incremental(get_stored_hash)
        assert len(results) == 1
        assert results[0].is_changed is True

    def test_mixed_changed_and_unchanged(self, tmp_path):
        """Mix of changed and unchanged files."""
        f1 = tmp_path / "a.py"
        f1.write_text("aaa")
        f2 = tmp_path / "b.py"
        f2.write_text("bbb")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=[],
        )

        # Get real hashes
        initial = scanner.scan()
        hash_map = {fi.path: fi.content_hash for fi in initial}

        # Only return hash for first file (second is "new")
        first_path = sorted(hash_map.keys())[0]

        def get_stored_hash(path):
            if path == first_path:
                return hash_map[path]
            return None

        results = scanner.scan_incremental(get_stored_hash)
        assert len(results) == 2
        changed = [fi for fi in results if fi.is_changed]
        unchanged = [fi for fi in results if not fi.is_changed]
        assert len(changed) == 1
        assert len(unchanged) == 1



class TestIsIgnoredPathComponents:
    """Cover lines 135, 140, 142: path component matching in _is_ignored."""

    def test_directory_pattern_matches_path_component(self, tmp_path):
        """Line 135: fnmatch(part + '/', pattern) matches directory patterns."""
        # Create a file inside a 'vendor' directory
        vendor_dir = tmp_path / "vendor"
        vendor_dir.mkdir()
        f = vendor_dir / "lib.py"
        f.write_text("x = 1")

        # Also create a file NOT in vendor
        normal = tmp_path / "main.py"
        normal.write_text("y = 2")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=["vendor/"],  # Directory pattern with trailing slash
        )
        results = scanner.scan()
        paths = [fi.relative_path for fi in results]
        assert "main.py" in paths
        # vendor/lib.py should be ignored because 'vendor' + '/' matches 'vendor/'
        assert not any("vendor" in p for p in paths)

    def test_wildcard_directory_pattern(self, tmp_path):
        """Line 140: fnmatch(part, pattern.rstrip('/').rstrip('/*')) matches."""
        # Create a file inside a 'build' directory
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        f = build_dir / "output.py"
        f.write_text("x = 1")

        normal = tmp_path / "src.py"
        normal.write_text("y = 2")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=["build/*"],  # Wildcard directory pattern
        )
        results = scanner.scan()
        paths = [fi.relative_path for fi in results]
        assert "src.py" in paths
        assert not any("build" in p for p in paths)

    def test_no_pattern_matches_returns_false(self, tmp_path):
        """Line 142: return False when no pattern matches."""
        f = tmp_path / "normal.py"
        f.write_text("x = 1")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=["*.js", "dist/", "node_modules/"],
        )
        results = scanner.scan()
        paths = [fi.relative_path for fi in results]
        assert "normal.py" in paths  # Not ignored

    def test_nested_directory_pattern(self, tmp_path):
        """Test deeply nested path component matching."""
        nested = tmp_path / "src" / "__pycache__"
        nested.mkdir(parents=True)
        f = nested / "module.py"
        f.write_text("x = 1")

        normal = tmp_path / "src" / "main.py"
        normal.write_text("y = 2")

        scanner = FileScanner(
            project_root=str(tmp_path),
            extensions=frozenset([".py"]),
            ignore_patterns=["__pycache__/"],
        )
        results = scanner.scan()
        paths = [fi.relative_path for fi in results]
        assert any("main.py" in p for p in paths)
        assert not any("__pycache__" in p for p in paths)
