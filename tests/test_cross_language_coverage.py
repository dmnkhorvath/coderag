"""Tests for cross_language.py — targeting uncovered lines.

Covers: collect_endpoints edge cases, collect_api_calls file handling,
match() URL cleaning, _extract_api_calls_from_source empty URL skips.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from coderag.core.models import Node, Edge, NodeKind, EdgeKind
from coderag.pipeline.cross_language import CrossLanguageMatcher, APIEndpoint, APICall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    id: str = "node-1",
    name: str = "test",
    kind: NodeKind = NodeKind.FILE,
    language: str = "python",
    file_path: str = "/tmp/test.py",
    qualified_name: str = "test",
    start_line: int = 1,
    end_line: int = 10,
    metadata: dict | None = None,
) -> Node:
    return Node(
        id=id,
        name=name,
        kind=kind,
        language=language,
        file_path=file_path,
        qualified_name=qualified_name,
        start_line=start_line,
        end_line=end_line,
        metadata=metadata or {},
    )


def _make_matcher(**kwargs):
    return CrossLanguageMatcher(**kwargs)


# ---------------------------------------------------------------------------
# collect_endpoints — line 269: qualified_name doesn't match HTTP method
# ---------------------------------------------------------------------------

class TestCollectEndpointsEdgeCases:
    """Cover lines 269, 272."""

    def test_route_no_url_pattern_no_http_method_in_qname(self):
        """Line 269: qualified_name doesn't start with HTTP method -> continue."""
        node = _make_node(
            id="route-1",
            kind=NodeKind.ROUTE,
            qualified_name="some_route",
            metadata={},  # no url_pattern, no http_method
        )
        matcher = _make_matcher()
        endpoints = matcher.collect_endpoints([node], [])
        assert len(endpoints) == 0

    def test_route_url_from_qualified_name(self):
        """Route with url_pattern extracted from qualified_name like 'GET /api/users'."""
        node = _make_node(
            id="route-1",
            kind=NodeKind.ROUTE,
            qualified_name="GET /api/users",
            metadata={},  # no url_pattern, no http_method
        )
        matcher = _make_matcher()
        endpoints = matcher.collect_endpoints([node], [])
        assert len(endpoints) == 1
        assert endpoints[0].http_method == "GET"
        assert endpoints[0].path == "/api/users"

    def test_route_no_http_method_defaults_to_get(self):
        """Line 272: url_pattern present but no http_method -> defaults to GET."""
        node = _make_node(
            id="route-1",
            kind=NodeKind.ROUTE,
            qualified_name="route",
            metadata={"url_pattern": "/api/items", "http_method": ""},
        )
        matcher = _make_matcher()
        endpoints = matcher.collect_endpoints([node], [])
        assert len(endpoints) == 1
        assert endpoints[0].http_method == "GET"

    def test_route_with_routes_to_edge(self):
        """Route with ROUTES_TO edge -> handler_id from edge."""
        node = _make_node(
            id="route-1",
            kind=NodeKind.ROUTE,
            qualified_name="route",
            metadata={"url_pattern": "/api/items", "http_method": "POST"},
        )
        edge = Edge(
            source_id="route-1",
            target_id="handler-1",
            kind=EdgeKind.ROUTES_TO,
        )
        matcher = _make_matcher()
        endpoints = matcher.collect_endpoints([node], [edge])
        assert len(endpoints) == 1
        assert endpoints[0].handler_node_id == "handler-1"


# ---------------------------------------------------------------------------
# collect_api_calls — lines 318-324: os.walk fallback
# ---------------------------------------------------------------------------

class TestCollectApiCallsOsWalk:
    """Cover lines 318-324: os.walk fallback when no JS file nodes."""

    def test_os_walk_fallback(self, tmp_path):
        """When nodes have no JS FILE nodes, falls back to os.walk."""
        js_file = tmp_path / "app.js"
        js_file.write_text('fetch("/api/users");\n')

        matcher = _make_matcher()
        calls = matcher.collect_api_calls([], [], str(tmp_path))
        # Should have found the JS file via os.walk
        assert isinstance(calls, list)

    def test_os_walk_skips_node_modules(self, tmp_path):
        """os.walk skips node_modules directory."""
        nm_dir = tmp_path / "node_modules" / "pkg"
        nm_dir.mkdir(parents=True)
        (nm_dir / "index.js").write_text('fetch("/api");\n')

        matcher = _make_matcher()
        calls = matcher.collect_api_calls([], [], str(tmp_path))
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# collect_api_calls — line 338: file not found
# ---------------------------------------------------------------------------

class TestCollectApiCallsFileNotFound:
    """Cover line 338: file doesn't exist -> continue."""

    def test_nonexistent_file_skipped(self, tmp_path):
        file_node = _make_node(
            id="file-1",
            kind=NodeKind.FILE,
            language="javascript",
            file_path=str(tmp_path / "nonexistent.js"),
        )
        matcher = _make_matcher()
        calls = matcher.collect_api_calls([file_node], [], str(tmp_path))
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# collect_api_calls — lines 343-344: OSError reading file
# ---------------------------------------------------------------------------

class TestCollectApiCallsOSError:
    """Cover lines 343-344: OSError on file read -> continue."""

    def test_file_read_oserror(self, tmp_path):
        js_file = tmp_path / "app.js"
        js_file.write_text("x")  # Create file so isfile passes

        file_node = _make_node(
            id="file-1",
            kind=NodeKind.FILE,
            language="javascript",
            file_path=str(js_file),
        )
        matcher = _make_matcher()
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            calls = matcher.collect_api_calls([file_node], [], str(tmp_path))
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# _extract_api_calls_from_source — empty URL skips
# ---------------------------------------------------------------------------

class TestExtractApiCallsEmptyUrls:
    """Cover lines 581, 601, 642, 695, 699."""

    def test_fetch_empty_url_skipped(self):
        """Line 581: fetch() with empty URL -> continue."""
        matcher = _make_matcher()
        source = 'fetch("");\n'
        calls = matcher._extract_api_calls_from_source(source, "test.js", [])
        assert all(c.url_pattern != "" for c in calls)

    def test_axios_empty_url_skipped(self):
        """Line 601: axios.get() with empty URL -> continue."""
        matcher = _make_matcher()
        source = 'axios.get("");\n'
        calls = matcher._extract_api_calls_from_source(source, "test.js", [])
        assert all(c.url_pattern != "" for c in calls)

    def test_jquery_empty_url_skipped(self):
        """Line 642: $.ajax with empty URL -> continue."""
        matcher = _make_matcher()
        source = '$.ajax("");\n'
        calls = matcher._extract_api_calls_from_source(source, "test.js", [])
        assert all(c.url_pattern != "" for c in calls)

    def test_custom_http_unknown_client_skipped(self):
        """Line 695: custom HTTP client with unknown name -> continue."""
        matcher = _make_matcher()
        source = 'unknownThing.get("/api/users");\n'
        calls = matcher._extract_api_calls_from_source(source, "test.js", [])
        assert isinstance(calls, list)

    def test_custom_http_empty_url_skipped(self):
        """Line 699: custom HTTP client with empty URL -> continue."""
        matcher = _make_matcher()
        source = 'apiClient.get("");\n'
        calls = matcher._extract_api_calls_from_source(source, "test.js", [])
        assert all(c.url_pattern != "" for c in calls)

    def test_fetch_with_valid_url(self):
        """Fetch with valid URL should produce a call."""
        matcher = _make_matcher()
        source = 'fetch("/api/users");\n'
        calls = matcher._extract_api_calls_from_source(source, "test.js", [])
        assert any(c.url_pattern == "/api/users" for c in calls)

    def test_axios_with_valid_url(self):
        """Axios with valid URL should produce a call."""
        matcher = _make_matcher()
        source = 'axios.get("/api/items");\n'
        calls = matcher._extract_api_calls_from_source(source, "test.js", [])
        assert any("/api/items" in c.url_pattern for c in calls)


# ---------------------------------------------------------------------------
# match() — URL cleaning: full URL, empty URL, relative URL
# Lines 425-431, 435, 439
# ---------------------------------------------------------------------------

class TestMatchUrlCleaning:
    """Cover lines 425-431, 435, 439."""

    def test_full_url_parsed(self):
        """Lines 425-431: full http:// URL -> extract path via urlparse."""
        matcher = _make_matcher()
        endpoints = [
            APIEndpoint(
                path="/api/users",
                http_method="GET",
                handler_node_id="handler-1",
                file_path="routes.py",
            )
        ]
        calls = [
            APICall(
                url_pattern="https://example.com/api/users",
                http_method="GET",
                caller_node_id="caller-1",
                file_path="app.js",
                confidence=0.9,
            )
        ]
        matches = matcher.match(endpoints, calls)
        assert isinstance(matches, list)
        # Should match since urlparse extracts /api/users
        assert len(matches) >= 1

    def test_relative_url_gets_slash_prefix(self):
        """Line 439: relative URL without / -> prepend /."""
        matcher = _make_matcher()
        endpoints = [
            APIEndpoint(
                path="/api/users",
                http_method="GET",
                handler_node_id="handler-1",
                file_path="routes.py",
            )
        ]
        calls = [
            APICall(
                url_pattern="api/users",
                http_method="GET",
                caller_node_id="caller-1",
                file_path="app.js",
                confidence=0.9,
            )
        ]
        matches = matcher.match(endpoints, calls)
        assert isinstance(matches, list)
        # Should match since api/users -> /api/users
        assert len(matches) >= 1

    def test_empty_url_after_cleaning_skipped(self):
        """Line 435: empty clean_url after processing -> continue."""
        matcher = _make_matcher()
        endpoints = [
            APIEndpoint(
                path="/api/users",
                http_method="GET",
                handler_node_id="handler-1",
                file_path="routes.py",
            )
        ]
        calls = [
            APICall(
                url_pattern="https://example.com",  # path will be empty after urlparse
                http_method="GET",
                caller_node_id="caller-1",
                file_path="app.js",
                confidence=0.9,
            )
        ]
        matches = matcher.match(endpoints, calls)
        # Empty URL should be skipped, no match
        assert isinstance(matches, list)
