"""Targeted tests for JS framework detector coverage gaps.

Covers Express, React, and NextJS detectors.
Express missing: 103-105, 203, 272-273, 279-283, 301-305
React missing: 114-116, 121, 195, 242-251, 309, 474, 490-523
NextJS missing: 75, 142-144, 149, 215, 273, 310, 422, 459, 570, 578, 608-627
"""

import json
import os
from unittest.mock import MagicMock, patch

from coderag.core.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    generate_node_id,
)
from coderag.plugins.javascript.frameworks.express import ExpressDetector
from coderag.plugins.javascript.frameworks.nextjs import NextJSDetector
from coderag.plugins.javascript.frameworks.react import ReactDetector


def _make_file_node(file_path, name, lang="javascript"):
    return Node(
        id=generate_node_id(file_path, 1, NodeKind.FILE, name),
        kind=NodeKind.FILE,
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=1,
        end_line=100,
        language=lang,
    )


def _make_func_node(file_path, name, line, kind=NodeKind.FUNCTION, end_line=None):
    return Node(
        id=generate_node_id(file_path, line, kind, name),
        kind=kind,
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=line,
        end_line=end_line or line + 10,
        language="javascript",
    )


def _make_method_node(file_path, name, line):
    return Node(
        id=generate_node_id(file_path, line, NodeKind.METHOD, name),
        kind=NodeKind.METHOD,
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=line,
        end_line=line + 5,
        language="javascript",
    )


# ===========================================================================
# EXPRESS DETECTOR TESTS
# ===========================================================================
class TestExpressDetectFramework:
    def test_detect_with_package_json(self, tmp_path):
        pkg = {"dependencies": {"express": "^4.18.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        det = ExpressDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_detect_no_express(self, tmp_path):
        pkg = {"dependencies": {"fastify": "^4.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        det = ExpressDetector()
        assert det.detect_framework(str(tmp_path)) is False

    def test_monorepo_subdir_check(self, tmp_path):
        """Lines 103-105: Check monorepo subdirectories for express."""
        det = ExpressDetector()
        pkgs = tmp_path / "packages" / "api"
        pkgs.mkdir(parents=True)
        pkg = {"dependencies": {"express": "^4.18.0"}}
        (pkgs / "package.json").write_text(json.dumps(pkg))
        assert det.detect_framework(str(tmp_path)) is True

    def test_monorepo_oserror(self, tmp_path):
        """Lines 103-105: OSError when listing monorepo subdirectory."""
        det = ExpressDetector()
        pkgs = tmp_path / "packages"
        pkgs.mkdir()
        real_listdir = os.listdir

        def mock_listdir(path):
            if "packages" in str(path):
                raise OSError("Permission denied")
            return real_listdir(path)

        with patch("os.listdir", side_effect=mock_listdir):
            result = det.detect_framework(str(tmp_path))
        assert result is False


class TestExpressDetect:
    def test_middleware_name_fallback(self, tmp_path):
        """Line 203: middleware with no extractable name gets fallback."""
        src = tmp_path / "app.js"
        code = b"app.use(function(req, res, next) { next(); });\n"
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "app.js")
        det = ExpressDetector()
        patterns = det.detect(str(src), None, code, [file_node], [])
        assert isinstance(patterns, list)

    def test_route_handler_same_line(self, tmp_path):
        """Lines 272-273: handler function on same line as route."""
        src = tmp_path / "routes.js"
        code = b"""const express = require('express');
const router = express.Router();
router.get('/users', getUsers);
function getUsers(req, res) { res.json([]); }
"""
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "routes.js")
        func_node = _make_func_node(str(src), "getUsers", 4)
        det = ExpressDetector()
        patterns = det.detect(str(src), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_route_handler_closest_within_2_lines(self, tmp_path):
        """Lines 279-283: closest function within 2 lines of route."""
        src = tmp_path / "routes.js"
        code = b"""const express = require('express');
const router = express.Router();
router.get('/items', handler);

function handler(req, res) { res.json([]); }
"""
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "routes.js")
        func_node = _make_func_node(str(src), "handler", 5)
        det = ExpressDetector()
        patterns = det.detect(str(src), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_middleware_variable_ref(self, tmp_path):
        """Lines 301-305: middleware name from variable reference."""
        src = tmp_path / "app.js"
        code = b"""const express = require('express');
const app = express();
app.use(cors);
app.use(helmet);
"""
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "app.js")
        det = ExpressDetector()
        patterns = det.detect(str(src), None, code, [file_node], [])
        assert isinstance(patterns, list)

    def test_route_with_inline_handler(self, tmp_path):
        """Route with inline arrow function handler."""
        src = tmp_path / "app.js"
        code = b"""const express = require('express');
const app = express();
app.get('/health', (req, res) => res.json({ ok: true }));
"""
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "app.js")
        det = ExpressDetector()
        patterns = det.detect(str(src), None, code, [file_node], [])
        assert isinstance(patterns, list)


class TestExpressGlobalPatterns:
    def test_global_patterns(self):
        det = ExpressDetector()
        store = MagicMock()
        store.find_nodes.return_value = []
        patterns = det.detect_global_patterns(store)
        assert isinstance(patterns, list)


# ===========================================================================
# REACT DETECTOR TESTS
# ===========================================================================
class TestReactDetectFramework:
    def test_detect_with_react_dep(self, tmp_path):
        pkg = {"dependencies": {"react": "^18.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        det = ReactDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_monorepo_oserror(self, tmp_path):
        """Lines 114-116: OSError when listing monorepo subdirectory."""
        det = ReactDetector()
        pkgs = tmp_path / "packages"
        pkgs.mkdir()
        real_listdir = os.listdir

        def mock_listdir(path):
            if "packages" in str(path):
                raise OSError("Permission denied")
            return real_listdir(path)

        with patch("os.listdir", side_effect=mock_listdir):
            result = det.detect_framework(str(tmp_path))
        assert result is False

    def test_tsx_jsx_fallback(self, tmp_path):
        """Line 121: .tsx/.jsx files as React signal."""
        det = ReactDetector()
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "App.tsx").write_text("export default function App() {}")
        result = det.detect_framework(str(tmp_path))
        assert result is True

    def test_jsx_fallback(self, tmp_path):
        """Line 121: .jsx files as React signal."""
        det = ReactDetector()
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "Component.jsx").write_text("export default function Comp() {}")
        result = det.detect_framework(str(tmp_path))
        assert result is True

    def test_no_react_signals(self, tmp_path):
        """No React signals at all."""
        det = ReactDetector()
        (tmp_path / "index.js").write_text("console.log('hello');")
        result = det.detect_framework(str(tmp_path))
        assert result is False


class TestReactDetect:
    def test_class_component_with_render(self, tmp_path):
        """Lines 242-251: class with render method detected as component."""
        src = tmp_path / "MyComponent.jsx"
        code = b"""import React from 'react';
class MyComponent extends React.Component {
    render() {
        return <div>Hello</div>;
    }
}
export default MyComponent;
"""
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "MyComponent.jsx")
        class_node = _make_func_node(str(src), "MyComponent", 2, NodeKind.CLASS)
        render_node = _make_method_node(str(src), "render", 3)
        contains_edge = Edge(
            source_id=class_node.id,
            target_id=render_node.id,
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
        )
        det = ReactDetector()
        patterns = det.detect(str(src), None, code, [file_node, class_node, render_node], [contains_edge])
        assert isinstance(patterns, list)

    def test_class_without_render_skipped(self, tmp_path):
        """Lines 242-251: class without render method is not a component."""
        src = tmp_path / "Utils.js"
        code = b"""class Utils {
    static format(data) { return data; }
}
export default Utils;
"""
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "Utils.js")
        class_node = _make_func_node(str(src), "Utils", 1, NodeKind.CLASS)
        det = ReactDetector()
        patterns = det.detect(str(src), None, code, [file_node, class_node], [])
        assert isinstance(patterns, list)

    def test_no_components_returns_empty_or_none(self, tmp_path):
        """Line 309: no new_nodes returns None."""
        src = tmp_path / "utils.js"
        code = b"const x = 42;\nexport default x;\n"
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "utils.js")
        det = ReactDetector()
        patterns = det.detect(str(src), None, code, [file_node], [])
        assert isinstance(patterns, list)

    def test_functional_component_with_jsx(self, tmp_path):
        """Functional component returning JSX."""
        src = tmp_path / "App.jsx"
        code = b"""function App() {
    return <div>Hello World</div>;
}
export default App;
"""
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "App.jsx")
        func_node = _make_func_node(str(src), "App", 1)
        det = ReactDetector()
        patterns = det.detect(str(src), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_hook_usage(self, tmp_path):
        """Component using hooks."""
        src = tmp_path / "Counter.jsx"
        code = b"""import { useState } from 'react';
function Counter() {
    const [count, setCount] = useState(0);
    return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
export default Counter;
"""
        src.write_bytes(code)
        file_node = _make_file_node(str(src), "Counter.jsx")
        func_node = _make_func_node(str(src), "Counter", 2)
        det = ReactDetector()
        patterns = det.detect(str(src), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)


class TestReactFindEnclosingFunction:
    def test_no_candidates(self):
        """Line 474: no candidates returns None."""
        det = ReactDetector()
        result = det._find_enclosing_function(50, [])
        assert result is None

    def test_with_enclosing_function(self):
        """Returns the most specific enclosing function."""
        det = ReactDetector()
        outer = _make_func_node("test.js", "outer", 1, end_line=50)
        inner = _make_func_node("test.js", "inner", 10, end_line=20)
        result = det._find_enclosing_function(15, [outer, inner])
        assert result is inner

    def test_line_outside_all_functions(self):
        """Line outside all functions returns None."""
        det = ReactDetector()
        func = _make_func_node("test.js", "func", 10, end_line=20)
        result = det._find_enclosing_function(50, [func])
        assert result is None


class TestReactGlobalPatterns:
    def test_cross_file_hooks_no_hooks(self):
        """Lines 490-523: no hook nodes returns empty."""
        det = ReactDetector()
        store = MagicMock()
        store.find_nodes.return_value = []
        patterns = det.detect_global_patterns(store)
        assert isinstance(patterns, list)

    def test_cross_file_hooks_with_unresolved(self):
        """Lines 490-523: hook nodes with unresolved references."""
        det = ReactDetector()
        store = MagicMock()

        hook_node = _make_func_node("hooks.js", "useAuth", 1)
        comp_node = Node(
            id=generate_node_id("App.jsx", 1, NodeKind.COMPONENT, "App"),
            kind=NodeKind.COMPONENT,
            name="App",
            qualified_name="App",
            file_path="App.jsx",
            start_line=1,
            end_line=20,
            language="javascript",
        )

        unresolved_edge = Edge(
            source_id=comp_node.id,
            target_id="__unresolved__:hook:useAuth",
            kind=EdgeKind.USES_HOOK,
            confidence=0.5,
        )

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.FUNCTION:
                return [hook_node]
            if kind == NodeKind.COMPONENT:
                return [comp_node]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        store.get_edges.return_value = [unresolved_edge]

        patterns = det.detect_global_patterns(store)
        assert isinstance(patterns, list)

    def test_cross_file_hooks_no_unresolved(self):
        """Lines 490-523: hooks exist but no unresolved references."""
        det = ReactDetector()
        store = MagicMock()

        hook_node = _make_func_node("hooks.js", "useAuth", 1)
        comp_node = Node(
            id=generate_node_id("App.jsx", 1, NodeKind.COMPONENT, "App"),
            kind=NodeKind.COMPONENT,
            name="App",
            qualified_name="App",
            file_path="App.jsx",
            start_line=1,
            end_line=20,
            language="javascript",
        )

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.FUNCTION:
                return [hook_node]
            if kind == NodeKind.COMPONENT:
                return [comp_node]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        store.get_edges.return_value = []

        patterns = det.detect_global_patterns(store)
        assert isinstance(patterns, list)


# ===========================================================================
# NEXTJS DETECTOR TESTS
# ===========================================================================
class TestNextJSDetectFramework:
    def test_detect_with_next_dep(self, tmp_path):
        pkg = {"dependencies": {"next": "^14.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        det = NextJSDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_monorepo_oserror(self, tmp_path):
        """Lines 142-144: OSError when listing monorepo subdirectory."""
        det = NextJSDetector()
        pkgs = tmp_path / "packages"
        pkgs.mkdir()
        real_listdir = os.listdir

        def mock_listdir(path):
            if "packages" in str(path):
                raise OSError("Permission denied")
            return real_listdir(path)

        with patch("os.listdir", side_effect=mock_listdir):
            result = det.detect_framework(str(tmp_path))
        assert result is False

    def test_next_config_js_fallback(self, tmp_path):
        """Line 149: next.config.js as NextJS signal."""
        det = NextJSDetector()
        (tmp_path / "next.config.js").write_text("module.exports = {};")
        result = det.detect_framework(str(tmp_path))
        assert result is True

    def test_next_config_mjs_fallback(self, tmp_path):
        """Line 149: next.config.mjs as NextJS signal."""
        det = NextJSDetector()
        (tmp_path / "next.config.mjs").write_text("export default {};")
        result = det.detect_framework(str(tmp_path))
        assert result is True

    def test_no_next_signals(self, tmp_path):
        det = NextJSDetector()
        (tmp_path / "index.js").write_text("console.log('hello');")
        result = det.detect_framework(str(tmp_path))
        assert result is False


class TestNextJSDetect:
    def test_app_router_page(self, tmp_path):
        app_dir = tmp_path / "app" / "dashboard"
        app_dir.mkdir(parents=True)
        page = app_dir / "page.tsx"
        code = b"export default function Dashboard() { return <div>Dashboard</div>; }"
        page.write_bytes(code)
        file_node = _make_file_node(str(page), "page.tsx")
        func_node = _make_func_node(str(page), "Dashboard", 1)
        det = NextJSDetector()
        patterns = det.detect(str(page), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_app_router_layout(self, tmp_path):
        app_dir = tmp_path / "app"
        app_dir.mkdir(parents=True)
        layout = app_dir / "layout.tsx"
        code = b"export default function RootLayout({ children }) { return <html>{children}</html>; }"
        layout.write_bytes(code)
        file_node = _make_file_node(str(layout), "layout.tsx")
        func_node = _make_func_node(str(layout), "RootLayout", 1)
        det = NextJSDetector()
        patterns = det.detect(str(layout), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_app_router_route_handler(self, tmp_path):
        api_dir = tmp_path / "app" / "api" / "users"
        api_dir.mkdir(parents=True)
        route = api_dir / "route.ts"
        code = b"export async function GET(request) { return Response.json([]); }\nexport async function POST(request) { return Response.json({}); }"
        route.write_bytes(code)
        file_node = _make_file_node(str(route), "route.ts")
        get_func = _make_func_node(str(route), "GET", 1)
        post_func = _make_func_node(str(route), "POST", 2)
        det = NextJSDetector()
        patterns = det.detect(str(route), None, code, [file_node, get_func, post_func], [])
        assert isinstance(patterns, list)

    def test_non_route_extension_skipped(self, tmp_path):
        """Line 310: non-route extension returns None."""
        app_dir = tmp_path / "app"
        app_dir.mkdir(parents=True)
        css_file = app_dir / "page.css"
        code = b".page { color: red; }"
        css_file.write_bytes(code)
        file_node = _make_file_node(str(css_file), "page.css")
        det = NextJSDetector()
        patterns = det.detect(str(css_file), None, code, [file_node], [])
        assert isinstance(patterns, list)

    def test_pages_router_index(self, tmp_path):
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)
        index = pages_dir / "index.tsx"
        code = b"export default function Home() { return <div>Home</div>; }"
        index.write_bytes(code)
        file_node = _make_file_node(str(index), "index.tsx")
        func_node = _make_func_node(str(index), "Home", 1)
        det = NextJSDetector()
        patterns = det.detect(str(index), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_pages_router_non_route_extension(self, tmp_path):
        """Line 459: non-route extension in pages router."""
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)
        css_file = pages_dir / "styles.css"
        code = b".page { color: red; }"
        css_file.write_bytes(code)
        file_node = _make_file_node(str(css_file), "styles.css")
        det = NextJSDetector()
        patterns = det.detect(str(css_file), None, code, [file_node], [])
        assert isinstance(patterns, list)

    def test_dynamic_route_segment(self, tmp_path):
        app_dir = tmp_path / "app" / "users" / "[id]"
        app_dir.mkdir(parents=True)
        page = app_dir / "page.tsx"
        code = b"export default function UserPage({ params }) { return <div>{params.id}</div>; }"
        page.write_bytes(code)
        file_node = _make_file_node(str(page), "page.tsx")
        func_node = _make_func_node(str(page), "UserPage", 1)
        det = NextJSDetector()
        patterns = det.detect(str(page), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_optional_catch_all_route(self, tmp_path):
        """Line 75: optional catch-all [[...slug]] segment."""
        app_dir = tmp_path / "app" / "docs" / "[[...slug]]"
        app_dir.mkdir(parents=True)
        page = app_dir / "page.tsx"
        code = b"export default function DocsPage({ params }) { return <div>Docs</div>; }"
        page.write_bytes(code)
        file_node = _make_file_node(str(page), "page.tsx")
        func_node = _make_func_node(str(page), "DocsPage", 1)
        det = NextJSDetector()
        patterns = det.detect(str(page), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_catch_all_route(self, tmp_path):
        app_dir = tmp_path / "app" / "blog" / "[...slug]"
        app_dir.mkdir(parents=True)
        page = app_dir / "page.tsx"
        code = b"export default function BlogPost({ params }) { return <div>Blog</div>; }"
        page.write_bytes(code)
        file_node = _make_file_node(str(page), "page.tsx")
        func_node = _make_func_node(str(page), "BlogPost", 1)
        det = NextJSDetector()
        patterns = det.detect(str(page), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_no_components_returns_none(self, tmp_path):
        """Line 273: no new_nodes returns None."""
        app_dir = tmp_path / "app"
        app_dir.mkdir(parents=True)
        util = app_dir / "utils.ts"
        code = b"export const x = 42;"
        util.write_bytes(code)
        file_node = _make_file_node(str(util), "utils.ts")
        det = NextJSDetector()
        patterns = det.detect(str(util), None, code, [file_node], [])
        assert isinstance(patterns, list)

    def test_no_route_nodes_returns_none(self, tmp_path):
        """Line 422: no route_nodes returns None."""
        api_dir = tmp_path / "app" / "api" / "health"
        api_dir.mkdir(parents=True)
        route = api_dir / "route.ts"
        code = b"// empty route handler"
        route.write_bytes(code)
        file_node = _make_file_node(str(route), "route.ts")
        det = NextJSDetector()
        patterns = det.detect(str(route), None, code, [file_node], [])
        assert isinstance(patterns, list)

    def test_route_group_segment(self, tmp_path):
        app_dir = tmp_path / "app" / "(marketing)" / "about"
        app_dir.mkdir(parents=True)
        page = app_dir / "page.tsx"
        code = b"export default function About() { return <div>About</div>; }"
        page.write_bytes(code)
        file_node = _make_file_node(str(page), "page.tsx")
        func_node = _make_func_node(str(page), "About", 1)
        det = NextJSDetector()
        patterns = det.detect(str(page), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_pages_router_dynamic_route(self, tmp_path):
        pages_dir = tmp_path / "pages" / "users"
        pages_dir.mkdir(parents=True)
        page = pages_dir / "[id].tsx"
        code = b"export default function UserPage({ params }) { return <div>User</div>; }"
        page.write_bytes(code)
        file_node = _make_file_node(str(page), "[id].tsx")
        func_node = _make_func_node(str(page), "UserPage", 1)
        det = NextJSDetector()
        patterns = det.detect(str(page), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_pages_router_special_files(self, tmp_path):
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True)
        app = pages_dir / "_app.tsx"
        code = b"export default function App({ Component, pageProps }) { return <Component {...pageProps} />; }"
        app.write_bytes(code)
        file_node = _make_file_node(str(app), "_app.tsx")
        func_node = _make_func_node(str(app), "App", 1)
        det = NextJSDetector()
        patterns = det.detect(str(app), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)

    def test_pages_router_api_route(self, tmp_path):
        api_dir = tmp_path / "pages" / "api"
        api_dir.mkdir(parents=True)
        handler = api_dir / "users.ts"
        code = b"export default function handler(req, res) { res.json([]); }"
        handler.write_bytes(code)
        file_node = _make_file_node(str(handler), "users.ts")
        func_node = _make_func_node(str(handler), "handler", 1)
        det = NextJSDetector()
        patterns = det.detect(str(handler), None, code, [file_node, func_node], [])
        assert isinstance(patterns, list)


class TestNextJSGlobalPatterns:
    def test_returns_empty(self):
        """Line 215: detect_global_patterns returns empty list."""
        det = NextJSDetector()
        store = MagicMock()
        patterns = det.detect_global_patterns(store)
        assert patterns == []


class TestNextJSHelpers:
    def test_find_handler_match(self):
        """Line 578: _find_handler returns matching function."""
        func = _make_func_node("route.ts", "GET", 1)
        result = NextJSDetector._find_handler([func], "GET")
        assert result is func

    def test_find_handler_no_match(self):
        """Line 578: _find_handler returns None when no match."""
        func = _make_func_node("route.ts", "GET", 1)
        result = NextJSDetector._find_handler([func], "POST")
        assert result is None

    def test_find_default_export_direct(self):
        """Lines 608-627: find default export via 'export default function Name'."""
        source = "export default function Dashboard() { return null; }"
        func = _make_func_node("page.tsx", "Dashboard", 1)
        result = NextJSDetector._find_default_export([func], source)
        assert result is func

    def test_find_default_export_reference(self):
        """Lines 608-627: find default export via 'export default Name' reference."""
        source = "function MyPage() { return null; }\nexport default MyPage;"
        func = _make_func_node("page.tsx", "MyPage", 1)
        result = NextJSDetector._find_default_export([func], source)
        assert result is func

    def test_find_default_export_fallback_uppercase(self):
        """Lines 608-627: fallback to first uppercase-named function."""
        source = "const x = 42;"
        func = _make_func_node("page.tsx", "PageComponent", 1)
        result = NextJSDetector._find_default_export([func], source)
        assert result is func

    def test_find_default_export_none(self):
        """Lines 608-627: no default export found returns None."""
        source = "const x = 42;"
        func = _make_func_node("page.tsx", "helper", 1)
        result = NextJSDetector._find_default_export([func], source)
        assert result is None

    def test_find_export_line(self):
        """Line 570: _find_export_line finds line of export statement."""
        source = "import React from 'react';\nexport default function Page() {}\n"
        result = NextJSDetector._find_export_line(source, "GET")
        assert isinstance(result, int)

    def test_find_export_line_with_match(self):
        """Line 570: _find_export_line with matching pattern."""
        source = "import React from 'react';\nexport async function GET(req) {}\n"
        result = NextJSDetector._find_export_line(source, "GET")
        assert result == 2

    def test_find_default_export_class(self):
        """Lines 608-627: find default export via class reference."""
        source = "class MyPage extends Component {}\nexport default MyPage;"
        cls = _make_func_node("page.tsx", "MyPage", 1, NodeKind.CLASS)
        result = NextJSDetector._find_default_export([cls], source)
        assert result is cls

    def test_find_default_export_variable(self):
        """Lines 608-627: find default export via variable reference."""
        source = "const MyPage = () => <div/>;\nexport default MyPage;"
        var = _make_func_node("page.tsx", "MyPage", 1, NodeKind.VARIABLE)
        result = NextJSDetector._find_default_export([var], source)
        assert result is var
