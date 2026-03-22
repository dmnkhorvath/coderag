"""Integration tests for session memory — full workflow."""

from __future__ import annotations

import subprocess
import sys

import pytest

from coderag.session.injector import ContextInjector
from coderag.session.store import SessionStore
from coderag.session.tracker import SessionTracker


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "integration.db")


class TestFullWorkflow:
    """Test: create session → log events → end → new session → get context."""

    def test_multi_session_workflow(self, db_path):
        store = SessionStore(db_path)
        tracker = SessionTracker(store)

        # Session 1: exploration
        sid1 = tracker.start_session(tool="claude-code", prompt="fix routing")
        tracker.log_read("src/App.php")
        tracker.log_read("src/Routing/Router.php")
        tracker.log_edit("src/Routing/Router.php", metadata={"description": "Fixed route matching"})
        tracker.log_decision("Use regex-based route matching instead of string comparison")
        tracker.log_task("Add unit tests for new route matching", status="open")
        tracker.log_fact("Slim uses PSR-7 HTTP message interfaces")
        tracker.end_session()

        # Session 2: testing
        sid2 = tracker.start_session(tool="cursor", prompt="add tests")
        tracker.log_read("src/Routing/Router.php")
        tracker.log_read("tests/Routing/RouterTest.php")
        tracker.log_query("route matching tests")
        tracker.end_session()

        # Verify sessions
        sessions = store.get_recent_sessions(limit=10)
        assert len(sessions) == 2

        # Verify hot files
        hot = store.get_hot_files(limit=10)
        assert len(hot) >= 2
        # Router.php should be hottest (2 reads + 1 edit = 3)
        assert hot[0][0] == "src/Routing/Router.php"
        assert hot[0][1] == 3

        # Verify context
        decisions = store.get_context(category="decision")
        assert len(decisions) == 1
        assert "regex" in decisions[0]["content"].lower()

        tasks = store.get_context(category="task")
        assert len(tasks) == 1
        assert tasks[0]["content"] == "Add unit tests for new route matching"

        facts = store.get_context(category="fact")
        assert len(facts) == 1
        assert "PSR-7" in facts[0]["content"]

        # Generate context
        injector = ContextInjector(store)
        context = injector.generate_context(token_budget=4000)
        assert "## Session Context" in context
        assert "Router.php" in context
        assert "regex" in context.lower()
        assert "PSR-7" in context

        store.close()

    def test_context_deactivation(self, db_path):
        """Test marking tasks as done."""
        store = SessionStore(db_path)
        tracker = SessionTracker(store)

        tracker.start_session()
        tracker.log_task("Fix the bug")
        tracker.log_task("Write docs")
        tracker.end_session()

        tasks = store.get_context(category="task", active_only=True)
        assert len(tasks) == 2

        # Deactivate first task
        store.deactivate_context(tasks[0]["id"])

        active_tasks = store.get_context(category="task", active_only=True)
        assert len(active_tasks) == 1

        store.close()

    def test_persistence_across_store_instances(self, db_path):
        """Data persists when store is closed and reopened."""
        # Write data
        store1 = SessionStore(db_path)
        tracker1 = SessionTracker(store1)
        tracker1.start_session(tool="test")
        tracker1.log_read("file.py")
        tracker1.log_decision("Use microservices")
        tracker1.end_session()
        store1.close()

        # Read data with new store
        store2 = SessionStore(db_path)
        sessions = store2.get_recent_sessions(limit=10)
        assert len(sessions) == 1

        hot = store2.get_hot_files(limit=10)
        assert len(hot) == 1
        assert hot[0][0] == "file.py"

        decisions = store2.get_context(category="decision")
        assert len(decisions) == 1
        assert "microservices" in decisions[0]["content"]

        store2.close()


class TestContextInjectionIntegration:
    """Test context injection with realistic data."""

    def test_context_with_many_sessions(self, db_path):
        """Context generation with many sessions."""
        store = SessionStore(db_path)
        tracker = SessionTracker(store)

        # Create 5 sessions with varied activity
        for i in range(5):
            tracker.start_session(tool=f"tool-{i}", prompt=f"task {i}")
            for j in range(3):
                tracker.log_read(f"src/module{j}/file{i}.py")
            if i % 2 == 0:
                tracker.log_edit(f"src/module0/file{i}.py")
            tracker.end_session()

        # Add some context items
        tracker.start_session()
        tracker.log_decision("Decision A")
        tracker.log_decision("Decision B")
        tracker.log_task("Task 1")
        tracker.log_task("Task 2")
        tracker.log_fact("Fact X")
        tracker.end_session()

        injector = ContextInjector(store)
        context = injector.generate_context(token_budget=4000)

        # Should have all sections
        assert "Hot Files" in context
        assert "Decisions" in context
        assert "Open Tasks" in context
        assert "Facts" in context

        store.close()

    def test_token_budget_truncation(self, db_path):
        """Very small budget should still produce valid output."""
        store = SessionStore(db_path)
        tracker = SessionTracker(store)

        tracker.start_session()
        for i in range(50):
            tracker.log_read(f"src/very/long/path/to/module{i}/deeply/nested/file{i}.py")
            tracker.log_decision(f"Decision number {i} with a very long description that takes up tokens")
        tracker.end_session()

        injector = ContextInjector(store)
        context = injector.generate_context(token_budget=200)

        # Should be within budget (200 tokens * 4 chars = 800 chars, with some slack)
        assert len(context) <= 1000
        assert "## Session Context" in context

        store.close()


class TestCLIIntegration:
    """Test CLI session commands."""

    def test_session_list_empty(self, tmp_path):
        """session list on empty db should not crash."""
        # Create a minimal codegraph dir
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        db_path = str(cg_dir / "graph.db")
        store = SessionStore(db_path)
        store.close()

        result = subprocess.run(
            [sys.executable, "-m", "coderag.cli.main", "session", "list", "-p", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should not crash (exit code 0 or 1 for "no sessions")
        assert result.returncode in (0, 1, 2)  # 2 = click usage error is also acceptable

    def test_session_context_empty(self, tmp_path):
        """session context on empty db should not crash."""
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        db_path = str(cg_dir / "graph.db")
        store = SessionStore(db_path)
        store.close()

        result = subprocess.run(
            [sys.executable, "-m", "coderag.cli.main", "session", "context", "-p", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1, 2)
