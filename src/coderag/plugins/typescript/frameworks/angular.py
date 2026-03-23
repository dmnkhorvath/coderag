"""Angular framework detector for CodeRAG.

Detects Angular-specific patterns including components, services,
modules, directives, pipes, routing, dependency injection, signals,
and RxJS patterns from TypeScript source files.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from coderag.core.models import (
    Edge,
    EdgeKind,
    FrameworkPattern,
    Node,
    NodeKind,
    generate_node_id,
)
from coderag.core.registry import FrameworkDetector

logger = logging.getLogger(__name__)

# =============================================================================
# Regex patterns for Angular decorator detection
# =============================================================================

# @Component decorator
_COMPONENT_DECORATOR_RE = re.compile(
    r"@Component\s*\(\s*\{",
    re.MULTILINE,
)
# Extract selector from @Component
_COMPONENT_SELECTOR_RE = re.compile(
    r"""selector\s*:\s*['"](?P<selector>[^'"]+)['"]""",
)
# Extract templateUrl
_TEMPLATE_URL_RE = re.compile(
    r"""templateUrl\s*:\s*['"](?P<url>[^'"]+)['"]""",
)
# Extract styleUrls
_STYLE_URLS_RE = re.compile(
    r"""styleUrls\s*:\s*\[(?P<urls>[^\]]*)\]""",
)
# Extract single styleUrl (Angular 17+)
_STYLE_URL_SINGLE_RE = re.compile(
    r"""styleUrl\s*:\s*['"](?P<url>[^'"]+)['"]""",
)
# Standalone component flag
_STANDALONE_RE = re.compile(
    r"standalone\s*:\s*true",
)
# @Injectable decorator
_INJECTABLE_RE = re.compile(
    r"@Injectable\s*\(\s*(?:\{[^}]*\})?\s*\)",
)
# providedIn from @Injectable
_PROVIDED_IN_RE = re.compile(
    r"""providedIn\s*:\s*['"](?P<scope>[^'"]+)['"]""",
)
# @NgModule decorator
_NG_MODULE_RE = re.compile(
    r"@NgModule\s*\(\s*\{",
    re.MULTILINE,
)
# @Directive decorator
_DIRECTIVE_RE = re.compile(
    r"@Directive\s*\(\s*\{",
    re.MULTILINE,
)
# Directive selector
_DIRECTIVE_SELECTOR_RE = re.compile(
    r"""selector\s*:\s*['"](?P<selector>[^'"]+)['"]""",
)
# @Pipe decorator
_PIPE_RE = re.compile(
    r"@Pipe\s*\(\s*\{",
    re.MULTILINE,
)
_PIPE_NAME_RE = re.compile(
    r"""name\s*:\s*['"](?P<name>[^'"]+)['"]""",
)

# =============================================================================
# Regex patterns for NgModule arrays
# =============================================================================

_DECLARATIONS_RE = re.compile(
    r"declarations\s*:\s*\[(?P<items>[^\]]*)\]",
    re.DOTALL,
)
_MODULE_IMPORTS_RE = re.compile(
    r"imports\s*:\s*\[(?P<items>[^\]]*)\]",
    re.DOTALL,
)
_MODULE_EXPORTS_RE = re.compile(
    r"exports\s*:\s*\[(?P<items>[^\]]*)\]",
    re.DOTALL,
)
_PROVIDERS_RE = re.compile(
    r"providers\s*:\s*\[(?P<items>[^\]]*)\]",
    re.DOTALL,
)
_BOOTSTRAP_RE = re.compile(
    r"bootstrap\s*:\s*\[(?P<items>[^\]]*)\]",
    re.DOTALL,
)

# =============================================================================
# Regex patterns for class detection (used to find enclosing class)
# =============================================================================

_CLASS_DECL_RE = re.compile(
    r"(?:export\s+)?class\s+(?P<name>[A-Z]\w*)\b",
)

# =============================================================================
# Regex patterns for dependency injection
# =============================================================================

# Constructor injection: constructor(private xxxService: XxxService)
_CONSTRUCTOR_INJECT_RE = re.compile(
    r"constructor\s*\([^)]*?"
    r"\b(?:private|public|protected|readonly)\s+"
    r"(?P<param>\w+)\s*:\s*(?P<type>[A-Z]\w+)",
    re.DOTALL,
)
# All constructor params with access modifiers (for multi-param)
_CONSTRUCTOR_PARAMS_RE = re.compile(
    r"\b(?:private|public|protected|readonly)\s+"
    r"(?P<param>\w+)\s*:\s*(?P<type>[A-Z]\w+)",
)
# inject() function (Angular 14+)
_INJECT_FN_RE = re.compile(
    r"(?P<name>\w+)\s*=\s*inject\s*\(\s*(?P<type>[A-Z]\w+)\s*\)",
)

# =============================================================================
# Regex patterns for routing
# =============================================================================

# Route definitions: { path: 'xxx', component: Xxx }
_ROUTE_PATH_RE = re.compile(r"""path\s*:\s*['"](?P<path>[^'"]*)['"]""")
_ROUTE_COMPONENT_RE = re.compile(
    r"component\s*:\s*(?P<comp>[A-Z]\w+)",
)
_ROUTE_LAZY_RE = re.compile(
    r"""loadComponent\s*:\s*\(\)\s*=>\s*import\s*\(['"](?P<module>[^'"]+)['"]\)""",
)
_ROUTE_LAZY_CHILDREN_RE = re.compile(
    r"""loadChildren\s*:\s*\(\)\s*=>\s*import\s*\(['"](?P<module>[^'"]+)['"]\)""",
)
# Route guards (resolve removed — handled separately)
_ROUTE_GUARD_RE = re.compile(
    r"(?:canActivate|canDeactivate|canMatch)\s*:\s*\[(?P<guards>[^\]]*)\]",
)
# Route resolve (separate from guards)
_ROUTE_RESOLVE_RE = re.compile(
    r"resolve\s*:\s*(?:(?:\{(?P<obj>[^}]*)\})|(?:\[(?P<arr>[^\]]*)\]))",
)
# Routes array declaration
_ROUTES_ARRAY_RE = re.compile(
    r"(?:const|let|var)\s+\w+\s*(?::\s*Routes)?\s*=\s*\[",
)

# =============================================================================
# Regex patterns for signals (Angular 16+)
# =============================================================================

_SIGNAL_RE = re.compile(
    r"(?P<name>\w+)\s*=\s*signal\s*[<(]",
)
_COMPUTED_SIGNAL_RE = re.compile(
    r"(?P<name>\w+)\s*=\s*computed\s*\(",
)
_EFFECT_RE = re.compile(
    r"\beffect\s*\(",
)
# Signal getter calls inside computed() bodies: this.someSignal() or someSignal()
_SIGNAL_CALL_RE = re.compile(
    r"(?:this\.)?(?P<signal>\w+)\(\)",
)

# =============================================================================
# Regex patterns for RxJS
# =============================================================================

_OBSERVABLE_RE = re.compile(
    r":\s*Observable\s*<",
)
_SUBJECT_RE = re.compile(
    r"new\s+(?P<type>Subject|BehaviorSubject|ReplaySubject|AsyncSubject)\s*[<(]",
)
_SUBSCRIBE_RE = re.compile(
    r"\.subscribe\s*\(",
)
_PIPE_OPERATOR_RE = re.compile(
    r"\.pipe\s*\(",
)
_HTTP_CLIENT_RE = re.compile(
    r"\bthis\.http\.(?P<method>get|post|put|delete|patch)\s*[<(]",
)
_HTTP_CLIENT_URL_RE = re.compile(
    r"""\bthis\.http\.(?P<method>get|post|put|delete|patch)\s*(?:<[^>]*>)?\s*\(\s*['"`](?P<url>[^'"`]+)['"`]""",
)

# =============================================================================
# Regex patterns for template analysis (inline templates)
# =============================================================================

_INLINE_TEMPLATE_RE = re.compile(
    r"template\s*:\s*`(?P<template>[^`]*)`",
    re.DOTALL,
)
# Component selectors in templates (app-xxx pattern)
_TEMPLATE_SELECTOR_RE = re.compile(
    r"<(?P<tag>app-[a-z][a-z0-9-]*)\b",
)
# Angular structural directives in templates
_NG_DIRECTIVE_RE = re.compile(
    r"\*(?:ngIf|ngFor|ngSwitch)|\[ngClass\]|\[ngStyle\]",
)
# New control flow syntax (@if, @for, @switch, @defer)
_NEW_CONTROL_FLOW_RE = re.compile(
    r"@(?:if|for|switch|defer)\b",
)
# Event bindings in templates
_EVENT_BINDING_RE = re.compile(
    r"\((?P<event>[a-zA-Z]+)\)\s*=",
)
# Property bindings in templates
_PROPERTY_BINDING_RE = re.compile(
    r"\[(?P<prop>[a-zA-Z]+)\]\s*=",
)

# =============================================================================
# NEW: Regex patterns for advanced template analysis
# =============================================================================

# Pipe usage in templates: | pipeName
_PIPE_USAGE_RE = re.compile(
    r"\|\s*(?P<pipe>[a-zA-Z]\w*)",
)
# Custom attribute directives: [appHighlight], [appTooltip] etc.
_CUSTOM_DIRECTIVE_RE = re.compile(
    r"\[(?P<dir>app[A-Z]\w+)\]",
)
# <ng-content> projection
_NG_CONTENT_RE = re.compile(
    r"<ng-content",
)
# Async pipe in templates
_ASYNC_PIPE_RE = re.compile(
    r"\|\s*async\b",
)

# =============================================================================
# Regex for extracting decorator block content
# =============================================================================

_DECORATOR_BLOCK_RE = re.compile(
    r"@(?P<name>Component|Injectable|NgModule|Directive|Pipe)\s*\(",
)

# =============================================================================
# Constants
# =============================================================================

# Native DOM events to skip for angular_emits_output
_NATIVE_DOM_EVENTS = frozenset({
    "click", "dblclick", "submit", "change", "input", "focus", "blur",
    "keyup", "keydown", "keypress", "mouseover", "mouseout", "mouseenter",
    "mouseleave", "mousedown", "mouseup", "scroll", "load", "error",
    "resize", "contextmenu", "drag", "dragstart", "dragend", "dragover",
    "dragenter", "dragleave", "drop", "touchstart", "touchend",
    "touchmove", "wheel",
})

# Built-in Angular pipes to skip for pipe usage detection
_BUILTIN_PIPES = frozenset({
    "date", "uppercase", "lowercase", "currency", "decimal", "percent",
    "json", "slice", "async", "titlecase", "keyvalue", "i18nPlural",
    "i18nSelect", "number",
})


def _extract_decorator_block(source_text: str, match_start: int) -> str:
    """Extract the full decorator argument block from the opening paren.

    Handles nested braces and parentheses to find the matching closing paren.
    """
    # Find the opening paren after the decorator name
    paren_start = source_text.find("(", match_start)
    if paren_start == -1:
        return ""

    depth = 0
    i = paren_start
    while i < len(source_text):
        ch = source_text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return source_text[paren_start + 1 : i]
        elif ch in ("'", '"', "`"):
            # Skip string literals
            quote = ch
            i += 1
            while i < len(source_text) and source_text[i] != quote:
                if source_text[i] == "\\":
                    i += 1  # skip escaped char
                i += 1
        i += 1
    return source_text[paren_start + 1 :]


def _extract_list_items(text: str) -> list[str]:
    """Extract identifiers from a comma-separated list string.

    Handles items like: ComponentA, ComponentB, SomeModule.forRoot()
    Returns just the identifier names.
    """
    items: list[str] = []
    for raw in text.split(","):
        raw = raw.strip()
        # Remove .forRoot(), .forChild() etc.
        raw = re.sub(r"\.\w+\([^)]*\)", "", raw)
        # Remove any remaining parens/brackets
        raw = re.sub(r"[()\[\]{}]", "", raw).strip()
        if raw and re.match(r"^[A-Za-z_]\w*$", raw):
            items.append(raw)
    return items


def _line_of(source_text: str, pos: int) -> int:
    """Return 1-based line number for a character position."""
    return source_text[:pos].count("\n") + 1


def _extract_computed_body(source_text: str, match_start: int) -> str:
    """Extract the body of a computed() call for signal dependency analysis."""
    paren_start = source_text.find("(", match_start)
    if paren_start == -1:
        return ""
    depth = 0
    i = paren_start
    while i < len(source_text):
        ch = source_text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return source_text[paren_start + 1 : i]
        elif ch in ("'", '"', "`"):
            quote = ch
            i += 1
            while i < len(source_text) and source_text[i] != quote:
                if source_text[i] == "\\":
                    i += 1
                i += 1
        i += 1
    return source_text[paren_start + 1 :]


class AngularDetector(FrameworkDetector):
    """Detect Angular framework patterns in TypeScript projects."""

    @property
    def framework_name(self) -> str:
        return "angular"

    # -- Project-level detection ----------------------------------------

    def detect_framework(self, project_root: str) -> bool:
        """Check for angular.json or @angular/core in package.json."""
        # Check for angular.json
        angular_json = os.path.join(project_root, "angular.json")
        if os.path.isfile(angular_json):
            return True

        # Check for .angular-cli.json (older Angular CLI)
        angular_cli_json = os.path.join(project_root, ".angular-cli.json")
        if os.path.isfile(angular_cli_json):
            return True

        # Check package.json for @angular/core
        pkg_json = os.path.join(project_root, "package.json")
        if not os.path.isfile(pkg_json):
            return False

        try:
            with open(pkg_json, encoding="utf-8") as f:
                data = json.load(f)
            deps = data.get("dependencies", {})
            dev_deps = data.get("devDependencies", {})
            return "@angular/core" in deps or "@angular/core" in dev_deps
        except (json.JSONDecodeError, OSError):
            return False

    # -- Per-file detection ---------------------------------------------

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect per-file Angular patterns from already-extracted AST data.

        Identifies:
        - @Component, @Injectable, @NgModule, @Directive, @Pipe decorators
        - Dependency injection (constructor + inject())
        - Route definitions
        - Signals (signal, computed, effect)
        - RxJS patterns and HTTP client calls
        - Inline template analysis
        """
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        # Only process TypeScript files
        if not file_path.endswith((".ts", ".tsx")):
            return patterns

        # -- Decorator detection ----------------------------------------
        comp = self._detect_component(file_path, nodes, source_text)
        if comp:
            patterns.append(comp)

        svc = self._detect_service(file_path, nodes, source_text)
        if svc:
            patterns.append(svc)

        mod = self._detect_module(file_path, nodes, source_text)
        if mod:
            patterns.append(mod)

        directive = self._detect_directive(file_path, nodes, source_text)
        if directive:
            patterns.append(directive)

        pipe = self._detect_pipe(file_path, nodes, source_text)
        if pipe:
            patterns.append(pipe)

        # -- Routing ----------------------------------------------------
        routes = self._detect_routes(file_path, nodes, source_text)
        if routes:
            patterns.append(routes)

        # -- Dependency injection ---------------------------------------
        di = self._detect_dependency_injection(file_path, nodes, source_text)
        if di:
            patterns.append(di)

        # -- Signals ----------------------------------------------------
        signals = self._detect_signals(file_path, nodes, source_text)
        if signals:
            patterns.append(signals)

        # -- RxJS / HTTP ------------------------------------------------
        rxjs = self._detect_rxjs_patterns(file_path, nodes, source_text)
        if rxjs:
            patterns.append(rxjs)

        return patterns

    # -- Global patterns ------------------------------------------------

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Angular patterns.

        Connects DI edges across files and resolves route-to-component
        relationships that span multiple files.
        """
        patterns: list[FrameworkPattern] = []

        # Connect DI edges: resolve injected type names to actual service nodes
        di_pattern = self._connect_cross_file_di(store)
        if di_pattern:
            patterns.append(di_pattern)

        return patterns

    # =================================================================
    # Private helpers -- decorator detection
    # =================================================================

    def _detect_component(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect @Component decorated classes."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        for match in _COMPONENT_DECORATOR_RE.finditer(source_text):
            line_no = _line_of(source_text, match.start())
            block = _extract_decorator_block(source_text, match.start())

            # Extract metadata from decorator
            selector = ""
            sel_m = _COMPONENT_SELECTOR_RE.search(block)
            if sel_m:
                selector = sel_m.group("selector")

            template_url = ""
            tpl_m = _TEMPLATE_URL_RE.search(block)
            if tpl_m:
                template_url = tpl_m.group("url")

            style_urls: list[str] = []
            sty_m = _STYLE_URLS_RE.search(block)
            if sty_m:
                raw = sty_m.group("urls")
                style_urls = re.findall(r"""['"]([^'"]+)['"]""", raw)

            # Angular 17+ single styleUrl
            sty_single_m = _STYLE_URL_SINGLE_RE.search(block)
            if sty_single_m:
                single_url = sty_single_m.group("url")
                if single_url not in style_urls:
                    style_urls.append(single_url)

            standalone = bool(_STANDALONE_RE.search(block))

            # Find the class name after the decorator
            class_node = self._find_enclosing_class(line_no, nodes)
            class_name = class_node.name if class_node else None

            if not class_name:
                # Try regex fallback
                after_decorator = source_text[match.start() :]
                cls_m = _CLASS_DECL_RE.search(after_decorator)
                if cls_m:
                    class_name = cls_m.group("name")
                    line_no = _line_of(source_text, match.start() + cls_m.start())

            if not class_name:
                continue

            comp_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.COMPONENT, class_name),
                kind=NodeKind.COMPONENT,
                name=class_name,
                qualified_name=class_name,
                file_path=file_path,
                start_line=line_no,
                end_line=class_node.end_line if class_node else line_no + 20,
                language="typescript",
                metadata={
                    "framework": "angular",
                    "angular_type": "component",
                    "selector": selector,
                    "standalone": standalone,
                    "templateUrl": template_url,
                    "styleUrls": style_urls,
                    "original_node_id": class_node.id if class_node else None,
                },
            )
            new_nodes.append(comp_node)

            # --- Edge #9: angular_template_ref ---
            if template_url:
                new_edges.append(
                    Edge(
                        source_id=comp_node.id,
                        target_id=f"__unresolved__:template:{template_url}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "angular",
                            "angular_edge_type": "angular_template_ref",
                            "template_url": template_url,
                        },
                    )
                )

            # --- Edge #10: angular_style_ref ---
            for style_url in style_urls:
                new_edges.append(
                    Edge(
                        source_id=comp_node.id,
                        target_id=f"__unresolved__:stylesheet:{style_url}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.95,
                        line_number=line_no,
                        metadata={
                            "framework": "angular",
                            "angular_edge_type": "angular_style_ref",
                            "style_url": style_url,
                        },
                    )
                )

            # Analyze inline template for child component references
            inline_tpl_m = _INLINE_TEMPLATE_RE.search(block)
            if inline_tpl_m:
                template_text = inline_tpl_m.group("template")

                # Existing: angular_renders_component
                for sel_match in _TEMPLATE_SELECTOR_RE.finditer(template_text):
                    child_tag = sel_match.group("tag")
                    new_edges.append(
                        Edge(
                            source_id=comp_node.id,
                            target_id=f"__unresolved__:component:{child_tag}",
                            kind=EdgeKind.RENDERS,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_renders_component",
                                "child_selector": child_tag,
                            },
                        )
                    )

                # --- Edge #2: angular_uses_pipe ---
                seen_pipes: set[str] = set()
                for pipe_match in _PIPE_USAGE_RE.finditer(template_text):
                    pipe_name = pipe_match.group("pipe")
                    # Skip built-in pipes and async (handled separately)
                    if pipe_name in _BUILTIN_PIPES or pipe_name in seen_pipes:
                        continue
                    seen_pipes.add(pipe_name)
                    new_edges.append(
                        Edge(
                            source_id=comp_node.id,
                            target_id=f"__unresolved__:pipe:{pipe_name}",
                            kind=EdgeKind.DEPENDS_ON,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_uses_pipe",
                                "pipe_name": pipe_name,
                            },
                        )
                    )

                # --- Edge #3: angular_uses_directive ---
                seen_directives: set[str] = set()
                for dir_match in _CUSTOM_DIRECTIVE_RE.finditer(template_text):
                    directive_name = dir_match.group("dir")
                    if directive_name in seen_directives:
                        continue
                    seen_directives.add(directive_name)
                    new_edges.append(
                        Edge(
                            source_id=comp_node.id,
                            target_id=f"__unresolved__:directive:{directive_name}",
                            kind=EdgeKind.DEPENDS_ON,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_uses_directive",
                                "directive_name": directive_name,
                            },
                        )
                    )

                # --- Edge #4: angular_binds_input ---
                seen_inputs: set[str] = set()
                for prop_match in _PROPERTY_BINDING_RE.finditer(template_text):
                    prop_name = prop_match.group("prop")
                    if prop_name in seen_inputs:
                        continue
                    # Skip custom directive bindings (app-prefixed)
                    if re.match(r"^app[A-Z]", prop_name):
                        continue
                    seen_inputs.add(prop_name)
                    new_edges.append(
                        Edge(
                            source_id=comp_node.id,
                            target_id=f"__unresolved__:input:{prop_name}",
                            kind=EdgeKind.PASSES_PROP,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_binds_input",
                                "input_name": prop_name,
                            },
                        )
                    )

                # --- Edge #5: angular_emits_output ---
                seen_outputs: set[str] = set()
                for evt_match in _EVENT_BINDING_RE.finditer(template_text):
                    event_name = evt_match.group("event")
                    if event_name in _NATIVE_DOM_EVENTS or event_name in seen_outputs:
                        continue
                    seen_outputs.add(event_name)
                    new_edges.append(
                        Edge(
                            source_id=comp_node.id,
                            target_id=f"__unresolved__:output:{event_name}",
                            kind=EdgeKind.LISTENS_TO,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_emits_output",
                                "event_name": event_name,
                            },
                        )
                    )

                # --- Edge #6: angular_projects_content ---
                if _NG_CONTENT_RE.search(template_text):
                    new_edges.append(
                        Edge(
                            source_id=comp_node.id,
                            target_id=f"__unresolved__:projection:{comp_node.name}",
                            kind=EdgeKind.RENDERS,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_projects_content",
                                "component_name": comp_node.name,
                            },
                        )
                    )

                # --- Edge #7 (partial): angular_subscribes_to (async pipe) ---
                if _ASYNC_PIPE_RE.search(template_text):
                    new_edges.append(
                        Edge(
                            source_id=comp_node.id,
                            target_id="__unresolved__:observable:async_pipe",
                            kind=EdgeKind.DEPENDS_ON,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_subscribes_to",
                                "subscribe_type": "async_pipe",
                            },
                        )
                    )

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="components",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"component_count": len(new_nodes)},
        )

    def _detect_service(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect @Injectable decorated classes (services)."""
        new_nodes: list[Node] = []

        for match in _INJECTABLE_RE.finditer(source_text):
            line_no = _line_of(source_text, match.start())
            block = match.group(0)

            provided_in = ""
            prov_m = _PROVIDED_IN_RE.search(block)
            if prov_m:
                provided_in = prov_m.group("scope")

            # Find the class name
            class_node = self._find_enclosing_class(line_no, nodes)
            class_name = class_node.name if class_node else None

            if not class_name:
                after_decorator = source_text[match.start() :]
                cls_m = _CLASS_DECL_RE.search(after_decorator)
                if cls_m:
                    class_name = cls_m.group("name")
                    line_no = _line_of(source_text, match.start() + cls_m.start())

            if not class_name:
                continue

            svc_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.PROVIDER, class_name),
                kind=NodeKind.PROVIDER,
                name=class_name,
                qualified_name=class_name,
                file_path=file_path,
                start_line=line_no,
                end_line=class_node.end_line if class_node else line_no + 20,
                language="typescript",
                metadata={
                    "framework": "angular",
                    "angular_type": "service",
                    "providedIn": provided_in,
                    "original_node_id": class_node.id if class_node else None,
                },
            )
            new_nodes.append(svc_node)

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="services",
            nodes=new_nodes,
            edges=[],
            metadata={"service_count": len(new_nodes)},
        )

    def _detect_module(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect @NgModule decorated classes and their metadata arrays."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        for match in _NG_MODULE_RE.finditer(source_text):
            line_no = _line_of(source_text, match.start())
            block = _extract_decorator_block(source_text, match.start())

            # Find the class name
            class_node = self._find_enclosing_class(line_no, nodes)
            class_name = class_node.name if class_node else None

            if not class_name:
                after_decorator = source_text[match.start() :]
                cls_m = _CLASS_DECL_RE.search(after_decorator)
                if cls_m:
                    class_name = cls_m.group("name")
                    line_no = _line_of(source_text, match.start() + cls_m.start())

            if not class_name:
                continue

            mod_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MODULE, class_name),
                kind=NodeKind.MODULE,
                name=class_name,
                qualified_name=class_name,
                file_path=file_path,
                start_line=line_no,
                end_line=class_node.end_line if class_node else line_no + 30,
                language="typescript",
                metadata={
                    "framework": "angular",
                    "angular_type": "module",
                    "original_node_id": class_node.id if class_node else None,
                },
            )
            new_nodes.append(mod_node)

            # Parse NgModule metadata arrays
            # declarations -> CONTAINS edges
            decl_m = _DECLARATIONS_RE.search(block)
            if decl_m:
                for item in _extract_list_items(decl_m.group("items")):
                    new_edges.append(
                        Edge(
                            source_id=mod_node.id,
                            target_id=f"__unresolved__:component:{item}",
                            kind=EdgeKind.CONTAINS,
                            confidence=0.92,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_declares",
                                "declared_name": item,
                            },
                        )
                    )

            # imports -> IMPORTS edges
            imp_m = _MODULE_IMPORTS_RE.search(block)
            if imp_m:
                for item in _extract_list_items(imp_m.group("items")):
                    new_edges.append(
                        Edge(
                            source_id=mod_node.id,
                            target_id=f"__unresolved__:module:{item}",
                            kind=EdgeKind.IMPORTS,
                            confidence=0.92,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_imports_module",
                                "imported_module": item,
                            },
                        )
                    )

            # exports -> EXPORTS edges
            exp_m = _MODULE_EXPORTS_RE.search(block)
            if exp_m:
                for item in _extract_list_items(exp_m.group("items")):
                    new_edges.append(
                        Edge(
                            source_id=mod_node.id,
                            target_id=f"__unresolved__:component:{item}",
                            kind=EdgeKind.EXPORTS,
                            confidence=0.92,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_exports",
                                "exported_name": item,
                            },
                        )
                    )

            # providers -> PROVIDES_CONTEXT edges
            prov_m = _PROVIDERS_RE.search(block)
            if prov_m:
                for item in _extract_list_items(prov_m.group("items")):
                    new_edges.append(
                        Edge(
                            source_id=mod_node.id,
                            target_id=f"__unresolved__:service:{item}",
                            kind=EdgeKind.PROVIDES_CONTEXT,
                            confidence=0.90,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_provides",
                                "provided_service": item,
                            },
                        )
                    )

            # bootstrap -> RENDERS edges
            boot_m = _BOOTSTRAP_RE.search(block)
            if boot_m:
                for item in _extract_list_items(boot_m.group("items")):
                    new_edges.append(
                        Edge(
                            source_id=mod_node.id,
                            target_id=f"__unresolved__:component:{item}",
                            kind=EdgeKind.RENDERS,
                            confidence=0.95,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_bootstraps",
                                "bootstrapped_component": item,
                            },
                        )
                    )

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="modules",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "module_count": len(new_nodes),
                "edge_count": len(new_edges),
            },
        )

    def _detect_directive(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect @Directive decorated classes."""
        new_nodes: list[Node] = []

        for match in _DIRECTIVE_RE.finditer(source_text):
            line_no = _line_of(source_text, match.start())
            block = _extract_decorator_block(source_text, match.start())

            selector = ""
            sel_m = _DIRECTIVE_SELECTOR_RE.search(block)
            if sel_m:
                selector = sel_m.group("selector")

            class_node = self._find_enclosing_class(line_no, nodes)
            class_name = class_node.name if class_node else None

            if not class_name:
                after_decorator = source_text[match.start() :]
                cls_m = _CLASS_DECL_RE.search(after_decorator)
                if cls_m:
                    class_name = cls_m.group("name")
                    line_no = _line_of(source_text, match.start() + cls_m.start())

            if not class_name:
                continue

            dir_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.COMPONENT, class_name),
                kind=NodeKind.COMPONENT,
                name=class_name,
                qualified_name=class_name,
                file_path=file_path,
                start_line=line_no,
                end_line=class_node.end_line if class_node else line_no + 15,
                language="typescript",
                metadata={
                    "framework": "angular",
                    "angular_type": "directive",
                    "selector": selector,
                    "original_node_id": class_node.id if class_node else None,
                },
            )
            new_nodes.append(dir_node)

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="directives",
            nodes=new_nodes,
            edges=[],
            metadata={"directive_count": len(new_nodes)},
        )

    def _detect_pipe(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect @Pipe decorated classes."""
        new_nodes: list[Node] = []

        for match in _PIPE_RE.finditer(source_text):
            line_no = _line_of(source_text, match.start())
            block = _extract_decorator_block(source_text, match.start())

            pipe_name = ""
            name_m = _PIPE_NAME_RE.search(block)
            if name_m:
                pipe_name = name_m.group("name")

            class_node = self._find_enclosing_class(line_no, nodes)
            class_name = class_node.name if class_node else None

            if not class_name:
                after_decorator = source_text[match.start() :]
                cls_m = _CLASS_DECL_RE.search(after_decorator)
                if cls_m:
                    class_name = cls_m.group("name")
                    line_no = _line_of(source_text, match.start() + cls_m.start())

            if not class_name:
                continue

            pipe_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.FUNCTION, class_name),
                kind=NodeKind.FUNCTION,
                name=class_name,
                qualified_name=class_name,
                file_path=file_path,
                start_line=line_no,
                end_line=class_node.end_line if class_node else line_no + 10,
                language="typescript",
                metadata={
                    "framework": "angular",
                    "angular_type": "pipe",
                    "pipe_name": pipe_name,
                    "original_node_id": class_node.id if class_node else None,
                },
            )
            new_nodes.append(pipe_node)

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="pipes",
            nodes=new_nodes,
            edges=[],
            metadata={"pipe_count": len(new_nodes)},
        )

    # =================================================================
    # Private helpers -- routing
    # =================================================================

    def _detect_routes(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Angular route definitions."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        # Check if this file contains route definitions
        if not _ROUTES_ARRAY_RE.search(source_text) and "RouterModule" not in source_text:
            return None

        # Find all route path definitions
        for path_match in _ROUTE_PATH_RE.finditer(source_text):
            route_path = path_match.group("path")
            line_no = _line_of(source_text, path_match.start())

            # Look for component reference near this route
            # Search in a window around the path definition
            window_start = max(0, path_match.start() - 50)
            window_end = min(len(source_text), path_match.end() + 300)
            window = source_text[window_start:window_end]

            route_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.ROUTE, route_path or "/"),
                kind=NodeKind.ROUTE,
                name=route_path or "/",
                qualified_name=f"route:{route_path}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no + 5,
                language="typescript",
                metadata={
                    "framework": "angular",
                    "angular_type": "route",
                    "path": route_path,
                },
            )
            new_nodes.append(route_node)

            # Eager component reference
            comp_m = _ROUTE_COMPONENT_RE.search(window)
            if comp_m:
                comp_name = comp_m.group("comp")
                new_edges.append(
                    Edge(
                        source_id=route_node.id,
                        target_id=f"__unresolved__:component:{comp_name}",
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.92,
                        line_number=line_no,
                        metadata={
                            "framework": "angular",
                            "angular_edge_type": "angular_routes_to",
                            "component": comp_name,
                        },
                    )
                )

            # Lazy-loaded component
            lazy_m = _ROUTE_LAZY_RE.search(window)
            if lazy_m:
                module_path = lazy_m.group("module")
                new_edges.append(
                    Edge(
                        source_id=route_node.id,
                        target_id=f"__unresolved__:lazy:{module_path}",
                        kind=EdgeKind.DYNAMIC_IMPORTS,
                        confidence=0.88,
                        line_number=line_no,
                        metadata={
                            "framework": "angular",
                            "angular_edge_type": "angular_lazy_loads",
                            "module_path": module_path,
                            "lazy_type": "loadComponent",
                        },
                    )
                )

            # Lazy-loaded children
            lazy_children_m = _ROUTE_LAZY_CHILDREN_RE.search(window)
            if lazy_children_m:
                module_path = lazy_children_m.group("module")
                new_edges.append(
                    Edge(
                        source_id=route_node.id,
                        target_id=f"__unresolved__:lazy:{module_path}",
                        kind=EdgeKind.DYNAMIC_IMPORTS,
                        confidence=0.88,
                        line_number=line_no,
                        metadata={
                            "framework": "angular",
                            "angular_edge_type": "angular_lazy_loads",
                            "module_path": module_path,
                            "lazy_type": "loadChildren",
                        },
                    )
                )

            # Route guards
            guard_m = _ROUTE_GUARD_RE.search(window)
            if guard_m:
                guards = _extract_list_items(guard_m.group("guards"))
                for guard in guards:
                    new_edges.append(
                        Edge(
                            source_id=route_node.id,
                            target_id=f"__unresolved__:guard:{guard}",
                            kind=EdgeKind.DEPENDS_ON,
                            confidence=0.90,
                            line_number=line_no,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_guards",
                                "guard_name": guard,
                            },
                        )
                    )

            # --- Edge #1: angular_resolves ---
            resolve_m = _ROUTE_RESOLVE_RE.search(window)
            if resolve_m:
                obj_text = resolve_m.group("obj")
                arr_text = resolve_m.group("arr")
                if obj_text:
                    # Object form: resolve: { data: DataResolver, user: UserResolver }
                    # Extract values (the resolver names)
                    for pair in obj_text.split(","):
                        pair = pair.strip()
                        if ":" in pair:
                            resolver_name = pair.split(":", 1)[1].strip()
                            resolver_name = re.sub(r"[()\[\]{}]", "", resolver_name).strip()
                            if resolver_name and re.match(r"^[A-Za-z_]\w*$", resolver_name):
                                new_edges.append(
                                    Edge(
                                        source_id=route_node.id,
                                        target_id=f"__unresolved__:type:{resolver_name}",
                                        kind=EdgeKind.DEPENDS_ON,
                                        confidence=0.95,
                                        line_number=line_no,
                                        metadata={
                                            "framework": "angular",
                                            "angular_edge_type": "angular_resolves",
                                            "resolver_name": resolver_name,
                                        },
                                    )
                                )
                elif arr_text:
                    # Array form: resolve: [DataResolver]
                    for resolver_name in _extract_list_items(arr_text):
                        new_edges.append(
                            Edge(
                                source_id=route_node.id,
                                target_id=f"__unresolved__:type:{resolver_name}",
                                kind=EdgeKind.DEPENDS_ON,
                                confidence=0.95,
                                line_number=line_no,
                                metadata={
                                    "framework": "angular",
                                    "angular_edge_type": "angular_resolves",
                                    "resolver_name": resolver_name,
                                },
                            )
                        )

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="routes",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "route_count": len(new_nodes),
                "edge_count": len(new_edges),
            },
        )

    # =================================================================
    # Private helpers -- dependency injection
    # =================================================================

    def _detect_dependency_injection(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect constructor injection and inject() function calls."""
        new_edges: list[Edge] = []

        # Constructor injection
        # First find constructor blocks
        ctor_re = re.compile(r"constructor\s*\((?P<params>[^)]*?)\)", re.DOTALL)
        for ctor_match in ctor_re.finditer(source_text):
            ctor_line = _line_of(source_text, ctor_match.start())
            params_text = ctor_match.group("params")

            # Find the enclosing class
            class_node = self._find_enclosing_class(ctor_line, nodes)
            if not class_node:
                # Fallback: search backwards for class declaration
                before = source_text[: ctor_match.start()]
                cls_matches = list(_CLASS_DECL_RE.finditer(before))
                if not cls_matches:
                    continue
                last_cls = cls_matches[-1]
                source_class_name = last_cls.group("name")
                source_id = generate_node_id(
                    file_path,
                    _line_of(source_text, last_cls.start()),
                    NodeKind.CLASS,
                    source_class_name,
                )
            else:
                source_id = class_node.id

            # Extract each injected parameter
            for param_match in _CONSTRUCTOR_PARAMS_RE.finditer(params_text):
                param_name = param_match.group("param")
                type_name = param_match.group("type")
                new_edges.append(
                    Edge(
                        source_id=source_id,
                        target_id=f"__unresolved__:service:{type_name}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.90,
                        line_number=ctor_line,
                        metadata={
                            "framework": "angular",
                            "angular_edge_type": "angular_injects",
                            "param_name": param_name,
                            "service_type": type_name,
                            "injection_style": "constructor",
                        },
                    )
                )

        # inject() function calls (Angular 14+)
        for inject_match in _INJECT_FN_RE.finditer(source_text):
            inject_line = _line_of(source_text, inject_match.start())
            prop_name = inject_match.group("name")
            type_name = inject_match.group("type")

            class_node = self._find_enclosing_class(inject_line, nodes)
            if class_node:
                source_id = class_node.id
            else:
                before = source_text[: inject_match.start()]
                cls_matches = list(_CLASS_DECL_RE.finditer(before))
                if not cls_matches:
                    continue
                last_cls = cls_matches[-1]
                source_id = generate_node_id(
                    file_path,
                    _line_of(source_text, last_cls.start()),
                    NodeKind.CLASS,
                    last_cls.group("name"),
                )

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:service:{type_name}",
                    kind=EdgeKind.DEPENDS_ON,
                    line_number=inject_line,
                    metadata={
                        "framework": "angular",
                        "angular_edge_type": "angular_injects",
                        "param_name": prop_name,
                        "service_type": type_name,
                        "injection_style": "inject_function",
                    },
                )
            )

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="dependency_injection",
            nodes=[],
            edges=new_edges,
            metadata={"injection_count": len(new_edges)},
        )

    # =================================================================
    # Private helpers -- signals
    # =================================================================

    def _detect_signals(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Angular signals (signal, computed, effect)."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        # Collect signal names for dependency resolution
        signal_names: set[str] = set()

        # signal()
        for match in _SIGNAL_RE.finditer(source_text):
            name = match.group("name")
            line_no = _line_of(source_text, match.start())
            signal_names.add(name)
            new_nodes.append(
                Node(
                    id=generate_node_id(file_path, line_no, NodeKind.VARIABLE, name),
                    kind=NodeKind.VARIABLE,
                    name=name,
                    qualified_name=name,
                    file_path=file_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="typescript",
                    metadata={
                        "framework": "angular",
                        "angular_type": "signal",
                        "signal_kind": "writable",
                    },
                )
            )

        # computed()
        for match in _COMPUTED_SIGNAL_RE.finditer(source_text):
            name = match.group("name")
            line_no = _line_of(source_text, match.start())
            computed_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.VARIABLE, name),
                kind=NodeKind.VARIABLE,
                name=name,
                qualified_name=name,
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="typescript",
                metadata={
                    "framework": "angular",
                    "angular_type": "signal",
                    "signal_kind": "computed",
                },
            )
            new_nodes.append(computed_node)

            # --- Edge #8: angular_signal_depends ---
            # Extract the computed body and find signal getter calls
            body = _extract_computed_body(source_text, match.start())
            if body:
                seen_signals: set[str] = set()
                for call_match in _SIGNAL_CALL_RE.finditer(body):
                    sig_name = call_match.group("signal")
                    # Only create edges for known signal names or this.xxx() patterns
                    # Filter out common non-signal function calls
                    if sig_name in seen_signals:
                        continue
                    if sig_name in signal_names:
                        seen_signals.add(sig_name)
                        new_edges.append(
                            Edge(
                                source_id=computed_node.id,
                                target_id=f"__unresolved__:signal:{sig_name}",
                                kind=EdgeKind.DEPENDS_ON,
                                confidence=0.90,
                                line_number=line_no,
                                metadata={
                                    "framework": "angular",
                                    "angular_edge_type": "angular_signal_depends",
                                    "signal_name": sig_name,
                                },
                            )
                        )

        # effect() -- no named variable, just detect presence
        effect_count = len(list(_EFFECT_RE.finditer(source_text)))

        if not new_nodes and effect_count == 0:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="signals",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "signal_count": len(new_nodes),
                "effect_count": effect_count,
            },
        )

    # =================================================================
    # Private helpers -- RxJS patterns
    # =================================================================

    def _detect_rxjs_patterns(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect RxJS and HttpClient patterns."""
        new_edges: list[Edge] = []
        observable_count = len(list(_OBSERVABLE_RE.finditer(source_text)))
        subject_count = len(list(_SUBJECT_RE.finditer(source_text)))
        subscribe_count = len(list(_SUBSCRIBE_RE.finditer(source_text)))
        pipe_count = len(list(_PIPE_OPERATOR_RE.finditer(source_text)))

        # HTTP client calls -> API_CALLS edges
        for match in _HTTP_CLIENT_URL_RE.finditer(source_text):
            method = match.group("method")
            url = match.group("url")
            line_no = _line_of(source_text, match.start())

            # Find enclosing class
            class_node = self._find_enclosing_class(line_no, nodes)
            if class_node:
                source_id = class_node.id
            else:
                before = source_text[: match.start()]
                cls_matches = list(_CLASS_DECL_RE.finditer(before))
                if cls_matches:
                    last_cls = cls_matches[-1]
                    source_id = generate_node_id(
                        file_path,
                        _line_of(source_text, last_cls.start()),
                        NodeKind.CLASS,
                        last_cls.group("name"),
                    )
                else:
                    continue

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:api:{url}",
                    kind=EdgeKind.API_CALLS,
                    line_number=line_no,
                    metadata={
                        "framework": "angular",
                        "angular_edge_type": "angular_http_calls",
                        "http_method": method.upper(),
                        "url": url,
                    },
                )
            )

        # Also detect this.http.method() without URL extraction
        for match in _HTTP_CLIENT_RE.finditer(source_text):
            # Skip if already captured by URL regex
            method = match.group("method")
            line_no = _line_of(source_text, match.start())

            # Check if this position was already captured
            already_captured = False
            for edge in new_edges:
                if edge.line_number == line_no and edge.kind == EdgeKind.API_CALLS:
                    already_captured = True
                    break
            if already_captured:
                continue

            class_node = self._find_enclosing_class(line_no, nodes)
            if class_node:
                source_id = class_node.id
            else:
                before = source_text[: match.start()]
                cls_matches = list(_CLASS_DECL_RE.finditer(before))
                if cls_matches:
                    last_cls = cls_matches[-1]
                    source_id = generate_node_id(
                        file_path,
                        _line_of(source_text, last_cls.start()),
                        NodeKind.CLASS,
                        last_cls.group("name"),
                    )
                else:
                    continue

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:api:http_{method}",
                    kind=EdgeKind.API_CALLS,
                    line_number=line_no,
                    metadata={
                        "framework": "angular",
                        "angular_edge_type": "angular_http_calls",
                        "http_method": method.upper(),
                    },
                )
            )

        # --- Edge #7: angular_subscribes_to (.subscribe() calls) ---
        for match in _SUBSCRIBE_RE.finditer(source_text):
            line_no = _line_of(source_text, match.start())

            class_node = self._find_enclosing_class(line_no, nodes)
            if class_node:
                source_id = class_node.id
            else:
                before = source_text[: match.start()]
                cls_matches = list(_CLASS_DECL_RE.finditer(before))
                if cls_matches:
                    last_cls = cls_matches[-1]
                    source_id = generate_node_id(
                        file_path,
                        _line_of(source_text, last_cls.start()),
                        NodeKind.CLASS,
                        last_cls.group("name"),
                    )
                else:
                    continue

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:observable:subscribe_{line_no}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.85,
                    line_number=line_no,
                    metadata={
                        "framework": "angular",
                        "angular_edge_type": "angular_subscribes_to",
                        "subscribe_type": "explicit",
                    },
                )
            )

        has_rxjs = observable_count > 0 or subject_count > 0 or subscribe_count > 0 or pipe_count > 0

        if not new_edges and not has_rxjs:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="rxjs",
            nodes=[],
            edges=new_edges,
            metadata={
                "observable_count": observable_count,
                "subject_count": subject_count,
                "subscribe_count": subscribe_count,
                "pipe_count": pipe_count,
                "http_call_count": len([e for e in new_edges if e.metadata.get("angular_edge_type") == "angular_http_calls"]),
            },
        )

    # =================================================================
    # Private helpers -- cross-file patterns
    # =================================================================

    def _connect_cross_file_di(self, store: Any) -> FrameworkPattern | None:
        """Connect DI edges to actual service definitions across files."""
        new_edges: list[Edge] = []

        # Find all PROVIDER nodes (services)
        try:
            service_nodes = store.find_nodes(kind=NodeKind.PROVIDER, limit=500)
        except Exception:
            return None

        if not service_nodes:
            return None

        service_map: dict[str, str] = {s.name: s.id for s in service_nodes}

        # Find all COMPONENT nodes
        try:
            component_nodes = store.find_nodes(kind=NodeKind.COMPONENT, limit=500)
        except Exception:
            component_nodes = []

        all_nodes = list(service_nodes) + list(component_nodes)

        for node in all_nodes:
            try:
                node_edges = store.get_edges(
                    source_id=node.id,
                    kind=EdgeKind.DEPENDS_ON,
                )
            except Exception:
                continue

            for edge in node_edges:
                if not edge.target_id.startswith("__unresolved__:service:"):
                    continue

                service_name = edge.target_id.split(":")[-1]
                if service_name in service_map:
                    new_edges.append(
                        Edge(
                            source_id=edge.source_id,
                            target_id=service_map[service_name],
                            kind=EdgeKind.DEPENDS_ON,
                            confidence=0.95,
                            line_number=edge.line_number,
                            metadata={
                                "framework": "angular",
                                "angular_edge_type": "angular_injects",
                                "resolved": True,
                                "service_name": service_name,
                                **(edge.metadata or {}),
                            },
                        )
                    )

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="angular",
            pattern_type="cross_file_di",
            nodes=[],
            edges=new_edges,
            metadata={"resolved_injection_count": len(new_edges)},
        )

    # =================================================================
    # Utility helpers
    # =================================================================

    @staticmethod
    def _find_enclosing_class(line_no: int, nodes: list[Node]) -> Node | None:
        """Find the CLASS node that encloses a given line number."""
        candidates = [
            n
            for n in nodes
            if n.kind == NodeKind.CLASS
            and n.start_line is not None
            and n.end_line is not None
            and n.start_line <= line_no <= n.end_line
        ]
        if not candidates:
            return None
        # Return the most specific (smallest range) enclosing class
        return min(
            candidates,
            key=lambda n: (n.end_line or 0) - (n.start_line or 0),
        )
