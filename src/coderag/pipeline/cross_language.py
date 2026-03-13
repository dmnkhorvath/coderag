"""Cross-language matcher for CodeRAG.

Matches backend API endpoints (e.g., Laravel routes) to frontend API
calls (e.g., fetch/axios in JavaScript/TypeScript) using multi-strategy
URL matching.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from coderag.core.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    generate_node_id,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class APIEndpoint:
    """A backend API endpoint (e.g., a Laravel route)."""

    path: str  # URL path e.g. "/api/users/{id}"
    http_method: str  # GET, POST, PUT, DELETE
    handler_node_id: str  # Node ID of handler
    file_path: str
    name: str | None = None  # Named route


@dataclass(frozen=True)
class APICall:
    """A frontend API call (e.g., fetch or axios call)."""

    url_pattern: str  # URL pattern (may contain variables)
    http_method: str  # GET, POST, etc. or "UNKNOWN"
    caller_node_id: str  # Node ID of calling function
    file_path: str
    confidence: float = 1.0


@dataclass(frozen=True)
class CrossLanguageMatch:
    """A match between a backend endpoint and a frontend API call."""

    endpoint: APIEndpoint
    call: APICall
    match_strategy: str  # 'exact', 'parameterized', 'prefix', 'fuzzy'
    confidence: float


# ---------------------------------------------------------------------------
# Regex patterns for detecting API calls in JS/TS source
# ---------------------------------------------------------------------------

# fetch('url') or fetch(`url`)
_FETCH_RE = re.compile(
    r"""fetch\s*\(\s*
    (?:
        ['"](?P<url_str>[^'"]+)['"]          # String literal
        |
        `(?P<url_tpl>[^`]+)`                  # Template literal
    )""",
    re.VERBOSE,
)

# axios.get/post/put/patch/delete('url') or axios({url: 'url', method: 'get'})
_AXIOS_METHOD_RE = re.compile(
    r"""axios\s*\.\s*
    (?P<method>get|post|put|patch|delete|head|options|request)
    \s*\(\s*
    (?:
        ['"](?P<url_str>[^'"]+)['"]          # String literal
        |
        `(?P<url_tpl>[^`]+)`                  # Template literal
    )""",
    re.VERBOSE,
)

# axios({ url: '/path', method: 'get' })
_AXIOS_OBJ_RE = re.compile(
    r"""axios\s*\(\s*\{[^}]*
    url\s*:\s*['"](?P<url>[^'"]+)['"]        # url property
    [^}]*
    (?:method\s*:\s*['"](?P<method>[^'"]+)['"])? # optional method
    """,
    re.VERBOSE | re.DOTALL,
)

# $.ajax({ url: '/path', type/method: 'GET' })
_JQUERY_AJAX_RE = re.compile(
    r"""\$\s*\.\s*(?:ajax|get|post|getJSON)\s*\(
    (?:
        \s*['"](?P<url_direct>[^'"]+)['"]    # $.get('/url')
        |
        \s*\{[^}]*url\s*:\s*['"](?P<url_obj>[^'"]+)['"]  # $.ajax({url: '/url'})
    )""",
    re.VERBOSE | re.DOTALL,
)

# $.get/$.post shorthand method detection
_JQUERY_METHOD_MAP = {
    "get": "GET",
    "post": "POST",
    "getJSON": "GET",
    "ajax": "UNKNOWN",
}

# XMLHttpRequest.open('GET', '/url')
_XHR_RE = re.compile(
    r"""\.\.?open\s*\(\s*
    ['"](?P<method>[A-Z]+)['"]\s*,\s*
    ['"](?P<url>[^'"]+)['"]""",
    re.VERBOSE,
)

# Custom HTTP client wrappers: http.get(), client.post(), api.put(), $http.delete()
# Also handles TypeScript generics: http.get<Type>('url')
_CUSTOM_HTTP_RE = re.compile(
    r"""(?P<client>[a-zA-Z_$][a-zA-Z0-9_$]*)\s*\.\s*
    (?P<method>get|post|put|patch|delete|head|options|request)
    \s*(?:<[^>]*>)?\s*                                  # Optional TS generics
    \(\s*
    (?:
        ['"](?P<url_str>[^'"]+)['"]          # String literal
        |
        `(?P<url_tpl>[^`]+)`                  # Template literal
    )""",
    re.VERBOSE,
)

# Known HTTP client variable names (common patterns)
_HTTP_CLIENT_NAMES = {
    "http",
    "client",
    "api",
    "request",
    "req",
    "$http",
    "httpClient",
    "apiClient",
    "axiosInstance",
    "httpService",
    "apiService",
    "fetcher",
}


# ---------------------------------------------------------------------------
# URL normalization helpers
# ---------------------------------------------------------------------------

# Parameter patterns: {id}, $id, :id, ${variable}
_PARAM_RE = re.compile(
    r"(?:"
    r"\{[^}]+\}"  # {id}, {user_id}
    r"|\$[a-zA-Z_][a-zA-Z0-9_]*"  # $id
    r"|:[a-zA-Z_][a-zA-Z0-9_]*"  # :id
    r"|\$\{[^}]+\}"  # ${variable}
    r")"
)


def _normalize_url(url: str) -> str:
    """Normalize a URL by replacing all parameter patterns with {param}."""
    return _PARAM_RE.sub("{param}", url)


def _strip_query_and_fragment(url: str) -> str:
    """Remove query string and fragment from URL."""
    url = url.split("?")[0]
    url = url.split("#")[0]
    return url


def _clean_template_literal(url: str) -> str:
    """Clean template literal URLs by replacing ${...} with {param}."""
    return re.sub(r"\$\{[^}]+\}", "{param}", url)


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


# ---------------------------------------------------------------------------
# CrossLanguageMatcher
# ---------------------------------------------------------------------------


class CrossLanguageMatcher:
    """Match backend API endpoints to frontend API calls.

    Uses a multi-strategy matching pipeline:
    1. Exact match (confidence 0.95)
    2. Parameterized match (confidence 0.85)
    3. Prefix match (confidence 0.60)
    4. Fuzzy match (confidence 0.40)
    """

    def __init__(
        self,
        fuzzy_threshold: int = 3,
        min_path_segments: int = 2,
    ) -> None:
        self._fuzzy_threshold = fuzzy_threshold
        self._min_path_segments = min_path_segments

    def collect_endpoints(
        self,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[APIEndpoint]:
        """Collect API endpoints from ROUTE nodes.

        Finds ROUTE nodes that have HTTP method metadata and creates
        APIEndpoint objects from them.
        """
        endpoints: list[APIEndpoint] = []

        for node in nodes:
            if node.kind != NodeKind.ROUTE:
                continue

            http_method = node.metadata.get("http_method", "")
            url_pattern = node.metadata.get("url_pattern", "")

            if not url_pattern:
                # Try to extract from qualified_name (e.g., "GET /api/users")
                parts = node.qualified_name.split(" ", 1)
                if len(parts) == 2 and parts[0] in (
                    "GET",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                    "HEAD",
                ):
                    http_method = parts[0]
                    url_pattern = parts[1]
                else:
                    continue

            if not http_method:
                http_method = "GET"

            # Find the handler node via ROUTES_TO edges
            handler_id = node.id
            for edge in edges:
                if edge.source_id == node.id and edge.kind == EdgeKind.ROUTES_TO:
                    handler_id = edge.target_id
                    break

            endpoints.append(
                APIEndpoint(
                    path=url_pattern,
                    http_method=http_method.upper(),
                    handler_node_id=handler_id,
                    file_path=node.file_path,
                    name=node.metadata.get("route_name"),
                )
            )

        logger.info("Collected %d API endpoints", len(endpoints))
        return endpoints

    def collect_api_calls(
        self,
        nodes: list[Node],
        edges: list[Edge],
        project_root: str,
    ) -> list[APICall]:
        """Scan JS/TS source files for API calls.

        Searches for fetch(), axios, $.ajax(), and XMLHttpRequest patterns
        in JavaScript and TypeScript files.
        """
        calls: list[APICall] = []
        js_extensions = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

        # Get unique JS/TS file paths from nodes
        js_files: set[str] = set()
        for node in nodes:
            if node.kind == NodeKind.FILE and node.language in ("javascript", "typescript"):
                js_files.add(node.file_path)

        # Also scan for JS/TS files in the project
        if not js_files:
            for root, _dirs, files in os.walk(project_root):
                # Skip common non-source directories
                rel_root = os.path.relpath(root, project_root)
                if any(part in rel_root.split(os.sep) for part in ("node_modules", "vendor", ".git", "dist", "build")):
                    continue
                for fname in files:
                    ext = os.path.splitext(fname)[1]
                    if ext in js_extensions:
                        js_files.add(os.path.join(root, fname))

        # Build a map of function nodes by file and line for caller resolution
        func_map: dict[str, list[Node]] = {}
        for node in nodes:
            if node.kind in (NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.VARIABLE, NodeKind.CONSTANT):
                func_map.setdefault(node.file_path, []).append(node)

        for file_path in js_files:
            abs_path = file_path
            if not os.path.isabs(file_path):
                abs_path = os.path.join(project_root, file_path)

            if not os.path.isfile(abs_path):
                continue

            try:
                with open(abs_path, encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except OSError:
                continue

            rel_path = os.path.relpath(abs_path, project_root)
            # Try both absolute and relative paths for func_map lookup
            # (extractors may store either format)
            file_funcs = func_map.get(abs_path, func_map.get(rel_path, []))

            # Extract API calls from this file using abs_path
            # (matches the file_path format stored by extractors)
            file_calls = self._extract_api_calls_from_source(
                source,
                abs_path,
                file_funcs,
            )
            calls.extend(file_calls)

        logger.info("Collected %d API calls from %d JS/TS files", len(calls), len(js_files))
        return calls

    @staticmethod
    def _detect_api_prefixes(endpoints: list[APIEndpoint]) -> list[str]:
        """Detect common URL prefixes from API endpoints.

        Many frameworks (Laravel, Rails, etc.) mount API routes under a
        common prefix like ``/api/`` while frontend HTTP clients use
        relative URLs without that prefix.  This method discovers such
        prefixes so the matcher can try them automatically.
        """
        from collections import Counter

        if not endpoints:
            return []

        # Count first path segments (e.g., /api/users -> "api")
        prefix_counter: Counter[str] = Counter()
        for ep in endpoints:
            parts = [p for p in ep.path.split("/") if p]
            if len(parts) >= 2:
                prefix_counter[parts[0]] += 1

        # A prefix is "common" if it appears in >50% of endpoints
        threshold = len(endpoints) * 0.5
        prefixes: list[str] = []
        for prefix, count in prefix_counter.most_common(5):
            if count >= threshold:
                prefixes.append("/" + prefix)

        return prefixes

    def match(
        self,
        endpoints: list[APIEndpoint],
        calls: list[APICall],
    ) -> list[CrossLanguageMatch]:
        """Match API calls to endpoints using multi-strategy matching.

        Strategies (in order of confidence):
        1. Exact match (0.95): URL paths match exactly
        2. Parameterized match (0.85): After normalizing parameters
        3. Prefix match (0.60): URL prefix matches
        4. Fuzzy match (0.40): Levenshtein distance < threshold

        Handles relative URLs from custom HTTP clients by detecting common
        API prefixes (e.g., /api/) from endpoints and trying them.
        """
        matches: list[CrossLanguageMatch] = []
        matched_calls: set[int] = set()  # Track matched call indices

        # Detect common API prefixes from endpoints (e.g., /api/, /v1/, /rest/)
        api_prefixes = self._detect_api_prefixes(endpoints)

        # Pre-compute normalized endpoint paths
        endpoint_normalized = [(_normalize_url(_strip_query_and_fragment(ep.path)), ep) for ep in endpoints]

        for call_idx, call in enumerate(calls):
            clean_url = _strip_query_and_fragment(call.url_pattern)
            clean_url = _clean_template_literal(clean_url)

            # Skip non-API URLs
            if clean_url.startswith(("http://", "https://")):
                # Extract path from full URL
                try:
                    from urllib.parse import urlparse

                    parsed = urlparse(clean_url)
                    clean_url = parsed.path
                except Exception:
                    continue

            # Skip empty URLs
            if not clean_url:
                continue

            # Ensure URL starts with / (handle relative URLs from HTTP client wrappers)
            if not clean_url.startswith("/"):
                clean_url = "/" + clean_url

            # Generate candidate URLs: original + with detected API prefixes
            candidate_urls = [clean_url]
            for prefix in api_prefixes:
                prefixed = prefix + clean_url  # e.g., /api + /songs/123 = /api/songs/123
                if prefixed not in candidate_urls:
                    candidate_urls.append(prefixed)

            best_match: CrossLanguageMatch | None = None
            best_confidence = 0.0

            for candidate_url in candidate_urls:
                normalized_call = _normalize_url(candidate_url)

                for norm_ep_path, endpoint in endpoint_normalized:
                    # Check HTTP method compatibility
                    method_compatible = (
                        call.http_method == "UNKNOWN"
                        or endpoint.http_method == "ANY"
                        or call.http_method == endpoint.http_method
                    )
                    if not method_compatible:
                        continue

                    ep_path = _strip_query_and_fragment(endpoint.path)

                    # Strategy 1: Exact match
                    if candidate_url == ep_path:
                        confidence = 0.95 * call.confidence
                        if confidence > best_confidence:
                            best_match = CrossLanguageMatch(
                                endpoint=endpoint,
                                call=call,
                                match_strategy="exact",
                                confidence=confidence,
                            )
                            best_confidence = confidence
                        continue

                    # Strategy 2: Parameterized match
                    if normalized_call == norm_ep_path:
                        confidence = 0.85 * call.confidence
                        if confidence > best_confidence:
                            best_match = CrossLanguageMatch(
                                endpoint=endpoint,
                                call=call,
                                match_strategy="parameterized",
                                confidence=confidence,
                            )
                            best_confidence = confidence
                        continue

                    # Strategy 3: Prefix match
                    call_segments = [s for s in candidate_url.split("/") if s]
                    ep_segments = [s for s in ep_path.split("/") if s]

                    if len(call_segments) >= self._min_path_segments:
                        norm_call_segs = [_normalize_url(s) for s in call_segments]
                        norm_ep_segs = [_normalize_url(s) for s in ep_segments]

                        min_len = min(len(norm_call_segs), len(norm_ep_segs))
                        if min_len >= self._min_path_segments:
                            if norm_call_segs[:min_len] == norm_ep_segs[:min_len]:
                                confidence = 0.60 * call.confidence
                                if confidence > best_confidence:
                                    best_match = CrossLanguageMatch(
                                        endpoint=endpoint,
                                        call=call,
                                        match_strategy="prefix",
                                        confidence=confidence,
                                    )
                                    best_confidence = confidence
                                continue

                    # Strategy 4: Fuzzy match
                    if len(normalized_call) > 3 and len(norm_ep_path) > 3:
                        distance = _levenshtein_distance(normalized_call, norm_ep_path)
                        max_len = max(len(normalized_call), len(norm_ep_path))
                        if distance <= self._fuzzy_threshold and distance < max_len * 0.3:
                            confidence = 0.40 * call.confidence * (1 - distance / max_len)
                            if confidence > best_confidence:
                                best_match = CrossLanguageMatch(
                                    endpoint=endpoint,
                                    call=call,
                                    match_strategy="fuzzy",
                                    confidence=confidence,
                                )
                                best_confidence = confidence

            if best_match is not None:
                matches.append(best_match)
                matched_calls.add(call_idx)

        logger.info(
            "Matched %d/%d API calls to %d endpoints",
            len(matches),
            len(calls),
            len(endpoints),
        )
        return matches

    def create_edges(self, matches: list[CrossLanguageMatch]) -> list[Edge]:
        """Create API_CALLS edges from cross-language matches."""
        edges: list[Edge] = []

        for m in matches:
            edges.append(
                Edge(
                    source_id=m.call.caller_node_id,
                    target_id=m.endpoint.handler_node_id,
                    kind=EdgeKind.API_CALLS,
                    confidence=m.confidence,
                    metadata={
                        "match_strategy": m.match_strategy,
                        "call_url": m.call.url_pattern,
                        "endpoint_url": m.endpoint.path,
                        "http_method": m.endpoint.http_method,
                        "call_file": m.call.file_path,
                        "endpoint_file": m.endpoint.file_path,
                        "cross_language": True,
                    },
                )
            )

        return edges

    # ── Private helpers ───────────────────────────────────────

    def _extract_api_calls_from_source(
        self,
        source: str,
        file_path: str,
        func_nodes: list[Node],
    ) -> list[APICall]:
        """Extract API calls from a single JS/TS source file."""
        calls: list[APICall] = []

        # fetch() calls
        for match in _FETCH_RE.finditer(source):
            url = match.group("url_str") or match.group("url_tpl") or ""
            if not url:
                continue

            line_no = source[: match.start()].count("\n") + 1
            http_method = self._detect_fetch_method(source, match.start())
            caller_id = self._find_enclosing_function(line_no, func_nodes, file_path)

            calls.append(
                APICall(
                    url_pattern=url,
                    http_method=http_method,
                    caller_node_id=caller_id,
                    file_path=file_path,
                    confidence=0.9 if match.group("url_str") else 0.7,
                )
            )

        # axios.method() calls
        for match in _AXIOS_METHOD_RE.finditer(source):
            url = match.group("url_str") or match.group("url_tpl") or ""
            if not url:
                continue

            method = match.group("method").upper()
            if method == "REQUEST":
                method = "UNKNOWN"

            line_no = source[: match.start()].count("\n") + 1
            caller_id = self._find_enclosing_function(line_no, func_nodes, file_path)

            calls.append(
                APICall(
                    url_pattern=url,
                    http_method=method,
                    caller_node_id=caller_id,
                    file_path=file_path,
                    confidence=0.9 if match.group("url_str") else 0.7,
                )
            )

        # axios({url: ..., method: ...}) calls
        for match in _AXIOS_OBJ_RE.finditer(source):
            url = match.group("url")
            method = (match.group("method") or "UNKNOWN").upper()

            line_no = source[: match.start()].count("\n") + 1
            caller_id = self._find_enclosing_function(line_no, func_nodes, file_path)

            calls.append(
                APICall(
                    url_pattern=url,
                    http_method=method,
                    caller_node_id=caller_id,
                    file_path=file_path,
                    confidence=0.85,
                )
            )

        # jQuery $.ajax/$.get/$.post calls
        for match in _JQUERY_AJAX_RE.finditer(source):
            url = match.group("url_direct") or match.group("url_obj") or ""
            if not url:
                continue

            # Detect method from jQuery shorthand
            jquery_method = re.search(
                r"\$\s*\.\s*(get|post|getJSON|ajax)",
                source[match.start() : match.start() + 30],
            )
            method = "UNKNOWN"
            if jquery_method:
                method = _JQUERY_METHOD_MAP.get(jquery_method.group(1), "UNKNOWN")

            line_no = source[: match.start()].count("\n") + 1
            caller_id = self._find_enclosing_function(line_no, func_nodes, file_path)

            calls.append(
                APICall(
                    url_pattern=url,
                    http_method=method,
                    caller_node_id=caller_id,
                    file_path=file_path,
                    confidence=0.85,
                )
            )

        # XMLHttpRequest.open() calls
        for match in _XHR_RE.finditer(source):
            url = match.group("url")
            method = match.group("method").upper()

            line_no = source[: match.start()].count("\n") + 1
            caller_id = self._find_enclosing_function(line_no, func_nodes, file_path)

            calls.append(
                APICall(
                    url_pattern=url,
                    http_method=method,
                    caller_node_id=caller_id,
                    file_path=file_path,
                    confidence=0.80,
                )
            )

        # Custom HTTP client wrappers: http.get(), client.post(), api.put(), etc.
        for match in _CUSTOM_HTTP_RE.finditer(source):
            client_name = match.group("client")
            # Only match known HTTP client names or common patterns
            if client_name.lower() not in _HTTP_CLIENT_NAMES and not any(
                client_name.lower().endswith(suffix) for suffix in ("client", "http", "api", "service", "request")
            ):
                continue

            url = match.group("url_str") or match.group("url_tpl") or ""
            if not url:
                continue

            method = match.group("method").upper()
            if method == "REQUEST":
                method = "UNKNOWN"

            line_no = source[: match.start()].count("\n") + 1
            caller_id = self._find_enclosing_function(line_no, func_nodes, file_path)

            calls.append(
                APICall(
                    url_pattern=url,
                    http_method=method,
                    caller_node_id=caller_id,
                    file_path=file_path,
                    confidence=0.85 if match.group("url_str") else 0.65,
                )
            )

        return calls

    def _detect_fetch_method(
        self,
        source: str,
        fetch_pos: int,
    ) -> str:
        """Detect HTTP method from fetch() options.

        Looks for { method: 'POST' } in the fetch call arguments.
        Defaults to GET if no method specified.
        """
        # Look at the next ~500 chars for method option
        window = source[fetch_pos : fetch_pos + 500]
        method_match = re.search(
            r"""method\s*:\s*['"](?P<method>[A-Z]+)['"]""",
            window,
        )
        if method_match:
            return method_match.group("method").upper()
        return "GET"

    def _find_enclosing_function(
        self,
        line_no: int,
        func_nodes: list[Node],
        file_path: str,
    ) -> str:
        """Find the function node that encloses a given line."""
        candidates = [
            n
            for n in func_nodes
            if n.file_path == file_path
            and n.start_line is not None
            and n.end_line is not None
            and n.start_line <= line_no <= n.end_line
        ]

        if candidates:
            # Return the most specific (smallest range)
            best = min(
                candidates,
                key=lambda n: (n.end_line or 0) - (n.start_line or 0),
            )
            return best.id

        # Fall back to the FILE node (extractors use line 1 for FILE nodes)
        return generate_node_id(file_path, 1, NodeKind.FILE, file_path)
