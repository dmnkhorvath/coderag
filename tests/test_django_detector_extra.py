"""Extra tests for DjangoDetector to cover remaining gaps."""

import os
from unittest.mock import MagicMock

import pytest

from coderag.core.models import (
    EdgeKind,
    Node,
    NodeKind,
)
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


# ── detect_framework edge cases ───────────────────────────────


class TestDetectFrameworkEdgeCases:
    def test_settings_py_with_installed_apps(self, detector, tmp_path):
        """Detect via settings.py containing INSTALLED_APPS."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        sub = tmp_path / "myproject"
        sub.mkdir()
        (sub / "settings.py").write_text("INSTALLED_APPS = ['django.contrib.admin']\n")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_wsgi_py_with_django(self, detector, tmp_path):
        """Detect via wsgi.py containing django reference."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        sub = tmp_path / "myproject"
        sub.mkdir()
        (sub / "wsgi.py").write_text(
            'import os\nos.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")\n'
            "from django.core.wsgi import get_wsgi_application\n"
            "application = get_wsgi_application()\n"
        )
        assert detector.detect_framework(str(tmp_path)) is True

    def test_asgi_py_with_django(self, detector, tmp_path):
        """Detect via asgi.py containing django reference."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        sub = tmp_path / "myproject"
        sub.mkdir()
        (sub / "asgi.py").write_text(
            "from django.core.asgi import get_asgi_application\napplication = get_asgi_application()\n"
        )
        assert detector.detect_framework(str(tmp_path)) is True

    def test_manage_py_nested(self, detector, tmp_path):
        """Detect manage.py nested up to depth 2."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        sub = tmp_path / "level1" / "level2"
        sub.mkdir(parents=True)
        (sub / "manage.py").write_text("#!/usr/bin/env python\n")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_no_django_dep_returns_false(self, detector, tmp_path):
        """No django dependency means False even with manage.py."""
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        (tmp_path / "requirements.txt").write_text("flask==2.0\n")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_settings_without_installed_apps(self, detector, tmp_path):
        """settings.py without INSTALLED_APPS should not match."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        sub = tmp_path / "myproject"
        sub.mkdir()
        (sub / "settings.py").write_text("DEBUG = True\n")
        # No manage.py, no INSTALLED_APPS, no wsgi/asgi
        assert detector.detect_framework(str(tmp_path)) is False

    def test_wsgi_without_django_ref(self, detector, tmp_path):
        """wsgi.py without django reference should not match."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        sub = tmp_path / "myproject"
        sub.mkdir()
        (sub / "wsgi.py").write_text("from gunicorn import app\n")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_dep_in_pyproject_toml(self, detector, tmp_path):
        """Detect django in pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["django>=4.2"]\n')
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_dep_in_pipfile(self, detector, tmp_path):
        """Detect django in Pipfile."""
        (tmp_path / "Pipfile").write_text('[packages]\ndjango = "*"\n')
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_skips_venv_dirs(self, detector, tmp_path):
        """Should skip venv directories during walk."""
        (tmp_path / "requirements.txt").write_text("django==4.2\n")
        venv = tmp_path / "venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "manage.py").write_text("#!/usr/bin/env python\n")
        # No manage.py outside venv
        assert detector.detect_framework(str(tmp_path)) is False


# ── _check_django_dependency ──────────────────────────────────


class TestCheckDjangoDependency:
    def test_requirements_base(self, detector, tmp_path):
        reqs = tmp_path / "requirements"
        reqs.mkdir()
        (reqs / "base.txt").write_text("django==4.2\n")
        assert detector._check_django_dependency(str(tmp_path)) is True

    def test_setup_py(self, detector, tmp_path):
        (tmp_path / "setup.py").write_text('install_requires=["django>=4.2"]\n')
        assert detector._check_django_dependency(str(tmp_path)) is True

    def test_setup_cfg(self, detector, tmp_path):
        (tmp_path / "setup.cfg").write_text("[options]\ninstall_requires = django>=4.2\n")
        assert detector._check_django_dependency(str(tmp_path)) is True

    def test_no_dep_files(self, detector, tmp_path):
        assert detector._check_django_dependency(str(tmp_path)) is False


# ── _is_middleware_class edge cases ───────────────────────────


class TestIsMiddlewareClass:
    def test_middleware_by_name_with_call(self, detector):
        """Class with 'Middleware' in name and __call__ method."""
        cls = _make_node(NodeKind.CLASS, "CorsMiddleware", "middleware.py", 1, 30)
        call_method = _make_node(NodeKind.METHOD, "__call__", "middleware.py", 5, 20)
        assert detector._is_middleware_class(cls, [call_method], "") is True

    def test_middleware_by_path_with_init(self, detector):
        """Class in middleware.py path with __init__ method."""
        cls = _make_node(NodeKind.CLASS, "MyHandler", "app/middleware.py", 1, 30)
        init_method = _make_node(NodeKind.METHOD, "__init__", "app/middleware.py", 5, 20)
        assert detector._is_middleware_class(cls, [init_method], "") is True

    def test_not_middleware_no_methods(self, detector):
        """Class with Middleware in name but no __call__ or __init__."""
        cls = _make_node(NodeKind.CLASS, "MiddlewareConfig", "config.py", 1, 30)
        assert detector._is_middleware_class(cls, [], "") is False

    def test_middleware_by_process_request(self, detector):
        """Class with process_request method."""
        cls = _make_node(NodeKind.CLASS, "MyClass", "app.py", 1, 30)
        method = _make_node(NodeKind.METHOD, "process_request", "app.py", 5, 20)
        assert detector._is_middleware_class(cls, [method], "") is True


# ── _detect_signals - signal.connect() ────────────────────────


class TestDetectSignals:
    def test_signal_connect(self, detector):
        """Detect signal.connect(handler) pattern."""
        source = "from django.db.models.signals import post_save\npost_save.connect(my_handler, sender=MyModel)\n"
        patterns = detector._detect_signals(source, "signals.py", [])
        assert len(patterns) >= 1
        signal_p = [p for p in patterns if p.metadata.get("handler") == "my_handler"]
        assert len(signal_p) == 1
        assert signal_p[0].metadata["signal_name"] == "post_save"

    def test_signal_connect_with_module_path(self, detector):
        """Detect models.signals.pre_delete.connect(handler)."""
        source = "models.signals.pre_delete.connect(cleanup_handler)\n"
        patterns = detector._detect_signals(source, "signals.py", [])
        assert len(patterns) >= 1
        assert patterns[0].metadata["signal_name"] == "pre_delete"
        assert patterns[0].metadata["handler"] == "cleanup_handler"

    def test_no_signals(self, detector):
        source = "x = 42\n"
        patterns = detector._detect_signals(source, "plain.py", [])
        assert len(patterns) == 0


# ── _extract_view_name ────────────────────────────────────────


class TestExtractViewName:
    def test_as_view(self, detector):
        assert detector._extract_view_name("views.UserListView.as_view()") == "UserListView"

    def test_dotted_function(self, detector):
        assert detector._extract_view_name("views.index") == "index"

    def test_plain_function(self, detector):
        assert detector._extract_view_name("home_view") == "home_view"


# ── _resolve_view ─────────────────────────────────────────────


class TestResolveView:
    def test_resolve_controller(self, detector):
        store = MagicMock()
        ctrl = _make_node(NodeKind.CONTROLLER, "UserView")
        store.find_nodes.return_value = [ctrl]
        result = detector._resolve_view("UserView", store)
        assert result == ctrl.id

    def test_resolve_class(self, detector):
        store = MagicMock()
        cls = _make_node(NodeKind.CLASS, "UserView")
        # First call (controller) returns empty, second (class) returns match
        store.find_nodes.side_effect = [[], [cls], []]
        result = detector._resolve_view("UserView", store)
        assert result == cls.id

    def test_resolve_function(self, detector):
        store = MagicMock()
        fn = _make_node(NodeKind.FUNCTION, "index")
        store.find_nodes.side_effect = [[], [], [fn]]
        result = detector._resolve_view("index", store)
        assert result == fn.id

    def test_resolve_not_found(self, detector):
        store = MagicMock()
        store.find_nodes.return_value = []
        result = detector._resolve_view("missing", store)
        assert result is None

    def test_resolve_name_mismatch(self, detector):
        store = MagicMock()
        wrong = _make_node(NodeKind.CONTROLLER, "OtherView")
        store.find_nodes.side_effect = [[wrong], [wrong], [wrong]]
        result = detector._resolve_view("UserView", store)
        assert result is None


# ── _build_route_tree ─────────────────────────────────────────


class TestBuildRouteTree:
    def test_build_route_tree_with_include(self, detector, tmp_path):
        """Build route tree from urls.py with include()."""
        urls_content = (
            "from django.urls import path, include\n"
            "urlpatterns = [\n"
            "    path('api/', include('myapp.api.urls')),\n"
            "    path('users/', views.UserListView.as_view(), name='user-list'),\n"
            "]\n"
        )
        (tmp_path / "urls.py").write_text(urls_content)
        store = MagicMock()
        store.find_nodes.return_value = []
        pattern = detector._build_route_tree(store, str(tmp_path))
        assert pattern is not None
        assert pattern.pattern_type == "routes"
        assert pattern.metadata["route_count"] >= 1

    def test_build_route_tree_resolves_view(self, detector, tmp_path):
        """Route tree resolves views via store."""
        urls_content = (
            "from django.urls import path\n"
            "urlpatterns = [\n"
            "    path('home/', views.HomeView.as_view(), name='home'),\n"
            "]\n"
        )
        (tmp_path / "urls.py").write_text(urls_content)
        ctrl = _make_node(NodeKind.CONTROLLER, "HomeView")
        store = MagicMock()
        store.find_nodes.side_effect = lambda **kw: [ctrl] if kw.get("kind") == NodeKind.CONTROLLER else []
        pattern = detector._build_route_tree(store, str(tmp_path))
        assert pattern is not None
        routes_to = [e for e in pattern.edges if e.kind == EdgeKind.ROUTES_TO]
        assert len(routes_to) >= 1

    def test_build_route_tree_no_urls(self, detector, tmp_path):
        """No urls.py files returns None."""
        pattern = detector._build_route_tree(MagicMock(), str(tmp_path))
        assert pattern is None

    def test_build_route_tree_unreadable_file(self, detector, tmp_path):
        """Unreadable urls.py is skipped."""
        urls = tmp_path / "urls.py"
        urls.write_text("urlpatterns = []")
        urls.chmod(0o000)
        store = MagicMock()
        pattern = detector._build_route_tree(store, str(tmp_path))
        urls.chmod(0o644)  # restore for cleanup
        # Should return None since file can't be read
        assert pattern is None


# ── _extract_middleware_chain ─────────────────────────────────


class TestExtractMiddlewareChain:
    def test_extract_middleware_chain(self, detector, tmp_path):
        """Extract MIDDLEWARE list from settings.py."""
        settings = tmp_path / "settings.py"
        settings.write_text(
            "MIDDLEWARE = [\n"
            "    'django.middleware.security.SecurityMiddleware',\n"
            "    'django.contrib.sessions.middleware.SessionMiddleware',\n"
            "    'django.middleware.common.CommonMiddleware',\n"
            "]\n"
        )
        store = MagicMock()
        pattern = detector._extract_middleware_chain(store, str(tmp_path))
        assert pattern is not None
        assert pattern.pattern_type == "middleware_chain"
        assert pattern.metadata["middleware_count"] == 3
        # Check chaining edges
        depends_on = [e for e in pattern.edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(depends_on) == 2  # 3 middleware, 2 chain edges

    def test_extract_middleware_chain_nested_settings(self, detector, tmp_path):
        """Find settings.py in nested directory."""
        settings_dir = tmp_path / "myproject" / "settings"
        settings_dir.mkdir(parents=True)
        (settings_dir / "base.py").write_text(
            "MIDDLEWARE = [\n    'django.middleware.security.SecurityMiddleware',\n]\n"
        )
        store = MagicMock()
        pattern = detector._extract_middleware_chain(store, str(tmp_path))
        assert pattern is not None
        assert pattern.metadata["middleware_count"] == 1

    def test_extract_middleware_chain_no_settings(self, detector, tmp_path):
        """No settings.py returns None."""
        store = MagicMock()
        pattern = detector._extract_middleware_chain(store, str(tmp_path))
        assert pattern is None

    def test_extract_middleware_chain_no_middleware_var(self, detector, tmp_path):
        """settings.py without MIDDLEWARE returns None."""
        (tmp_path / "settings.py").write_text("DEBUG = True\n")
        store = MagicMock()
        pattern = detector._extract_middleware_chain(store, str(tmp_path))
        assert pattern is None


# ── detect_global_patterns ────────────────────────────────────


class TestDetectGlobalPatterns:
    def test_infer_project_root_none(self, detector):
        """When store has no file nodes, returns empty."""
        store = MagicMock()
        store.find_nodes.return_value = []
        patterns = detector.detect_global_patterns(store)
        assert patterns == []

    def test_global_patterns_with_routes_and_middleware(self, detector, tmp_path):
        """Full global patterns with route tree and middleware chain."""
        # Create manage.py so _infer_project_root can find the project root
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        # Create urls.py
        (tmp_path / "urls.py").write_text(
            "from django.urls import path\nurlpatterns = [\n    path('home/', views.home, name='home'),\n]\n"
        )
        # Create settings.py
        (tmp_path / "settings.py").write_text(
            "MIDDLEWARE = [\n    'django.middleware.security.SecurityMiddleware',\n]\n"
        )
        # Mock store to return a file node with absolute path inside tmp_path
        file_node = _make_node(NodeKind.FILE, "models.py", file_path=os.path.join(str(tmp_path), "models.py"))
        store = MagicMock()
        store.find_nodes.side_effect = lambda **kw: [file_node] if kw.get("kind") == NodeKind.FILE else []
        patterns = detector.detect_global_patterns(store)
        pattern_types = {p.pattern_type for p in patterns}
        assert "routes" in pattern_types or "middleware_chain" in pattern_types


# ── _detect_url_patterns ──────────────────────────────────────


class TestDetectUrlPatterns:
    def test_url_patterns_with_as_view(self, detector):
        source = (
            "from django.urls import path\n"
            "urlpatterns = [\n"
            "    path('users/', views.UserListView.as_view(), name='user-list'),\n"
            "]\n"
        )
        pattern = detector._detect_url_patterns(source, "urls.py")
        assert pattern is not None
        assert pattern.metadata["route_count"] >= 1
        routes_to = [e for e in pattern.edges if e.kind == EdgeKind.ROUTES_TO]
        assert len(routes_to) >= 1

    def test_url_patterns_no_urlpatterns(self, detector):
        source = "from django.urls import path\n"
        pattern = detector._detect_url_patterns(source, "urls.py")
        assert pattern is None

    def test_url_patterns_empty(self, detector):
        source = "urlpatterns = []\n"
        pattern = detector._detect_url_patterns(source, "urls.py")
        assert pattern is None
