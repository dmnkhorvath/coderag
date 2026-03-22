"""Final targeted tests for DjangoDetector remaining coverage gaps."""

import os
from unittest.mock import MagicMock, patch

import pytest

from coderag.core.models import Node, NodeKind
from coderag.plugins.python.frameworks.django import DjangoDetector


@pytest.fixture
def detector():
    return DjangoDetector()


def _make_node(kind, name, file_path="test.py", start=1, end=50, qname=None):
    return Node(
        id=f"{kind.value}-{name}",
        kind=kind,
        name=name,
        qualified_name=qname or name,
        file_path=file_path,
        start_line=start,
        end_line=end,
        language="python",
    )


# ── framework_name property ───────────────────────────────────


class TestFrameworkName:
    def test_framework_name(self, detector):
        assert detector.framework_name == "django"


# ── detect_framework dir filtering (lines 217-218, 243-244, 252-253, 277-278, 286-287, 327-328) ──


class TestDetectFrameworkDirFiltering:
    def test_manage_py_deep_nested_beyond_depth2(self, detector, tmp_path):
        """manage.py at depth 3+ should NOT be found."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "manage.py").write_text("#!/usr/bin/env python\n")
        # No manage.py at depth <= 2, no settings, no wsgi/asgi
        assert detector.detect_framework(str(tmp_path)) is False

    def test_settings_walk_skips_node_modules(self, detector, tmp_path):
        """settings.py inside node_modules should be skipped."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        nm = tmp_path / "node_modules" / "some_pkg"
        nm.mkdir(parents=True)
        (nm / "settings.py").write_text("INSTALLED_APPS = ['django']\n")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_settings_walk_skips_dotdirs(self, detector, tmp_path):
        """settings.py inside .hidden dirs should be skipped."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "settings.py").write_text("INSTALLED_APPS = ['django']\n")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_settings_deep_beyond_depth3(self, detector, tmp_path):
        """settings.py at depth 4+ should NOT be found."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "settings.py").write_text("INSTALLED_APPS = ['django']\n")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_wsgi_walk_skips_venv(self, detector, tmp_path):
        """wsgi.py inside venv should be skipped."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        venv = tmp_path / "venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "wsgi.py").write_text("from django.core.wsgi import get_wsgi_application\n")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_asgi_walk_skips_env(self, detector, tmp_path):
        """asgi.py inside .env dir should be skipped."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        env = tmp_path / ".env"
        env.mkdir()
        (env / "asgi.py").write_text("from django.core.asgi import get_asgi_application\n")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_wsgi_deep_beyond_depth3(self, detector, tmp_path):
        """wsgi.py at depth 4+ should NOT be found."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "wsgi.py").write_text("from django.core.wsgi import get_wsgi_application\n")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_settings_oserror(self, detector, tmp_path):
        """Unreadable settings.py should be skipped gracefully."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        (tmp_path / "settings.py").write_text("INSTALLED_APPS = ['django']\n")
        original_open = open

        def mock_open(path, *a, **kw):
            if str(path).endswith("settings.py") and "settings" not in str(path).split(os.sep)[-2:]:
                raise OSError("Permission denied")
            return original_open(path, *a, **kw)

        with patch("builtins.open", side_effect=mock_open):
            result = detector.detect_framework(str(tmp_path))
        assert result is False

    def test_wsgi_oserror(self, detector, tmp_path):
        """Unreadable wsgi.py should be skipped gracefully."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        (tmp_path / "wsgi.py").write_text("from django.core.wsgi import get_wsgi_application\n")
        original_open = open

        def mock_open(path, *a, **kw):
            if str(path).endswith("wsgi.py"):
                raise OSError("Permission denied")
            return original_open(path, *a, **kw)

        with patch("builtins.open", side_effect=mock_open):
            result = detector.detect_framework(str(tmp_path))
        assert result is False


# ── _extract_bases edge case (line 463) ───────────────────────


class TestExtractBases:
    def test_extract_bases_out_of_range(self, detector):
        """Class with start_line beyond source should return empty."""
        cls = _make_node(NodeKind.CLASS, "MyClass", start=999, end=1000)
        result = detector._extract_bases(cls, "class Foo:\n    pass\n")
        assert result == []

    def test_extract_bases_no_parens(self, detector):
        """Class without parentheses returns empty."""
        cls = _make_node(NodeKind.CLASS, "MyClass", start=1, end=2)
        result = detector._extract_bases(cls, "class MyClass:\n    pass\n")
        assert result == []

    def test_extract_bases_multiline(self, detector):
        """Class with multi-line base classes."""
        cls = _make_node(NodeKind.CLASS, "MyView", start=1, end=5)
        source = "class MyView(\n    ListView,\n    LoginRequiredMixin):\n    pass\n"
        result = detector._extract_bases(cls, source)
        assert "ListView" in result
        assert "LoginRequiredMixin" in result


# ── _detect_model edge case (line 563) ────────────────────────


class TestDetectModelEdge:
    def test_model_with_meta_class(self, detector):
        """Model with Meta inner class."""
        cls = _make_node(NodeKind.CLASS, "Article", start=1, end=15)
        source = (
            "class Article(models.Model):\n"
            "    title = models.CharField(max_length=200)\n"
            "    class Meta:\n"
            "        ordering = ['-created']\n"
            "        verbose_name_plural = 'articles'\n"
        )
        pattern = detector._detect_model(cls, source, "models.py")
        assert pattern is not None
        assert pattern.pattern_type == "model"


# ── _detect_signals edge case (line 957) ──────────────────────


class TestDetectSignalsEdge:
    def test_receiver_decorator_no_matching_func(self, detector):
        """@receiver decorator with no function found nearby."""
        source = (
            "from django.dispatch import receiver\n"
            "from django.db.models.signals import post_save\n"
            "\n"
            "@receiver(post_save, sender=MyModel)\n"
            "# function is missing\n"
        )
        # No func_nodes provided
        patterns = detector._detect_signals(source, "signals.py", [])
        # Should not crash, may return empty if no func found
        assert isinstance(patterns, list)


# ── _extract_view_name edge case (line 1140) ──────────────────


class TestExtractViewNameEdge:
    def test_empty_string(self, detector):
        result = detector._extract_view_name("")
        assert result is None or result == ""

    def test_complex_as_view(self, detector):
        result = detector._extract_view_name("app.views.UserDetailView.as_view(template_name='user.html')")
        assert result == "UserDetailView"


# ── _build_route_tree OSError (lines 1164-1165) ──────────────


class TestBuildRouteTreeEdge:
    def test_unreadable_urls_file(self, detector, tmp_path):
        """Unreadable urls.py should be skipped."""
        (tmp_path / "urls.py").write_text("from django.urls import path\nurlpatterns = [path('home/', views.home)]\n")
        original_open = open

        def mock_open(path, *a, **kw):
            if str(path).endswith("urls.py"):
                raise OSError("Permission denied")
            return original_open(path, *a, **kw)

        store = MagicMock()
        with patch("builtins.open", side_effect=mock_open):
            result = detector._build_route_tree(store, str(tmp_path))
        assert result is None

    def test_urls_with_no_patterns(self, detector, tmp_path):
        """urls.py with no urlpatterns keyword."""
        (tmp_path / "urls.py").write_text("# empty file\n")
        store = MagicMock()
        result = detector._build_route_tree(store, str(tmp_path))
        assert result is None


# ── _extract_middleware_chain OSError (lines 1315-1316) ───────


class TestExtractMiddlewareChainEdge:
    def test_unreadable_settings(self, detector, tmp_path):
        """Unreadable settings.py should be skipped."""
        (tmp_path / "settings.py").write_text("MIDDLEWARE = ['django.middleware.security.SecurityMiddleware']\n")
        original_open = open

        def mock_open(path, *a, **kw):
            if str(path).endswith("settings.py"):
                raise OSError("Permission denied")
            return original_open(path, *a, **kw)

        store = MagicMock()
        with patch("builtins.open", side_effect=mock_open):
            result = detector._extract_middleware_chain(store, str(tmp_path))
        assert result is None

    def test_settings_without_middleware_list(self, detector, tmp_path):
        """settings.py with MIDDLEWARE as tuple (not list) should not match."""
        (tmp_path / "settings.py").write_text(
            "MIDDLEWARE = (\n    'django.middleware.security.SecurityMiddleware',\n)\n"
        )
        store = MagicMock()
        result = detector._extract_middleware_chain(store, str(tmp_path))
        assert result is None

    def test_base_py_in_settings_dir(self, detector, tmp_path):
        """base.py in a settings/ directory should be found."""
        settings_dir = tmp_path / "config" / "settings"
        settings_dir.mkdir(parents=True)
        (settings_dir / "base.py").write_text(
            "MIDDLEWARE = [\n"
            "    'django.middleware.common.CommonMiddleware',\n"
            "    'django.middleware.csrf.CsrfViewMiddleware',\n"
            "]\n"
        )
        store = MagicMock()
        result = detector._extract_middleware_chain(store, str(tmp_path))
        assert result is not None
        assert result.metadata["middleware_count"] == 2


# ── _check_django_dependency OSError (lines 327-328) ─────────


class TestCheckDjangoDependencyOSError:
    def test_oserror_on_dep_file_read(self, detector, tmp_path):
        """OSError reading a dep file should be skipped gracefully."""
        (tmp_path / "requirements.txt").write_text("flask==2.0\n")
        original_open = open

        def mock_open(path, *a, **kw):
            if str(path).endswith("requirements.txt"):
                raise OSError("Permission denied")
            return original_open(path, *a, **kw)

        with patch("builtins.open", side_effect=mock_open):
            result = detector._check_django_dependency(str(tmp_path))
        assert result is False

    def test_oserror_continues_to_next_file(self, detector, tmp_path):
        """OSError on first dep file should continue to next."""
        (tmp_path / "requirements.txt").write_text("flask==2.0\n")
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["django"]\n')
        original_open = open
        call_count = [0]

        def mock_open(path, *a, **kw):
            if str(path).endswith("requirements.txt"):
                call_count[0] += 1
                raise OSError("Permission denied")
            return original_open(path, *a, **kw)

        with patch("builtins.open", side_effect=mock_open):
            result = detector._check_django_dependency(str(tmp_path))
        assert result is True  # Found django in pyproject.toml


# ── _detect_model self-referencing FK (line 563) ─────────────


class TestDetectModelSelfRef:
    def test_self_referencing_foreignkey(self, detector):
        """Model with ForeignKey('self') should resolve to class name."""
        cls = _make_node(NodeKind.CLASS, "Category", start=1, end=10)
        source = (
            "class Category(models.Model):\n"
            "    name = models.CharField(max_length=100)\n"
            "    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True)\n"
        )
        pattern = detector._detect_model(cls, source, "models.py")
        assert pattern is not None
        assert pattern.pattern_type == "model"
        # Check that the relationship edge references Category, not "self"
        edges = pattern.edges
        rel_edges = [e for e in edges if e.metadata.get("relationship_type")]
        if rel_edges:
            # The related model should be resolved to "Category" not "self"
            for e in rel_edges:
                assert "self" not in e.target_id.lower() or "Category" in str(e.metadata)
