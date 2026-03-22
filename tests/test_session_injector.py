"""Tests for ContextInjector — markdown context generation."""

from __future__ import annotations

import pytest

from coderag.session.injector import ContextInjector, _estimate_tokens
from coderag.session.store import SessionStore
from coderag.session.tracker import SessionTracker


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SessionStore(db_path)
    yield s
    s.close()


@pytest.fixture
def injector(store):
    return ContextInjector(store)


@pytest.fixture
def populated_store(store):
    """Store with sample session data."""
    tracker = SessionTracker(store)

    # Session 1
    tracker.start_session(tool="claude-code", prompt="fix routing")
    tracker.log_read("src/auth/login.py")
    tracker.log_read("src/auth/login.py")
    tracker.log_edit("src/auth/login.py")
    tracker.log_read("src/models/user.py")
    tracker.log_decision("Use JWT tokens instead of session cookies")
    tracker.log_task("Add rate limiting to login endpoint")
    tracker.log_fact("The project uses PostgreSQL 15 in production")
    tracker.end_session()

    # Session 2
    tracker.start_session(tool="cursor", prompt="add tests")
    tracker.log_read("src/auth/login.py")
    tracker.log_read("tests/test_login.py")
    tracker.log_query("authentication flow")
    tracker.end_session()

    return store


class TestEstimateTokens:
    def test_basic(self):
        assert _estimate_tokens("hello world") == 2  # 11 chars / 4 = 2

    def test_empty(self):
        assert _estimate_tokens("") == 1  # min 1

    def test_long(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100


class TestContextGeneration:
    def test_generates_markdown(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=4000)
        assert "## Session Context" in context

    def test_includes_hot_files(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=4000)
        assert "Hot Files" in context
        assert "src/auth/login.py" in context

    def test_includes_decisions(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=4000)
        assert "Decisions" in context
        assert "JWT tokens" in context

    def test_includes_tasks(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=4000)
        assert "Open Tasks" in context
        assert "rate limiting" in context

    def test_includes_facts(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=4000)
        assert "Facts" in context
        assert "PostgreSQL" in context

    def test_includes_recent_activity(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=4000)
        assert "Recent Activity" in context


class TestTokenBudget:
    def test_respects_budget(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=100)
        # 100 tokens * 4 chars = 400 chars max
        assert len(context) <= 500  # some slack for truncation message

    def test_large_budget(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=10000)
        assert "## Session Context" in context

    def test_tiny_budget(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=10)
        # Should still produce something
        assert len(context) > 0


class TestEmptyDatabase:
    def test_empty_produces_header(self, injector):
        context = injector.generate_context(token_budget=4000)
        assert "## Session Context" in context

    def test_empty_no_sections(self, injector):
        context = injector.generate_context(token_budget=4000)
        assert "Hot Files" not in context
        assert "Decisions" not in context
        assert "Open Tasks" not in context


class TestSectionPriority:
    def test_hot_files_before_decisions(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=4000)
        hot_pos = context.find("Hot Files")
        dec_pos = context.find("Decisions")
        if hot_pos >= 0 and dec_pos >= 0:
            assert hot_pos < dec_pos

    def test_decisions_before_tasks(self, populated_store):
        injector = ContextInjector(populated_store)
        context = injector.generate_context(token_budget=4000)
        dec_pos = context.find("Decisions")
        task_pos = context.find("Open Tasks")
        if dec_pos >= 0 and task_pos >= 0:
            assert dec_pos < task_pos


class TestOnlyOneCategory:
    def test_only_decisions(self, store):
        tracker = SessionTracker(store)
        tracker.start_session()
        tracker.log_decision("Use microservices")
        tracker.end_session()

        injector = ContextInjector(store)
        context = injector.generate_context(token_budget=4000)
        assert "Decisions" in context
        assert "Use microservices" in context

    def test_only_tasks(self, store):
        tracker = SessionTracker(store)
        tracker.start_session()
        tracker.log_task("Fix the bug")
        tracker.end_session()

        injector = ContextInjector(store)
        context = injector.generate_context(token_budget=4000)
        assert "Open Tasks" in context
        assert "Fix the bug" in context

    def test_only_facts(self, store):
        tracker = SessionTracker(store)
        tracker.start_session()
        tracker.log_fact("Uses Redis for caching")
        tracker.end_session()

        injector = ContextInjector(store)
        context = injector.generate_context(token_budget=4000)
        assert "Facts" in context
        assert "Redis" in context
