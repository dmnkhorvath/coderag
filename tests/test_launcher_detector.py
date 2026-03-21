"""Tests for coderag.launcher.detector module."""

from __future__ import annotations

import time

import pytest

from coderag.launcher.detector import (
    ProjectState,
    ProjectStateInfo,
    _find_source_files,
    detect_project_state,
)


@pytest.fixture
def fresh_project(tmp_path):
    """Create a project with source files but no database."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.php").write_text("<?php echo 'hello';")
    (tmp_path / "src" / "utils.js").write_text("export default {};")
    (tmp_path / "src" / "types.ts").write_text("export type Foo = string;")
    return tmp_path


@pytest.fixture
def ready_project(tmp_path):
    """Create a project with source files and a current database."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.php").write_text("<?php echo 'hello';")
    (tmp_path / "src" / "utils.js").write_text("export default {};")

    # Create database that is newer than source files
    time.sleep(0.05)
    db_dir = tmp_path / ".codegraph"
    db_dir.mkdir()
    (db_dir / "graph.db").write_text("fake-db")
    return tmp_path


@pytest.fixture
def stale_project(tmp_path):
    """Create a project where source files are newer than the database."""
    # Create database first
    db_dir = tmp_path / ".codegraph"
    db_dir.mkdir()
    (db_dir / "graph.db").write_text("fake-db")

    # Wait and create source files (newer than db)
    time.sleep(0.05)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.php").write_text("<?php echo 'hello';")
    (tmp_path / "src" / "utils.js").write_text("export default {};")
    return tmp_path


class TestProjectState:
    """Test ProjectState enum."""

    def test_enum_values(self):
        assert ProjectState.FRESH == "fresh"
        assert ProjectState.STALE == "stale"
        assert ProjectState.READY == "ready"

    def test_enum_members(self):
        assert len(ProjectState) == 3


class TestProjectStateInfo:
    """Test ProjectStateInfo dataclass."""

    def test_defaults(self):
        info = ProjectStateInfo(
            state=ProjectState.FRESH,
            db_path="/tmp/test/.codegraph/graph.db",
            db_exists=False,
        )
        assert info.state == ProjectState.FRESH
        assert info.db_mtime is None
        assert info.source_file_count == 0
        assert info.newest_source_mtime is None
        assert info.stale_files == []

    def test_full_init(self):
        info = ProjectStateInfo(
            state=ProjectState.STALE,
            db_path="/tmp/test/.codegraph/graph.db",
            db_exists=True,
            db_mtime=1000.0,
            source_file_count=5,
            newest_source_mtime=2000.0,
            stale_files=["a.php", "b.js"],
        )
        assert info.source_file_count == 5
        assert len(info.stale_files) == 2


class TestFindSourceFiles:
    """Test _find_source_files helper."""

    def test_finds_source_files(self, fresh_project):
        files = _find_source_files(str(fresh_project))
        assert len(files) == 3
        paths = [f[0] for f in files]
        assert any("app.php" in p for p in paths)
        assert any("utils.js" in p for p in paths)
        assert any("types.ts" in p for p in paths)

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {};")
        (tmp_path / "app.js").write_text("import x from 'pkg';")
        files = _find_source_files(str(tmp_path))
        assert len(files) == 1
        assert "app.js" in files[0][0]

    def test_skips_vendor(self, tmp_path):
        vendor = tmp_path / "vendor" / "pkg"
        vendor.mkdir(parents=True)
        (vendor / "lib.php").write_text("<?php")
        (tmp_path / "app.php").write_text("<?php")
        files = _find_source_files(str(tmp_path))
        assert len(files) == 1

    def test_skips_git_dir(self, tmp_path):
        git = tmp_path / ".git" / "hooks"
        git.mkdir(parents=True)
        (git / "pre-commit.py").write_text("#!/usr/bin/env python")
        files = _find_source_files(str(tmp_path))
        assert len(files) == 0

    def test_empty_directory(self, tmp_path):
        files = _find_source_files(str(tmp_path))
        assert files == []

    def test_non_source_files_ignored(self, tmp_path):
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "data.json").write_text("{}")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        files = _find_source_files(str(tmp_path))
        assert len(files) == 0

    def test_returns_mtimes(self, fresh_project):
        files = _find_source_files(str(fresh_project))
        for rel_path, mtime in files:
            assert isinstance(mtime, float)
            assert mtime > 0


class TestDetectProjectState:
    """Test detect_project_state function."""

    def test_fresh_project(self, fresh_project):
        info = detect_project_state(str(fresh_project))
        assert info.state == ProjectState.FRESH
        assert info.db_exists is False
        assert info.source_file_count == 3
        assert info.db_mtime is None

    def test_ready_project(self, ready_project):
        info = detect_project_state(str(ready_project))
        assert info.state == ProjectState.READY
        assert info.db_exists is True
        assert info.source_file_count == 2
        assert info.db_mtime is not None

    def test_stale_project(self, stale_project):
        info = detect_project_state(str(stale_project))
        assert info.state == ProjectState.STALE
        assert info.db_exists is True
        assert len(info.stale_files) > 0
        assert info.source_file_count == 2

    def test_empty_directory(self, tmp_path):
        info = detect_project_state(str(tmp_path))
        assert info.state == ProjectState.FRESH
        assert info.source_file_count == 0

    def test_db_with_no_source_files(self, tmp_path):
        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        (db_dir / "graph.db").write_text("fake-db")
        info = detect_project_state(str(tmp_path))
        assert info.state == ProjectState.READY
        assert info.source_file_count == 0

    def test_custom_db_path(self, tmp_path):
        (tmp_path / "app.php").write_text("<?php")
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "my.db").write_text("fake-db")
        info = detect_project_state(str(tmp_path), db_relative="custom/my.db")
        # Source file is newer than db (created after)
        assert info.db_exists is True

    def test_db_path_in_info(self, fresh_project):
        info = detect_project_state(str(fresh_project))
        assert ".codegraph/graph.db" in info.db_path

    def test_stale_files_capped(self, tmp_path):
        """Stale files list is capped at 50."""
        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        (db_dir / "graph.db").write_text("fake-db")
        time.sleep(0.05)
        src = tmp_path / "src"
        src.mkdir()
        for i in range(60):
            (src / f"file_{i}.php").write_text(f"<?php // {i}")
        info = detect_project_state(str(tmp_path))
        assert info.state == ProjectState.STALE
        assert len(info.stale_files) <= 50
        assert info.source_file_count == 60
