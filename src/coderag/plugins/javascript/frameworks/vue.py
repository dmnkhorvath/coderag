"""Vue.js framework detector for CodeRAG.

Detects Vue-specific patterns including Single File Components,
Composition API, Options API, state management (Vuex/Pinia),
Vue Router, provide/inject, composables, and template analysis
from already-parsed AST nodes and source code.
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

# ── SFC block detection ───────────────────────────────────────
_TEMPLATE_BLOCK_RE = re.compile(
    r"<template(?P<attrs>[^>]*)>(?P<content>.*?)</template>",
    re.DOTALL,
)
_SCRIPT_BLOCK_RE = re.compile(
    r"<script(?P<attrs>[^>]*)>(?P<content>.*?)</script>",
    re.DOTALL,
)
_STYLE_BLOCK_RE = re.compile(
    r"<style(?P<attrs>[^>]*)>(?P<content>.*?)</style>",
    re.DOTALL,
)
_SETUP_ATTR_RE = re.compile(r"\bsetup\b")
_LANG_ATTR_RE = re.compile(r"""\blang\s*=\s*['"](?P<lang>[^'"]*)['"]""")

# ── Composition API patterns ──────────────────────────────────
_DEFINE_COMPONENT_RE = re.compile(r"\bdefineComponent\s*\(")
_DEFINE_PROPS_RE = re.compile(r"\bdefineProps\s*[<(]")
_DEFINE_EMITS_RE = re.compile(r"\bdefineEmits\s*[<(]")
_DEFINE_EXPOSE_RE = re.compile(r"\bdefineExpose\s*\(")
_DEFINE_SLOTS_RE = re.compile(r"\bdefineSlots\s*[<(]")
_DEFINE_MODEL_RE = re.compile(r"\bdefineModel\s*[<(]")

# Composition API reactivity
_REF_RE = re.compile(r"\bref\s*[<(]")
_REACTIVE_RE = re.compile(r"\breactive\s*[<(]")
_COMPUTED_RE = re.compile(r"\bcomputed\s*[<(]")
_WATCH_RE = re.compile(r"\bwatch\s*\(")
_WATCH_EFFECT_RE = re.compile(r"\bwatchEffect\s*\(")

# Composition API lifecycle hooks
_LIFECYCLE_HOOKS_RE = re.compile(
    r"\b(?P<hook>onMounted|onUnmounted|onBeforeMount|onBeforeUnmount"
    r"|onUpdated|onBeforeUpdate|onActivated|onDeactivated"
    r"|onErrorCaptured|onRenderTracked|onRenderTriggered"
    r"|onServerPrefetch)\s*\(",
)

# ── Options API patterns ──────────────────────────────────────
_OPTIONS_DATA_RE = re.compile(r"\bdata\s*\(\s*\)\s*\{")
_OPTIONS_METHODS_RE = re.compile(r"\bmethods\s*:\s*\{")
_OPTIONS_COMPUTED_RE = re.compile(r"\bcomputed\s*:\s*\{")
_OPTIONS_WATCH_RE = re.compile(r"\bwatch\s*:\s*\{")
_OPTIONS_LIFECYCLE_RE = re.compile(
    r"\b(?P<hook>mounted|unmounted|beforeMount|beforeUnmount"
    r"|updated|beforeUpdate|created|beforeCreate"
    r"|activated|deactivated|errorCaptured)\s*\(\s*\)",
)

# ── State management patterns ─────────────────────────────────
_VUEX_STORE_RE = re.compile(r"\b(?:createStore|useStore|mapState|mapGetters|mapActions|mapMutations)\s*\(")
_PINIA_STORE_RE = re.compile(r"\b(?:defineStore|useStore|storeToRefs)\s*\(")
_USE_STORE_RE = re.compile(r"\buse(?P<name>[A-Z][a-zA-Z0-9]*)Store\s*\(")

# ── Component registration ────────────────────────────────────
_COMPONENTS_OPTION_RE = re.compile(r"\bcomponents\s*:\s*\{")

# ── Vue Router patterns ──────────────────────────────────────
_CREATE_ROUTER_RE = re.compile(r"\bcreateRouter\s*\(")
_USE_ROUTE_RE = re.compile(r"\b(?P<fn>useRoute|useRouter)\s*\(")
_ROUTE_DEF_RE = re.compile(r"""path\s*:\s*['"](?P<path>[^'"]+)['"]""")
_ROUTE_COMPONENT_RE = re.compile(r"""component\s*:\s*(?P<comp>[A-Z]\w+)""")
_ROUTE_LAZY_RE = re.compile(r"""component\s*:\s*\(\)\s*=>\s*import\s*\(['"](?P<module>[^'"]+)['"]\)""")
_NAV_GUARD_RE = re.compile(r"\b(?:router\.)?(?P<guard>beforeEach|beforeEnter|afterEach|beforeResolve)\s*\(")
_ROUTER_LINK_RE = re.compile(r'<router-link[^>]*\bto=["\'](?P<to>[^"\']*)["\'\']')

# ── Provide/Inject patterns ──────────────────────────────────
_PROVIDE_RE = re.compile(r"""\bprovide\s*\(\s*(?:['"](?P<str_key>[^'"]+)['"]|(?P<sym_key>[A-Za-z_]\w*))""")
_INJECT_RE = re.compile(r"""\binject\s*\(\s*(?:['"](?P<str_key>[^'"]+)['"]|(?P<sym_key>[A-Za-z_]\w*))""")
_INJECTION_KEY_RE = re.compile(r"\b(?P<name>\w+)\s*(?::\s*InjectionKey|=\s*Symbol\s*\()")

# ── Composables patterns ─────────────────────────────────────
_COMPOSABLE_DEF_RE = re.compile(r"(?:function\s+|(?:const|let)\s+)(?P<name>use[A-Z]\w*)\s*(?:=|\()")
_COMPOSABLE_USE_RE = re.compile(r"\b(?P<name>use[A-Z]\w*)\s*\(")

# ── Template analysis patterns ────────────────────────────────
_TEMPLATE_COMPONENT_RE = re.compile(r"<(?P<comp>[A-Z][A-Za-z0-9]*)[\s/>]")
_TEMPLATE_KEBAB_COMP_RE = re.compile(r"<(?P<comp>[a-z][a-z0-9]*(?:-[a-z0-9]+)+)[\s/>]")
_V_MODEL_RE = re.compile(r"\bv-model(?::(?P<arg>\w+))?=")
_SLOT_DEF_RE = re.compile(r'<slot(?:\s+name=["\'](?P<name>[^"\']*)["\'\'])?')
_SLOT_USE_RE = re.compile(r"<template\s+(?:#|v-slot:)(?P<name>\w+)")
_EVENT_LISTENER_RE = re.compile(r"(?:@|v-on:)(?P<event>[\w.-]+)=")
_DYNAMIC_COMPONENT_RE = re.compile(r"<component\s+:is=")

# Known Vue built-in composables to exclude from custom composable detection
_VUE_BUILTIN_COMPOSABLES = frozenset(
    {
        "useRoute",
        "useRouter",
        "useStore",
        "useSlots",
        "useAttrs",
    }
)

# Known HTML elements to exclude from template component detection
_HTML_ELEMENTS = frozenset(
    {
        "div",
        "span",
        "p",
        "a",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "tr",
        "td",
        "th",
        "thead",
        "tbody",
        "tfoot",
        "form",
        "input",
        "button",
        "select",
        "option",
        "textarea",
        "label",
        "img",
        "video",
        "audio",
        "canvas",
        "svg",
        "path",
        "circle",
        "rect",
        "line",
        "header",
        "footer",
        "nav",
        "main",
        "section",
        "article",
        "aside",
        "pre",
        "code",
        "blockquote",
        "em",
        "strong",
        "i",
        "b",
        "u",
        "br",
        "hr",
        "meta",
        "link",
        "script",
        "style",
        "title",
        "head",
        "body",
        "html",
        "iframe",
        "embed",
        "object",
        "param",
        "source",
        "track",
        "details",
        "summary",
        "dialog",
        "menu",
        "menuitem",
        "fieldset",
        "legend",
        "datalist",
        "output",
        "progress",
        "meter",
        "figure",
        "figcaption",
        "picture",
        "map",
        "area",
        "col",
        "colgroup",
        "caption",
        "slot",
        "template",
    }
)

# Vue built-in components to exclude from template component detection
_VUE_BUILTIN_COMPONENTS = frozenset(
    {
        "Transition",
        "TransitionGroup",
        "KeepAlive",
        "Suspense",
        "Teleport",
        "Component",
        "Slot",
        "RouterLink",
        "RouterView",
    }
)


class VueDetector(FrameworkDetector):
    """Detect Vue.js framework patterns in JavaScript/TypeScript projects."""

    @property
    def framework_name(self) -> str:
        return "vue"

    def detect_framework(self, project_root: str) -> bool:
        """Check package.json for vue/nuxt dependency.

        Scans the root package.json first, then checks monorepo
        subdirectories (up to 2 levels deep) for vue or nuxt.
        Also detects .vue files as a strong signal.
        """
        vue_indicators = {"vue", "nuxt", "nuxt3", "@nuxt/kit"}

        def _check_pkg(pkg_path: str) -> bool:
            if not os.path.isfile(pkg_path):
                return False
            try:
                with open(pkg_path, encoding="utf-8") as f:
                    data = json.load(f)
                deps = set(data.get("dependencies", {}).keys())
                dev_deps = set(data.get("devDependencies", {}).keys())
                all_deps = deps | dev_deps
                return bool(all_deps & vue_indicators)
            except (json.JSONDecodeError, OSError):
                return False

        # Check root package.json
        if _check_pkg(os.path.join(project_root, "package.json")):
            return True

        # Check monorepo subdirectories (packages/*, apps/*, src/*)
        for subdir in ("packages", "apps", "src", "frontend", "client"):
            subdir_path = os.path.join(project_root, subdir)
            if os.path.isdir(subdir_path):
                try:
                    for entry in os.listdir(subdir_path):
                        pkg = os.path.join(subdir_path, entry, "package.json")
                        if _check_pkg(pkg):
                            return True
                except OSError:
                    continue

        # Fallback: check for .vue files
        for dirpath, _dirs, files in os.walk(project_root):
            if any(f.endswith(".vue") for f in files):
                return True
            # Don't recurse too deep
            depth = dirpath.replace(project_root, "").count(os.sep)
            if depth >= 3:
                _dirs.clear()

        return False

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect per-file Vue patterns from source code.

        Identifies:
        - Single File Components (.vue files)
        - Composition API usage (defineComponent, defineProps, ref, etc.)
        - Options API usage (data, methods, computed, watch, lifecycle)
        - Vuex/Pinia store usage
        - Vue Router patterns
        - Provide/Inject patterns
        - Custom composables
        - Template component usage
        """
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        is_vue_file = file_path.endswith(".vue")

        # ── SFC detection ─────────────────────────────────────
        if is_vue_file:
            sfc_pattern = self._detect_sfc(
                file_path,
                source_text,
                nodes,
            )
            if sfc_pattern:
                patterns.append(sfc_pattern)

        # ── Composition API detection ─────────────────────────
        composition_pattern = self._detect_composition_api(
            file_path,
            nodes,
            source_text,
        )
        if composition_pattern:
            patterns.append(composition_pattern)

        # ── Options API detection ─────────────────────────────
        options_pattern = self._detect_options_api(
            file_path,
            nodes,
            source_text,
        )
        if options_pattern:
            patterns.append(options_pattern)

        # ── Store detection ───────────────────────────────────
        store_pattern = self._detect_stores(
            file_path,
            nodes,
            source_text,
        )
        if store_pattern:
            patterns.append(store_pattern)

        # ── Router detection ──────────────────────────────────
        router_pattern = self._detect_router(file_path, nodes, source_text)
        if router_pattern:
            patterns.append(router_pattern)

        # ── Provide/Inject detection ──────────────────────────
        pi_pattern = self._detect_provide_inject(file_path, nodes, source_text)
        if pi_pattern:
            patterns.append(pi_pattern)

        # ── Composables detection ─────────────────────────────
        composable_pattern = self._detect_composables(file_path, nodes, source_text)
        if composable_pattern:
            patterns.append(composable_pattern)

        # ── Template patterns (Vue files only) ────────────────
        if is_vue_file:
            template_pattern = self._detect_template_patterns(
                file_path,
                source_text,
                nodes,
            )
            if template_pattern:
                patterns.append(template_pattern)

        return patterns

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Vue patterns.

        Currently returns empty — Vue patterns are primarily per-file.
        Future: could detect component registration trees, store module composition.
        """
        return []

    # ── Private helpers ───────────────────────────────────────

    def _detect_sfc(
        self,
        file_path: str,
        source_text: str,
        nodes: list[Node],
    ) -> FrameworkPattern | None:
        """Detect Vue Single File Component structure.

        Identifies <template>, <script>, and <style> blocks,
        and creates a COMPONENT node for the SFC.
        """
        has_template = bool(_TEMPLATE_BLOCK_RE.search(source_text))
        has_script = bool(_SCRIPT_BLOCK_RE.search(source_text))
        has_style = bool(_STYLE_BLOCK_RE.search(source_text))

        if not has_template and not has_script:
            return None

        # Determine script setup and language
        script_match = _SCRIPT_BLOCK_RE.search(source_text)
        is_setup = False
        script_lang = "javascript"
        if script_match:
            attrs = script_match.group("attrs")
            is_setup = bool(_SETUP_ATTR_RE.search(attrs))
            lang_match = _LANG_ATTR_RE.search(attrs)
            if lang_match:
                lang = lang_match.group("lang")
                if lang in ("ts", "typescript"):
                    script_lang = "typescript"

        # Derive component name from file path
        component_name = self._component_name_from_path(file_path)

        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        component_node = Node(
            id=generate_node_id(file_path, 1, NodeKind.COMPONENT, component_name),
            kind=NodeKind.COMPONENT,
            name=component_name,
            qualified_name=component_name,
            file_path=file_path,
            start_line=1,
            end_line=source_text.count("\n") + 1,
            language=script_lang,
            metadata={
                "framework": "vue",
                "component_type": "sfc",
                "has_template": has_template,
                "has_script": has_script,
                "has_style": has_style,
                "script_setup": is_setup,
                "script_lang": script_lang,
            },
        )
        new_nodes.append(component_node)

        # Link to any function/class nodes in the file
        for n in nodes:
            if n.kind in (NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.VARIABLE):
                new_edges.append(
                    Edge(
                        source_id=component_node.id,
                        target_id=n.id,
                        kind=EdgeKind.CONTAINS,
                        confidence=0.90,
                        metadata={"framework": "vue"},
                    )
                )

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="sfc",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "component_name": component_name,
                "has_template": has_template,
                "has_script": has_script,
                "has_style": has_style,
                "script_setup": is_setup,
            },
        )

    def _detect_composition_api(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Vue Composition API patterns.

        Identifies defineComponent, defineProps, defineEmits, defineExpose,
        ref, reactive, computed, watch, and lifecycle hooks.
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        api_usages: list[str] = []

        # Check for defineComponent
        if _DEFINE_COMPONENT_RE.search(source_text):
            api_usages.append("defineComponent")

        # Check for script setup macros
        for name, regex in [
            ("defineProps", _DEFINE_PROPS_RE),
            ("defineEmits", _DEFINE_EMITS_RE),
            ("defineExpose", _DEFINE_EXPOSE_RE),
            ("defineSlots", _DEFINE_SLOTS_RE),
            ("defineModel", _DEFINE_MODEL_RE),
        ]:
            if regex.search(source_text):
                api_usages.append(name)

        # Check for reactivity primitives
        for name, regex in [
            ("ref", _REF_RE),
            ("reactive", _REACTIVE_RE),
            ("computed", _COMPUTED_RE),
            ("watch", _WATCH_RE),
            ("watchEffect", _WATCH_EFFECT_RE),
        ]:
            if regex.search(source_text):
                api_usages.append(name)

        # Check for lifecycle hooks
        for match in _LIFECYCLE_HOOKS_RE.finditer(source_text):
            hook_name = match.group("hook")
            if hook_name not in api_usages:
                api_usages.append(hook_name)

            line_no = source_text[: match.start()].count("\n") + 1
            hook_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.HOOK, hook_name),
                kind=NodeKind.HOOK,
                name=hook_name,
                qualified_name=f"vue:{hook_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "hook_type": "lifecycle",
                    "api_style": "composition",
                },
            )
            new_nodes.append(hook_node)

            # Link hook to enclosing function
            enclosing = self._find_enclosing_function(line_no, nodes)
            if enclosing:
                new_edges.append(
                    Edge(
                        source_id=enclosing.id,
                        target_id=hook_node.id,
                        kind=EdgeKind.USES_HOOK,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={"framework": "vue", "hook_name": hook_name},
                    )
                )

        if not api_usages:
            return None

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="composition_api",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "api_usages": api_usages,
                "usage_count": len(api_usages),
            },
        )

    def _detect_options_api(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Vue Options API patterns.

        Identifies data(), methods, computed, watch, and lifecycle hooks.
        """
        options_found: list[str] = []
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        for name, regex in [
            ("data", _OPTIONS_DATA_RE),
            ("methods", _OPTIONS_METHODS_RE),
            ("computed", _OPTIONS_COMPUTED_RE),
            ("watch", _OPTIONS_WATCH_RE),
        ]:
            if regex.search(source_text):
                options_found.append(name)

        # Check for Options API lifecycle hooks
        for match in _OPTIONS_LIFECYCLE_RE.finditer(source_text):
            hook_name = match.group("hook")
            if hook_name not in options_found:
                options_found.append(hook_name)

            line_no = source_text[: match.start()].count("\n") + 1
            hook_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.HOOK, hook_name),
                kind=NodeKind.HOOK,
                name=hook_name,
                qualified_name=f"vue:options:{hook_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "hook_type": "lifecycle",
                    "api_style": "options",
                },
            )
            new_nodes.append(hook_node)

        if not options_found:
            return None

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="options_api",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "options_found": options_found,
                "option_count": len(options_found),
            },
        )

    def _detect_stores(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Vuex and Pinia store usage."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        store_usages: list[dict[str, str]] = []

        # Detect Pinia defineStore
        define_store_re = re.compile(r"""\bdefineStore\s*\(\s*['"](?P<name>[^'"]*)['"]""")
        for match in define_store_re.finditer(source_text):
            store_name = match.group("name")
            line_no = source_text[: match.start()].count("\n") + 1
            store_usages.append({"type": "pinia", "name": store_name, "action": "define"})

            store_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MODULE, f"store:{store_name}"),
                kind=NodeKind.MODULE,
                name=store_name,
                qualified_name=f"pinia:store:{store_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "store_type": "pinia",
                    "store_name": store_name,
                },
            )
            new_nodes.append(store_node)

        # Detect useXxxStore() calls (Pinia convention)
        for match in _USE_STORE_RE.finditer(source_text):
            store_name = match.group("name")
            line_no = source_text[: match.start()].count("\n") + 1
            store_usages.append({"type": "pinia", "name": store_name, "action": "use"})

            # Link to enclosing function
            enclosing = self._find_enclosing_function(line_no, nodes)
            if enclosing:
                new_edges.append(
                    Edge(
                        source_id=enclosing.id,
                        target_id=f"__unresolved__:store:{store_name}",
                        kind=EdgeKind.CALLS,
                        confidence=0.80,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "store_type": "pinia",
                            "store_name": store_name,
                        },
                    )
                )

        # Detect Vuex patterns
        if _VUEX_STORE_RE.search(source_text):
            store_usages.append({"type": "vuex", "name": "vuex", "action": "use"})

        if not store_usages:
            return None

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="stores",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "store_usages": store_usages,
                "store_count": len(store_usages),
            },
        )

    def _detect_router(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Vue Router patterns.

        Identifies createRouter(), useRoute/useRouter(), route definitions,
        navigation guards, and <router-link> usage in templates.
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        router_usages: list[dict[str, Any]] = []

        # Detect createRouter()
        for match in _CREATE_ROUTER_RE.finditer(source_text):
            line_no = source_text[: match.start()].count("\n") + 1
            router_usages.append({"type": "createRouter", "line": line_no})

        # Detect useRoute() / useRouter()
        for match in _USE_ROUTE_RE.finditer(source_text):
            fn_name = match.group("fn")
            line_no = source_text[: match.start()].count("\n") + 1
            router_usages.append({"type": fn_name, "line": line_no})

        # Detect route definitions: path: '/xxx'
        route_paths: list[dict[str, Any]] = []
        for match in _ROUTE_DEF_RE.finditer(source_text):
            route_path = match.group("path")
            line_no = source_text[: match.start()].count("\n") + 1

            route_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.ROUTE, route_path),
                kind=NodeKind.ROUTE,
                name=route_path,
                qualified_name=f"vue:route:{route_path}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "route_path": route_path,
                },
            )
            new_nodes.append(route_node)
            route_paths.append({"path": route_path, "line": line_no, "node_id": route_node.id})

        # Detect route component assignments (static)
        for match in _ROUTE_COMPONENT_RE.finditer(source_text):
            comp_name = match.group("comp")
            line_no = source_text[: match.start()].count("\n") + 1

            # Find the closest route path defined before this component assignment
            closest_route = None
            for rp in route_paths:
                if rp["line"] <= line_no:
                    closest_route = rp

            if closest_route:
                new_edges.append(
                    Edge(
                        source_id=closest_route["node_id"],
                        target_id=f"__unresolved__:component:{comp_name}",
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_routes_to",
                            "component_name": comp_name,
                        },
                    )
                )

        # Detect lazy-loaded route components
        for match in _ROUTE_LAZY_RE.finditer(source_text):
            module_path = match.group("module")
            line_no = source_text[: match.start()].count("\n") + 1

            closest_route = None
            for rp in route_paths:
                if rp["line"] <= line_no:
                    closest_route = rp

            if closest_route:
                new_edges.append(
                    Edge(
                        source_id=closest_route["node_id"],
                        target_id=f"__unresolved__:module:{module_path}",
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_routes_to",
                            "lazy_import": True,
                            "module_path": module_path,
                        },
                    )
                )

        # Detect navigation guards
        for match in _NAV_GUARD_RE.finditer(source_text):
            guard_name = match.group("guard")
            line_no = source_text[: match.start()].count("\n") + 1
            router_usages.append({"type": "nav_guard", "guard": guard_name, "line": line_no})

        # Detect <router-link> in templates
        for match in _ROUTER_LINK_RE.finditer(source_text):
            link_to = match.group("to")
            line_no = source_text[: match.start()].count("\n") + 1
            router_usages.append({"type": "router_link", "to": link_to, "line": line_no})

        if not router_usages and not route_paths:
            return None

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="router",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "router_usages": router_usages,
                "route_count": len(route_paths),
                "has_create_router": any(u["type"] == "createRouter" for u in router_usages),
                "has_nav_guards": any(u["type"] == "nav_guard" for u in router_usages),
            },
        )

    def _detect_provide_inject(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Vue provide/inject patterns.

        Identifies provide() calls, inject() calls, and InjectionKey declarations.
        Creates PROVIDER nodes and PROVIDES_CONTEXT / CONSUMES_CONTEXT edges.
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        pi_usages: list[dict[str, Any]] = []

        # Detect InjectionKey declarations
        injection_keys: dict[str, int] = {}
        for match in _INJECTION_KEY_RE.finditer(source_text):
            key_name = match.group("name")
            line_no = source_text[: match.start()].count("\n") + 1
            injection_keys[key_name] = line_no
            pi_usages.append({"type": "injection_key", "name": key_name, "line": line_no})

        # Detect provide() calls
        for match in _PROVIDE_RE.finditer(source_text):
            str_key = match.group("str_key")
            sym_key = match.group("sym_key")
            key = str_key or sym_key or "unknown"
            line_no = source_text[: match.start()].count("\n") + 1

            provider_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.PROVIDER, f"provide:{key}"),
                kind=NodeKind.PROVIDER,
                name=f"provide:{key}",
                qualified_name=f"vue:provide:{key}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "provide_key": key,
                    "key_type": "string" if str_key else "symbol",
                },
            )
            new_nodes.append(provider_node)
            pi_usages.append({"type": "provide", "key": key, "line": line_no})

            # Link provider to enclosing function
            enclosing = self._find_enclosing_function(line_no, nodes)
            if enclosing:
                new_edges.append(
                    Edge(
                        source_id=enclosing.id,
                        target_id=provider_node.id,
                        kind=EdgeKind.PROVIDES_CONTEXT,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_provides_context",
                            "provide_key": key,
                        },
                    )
                )

        # Detect inject() calls
        for match in _INJECT_RE.finditer(source_text):
            str_key = match.group("str_key")
            sym_key = match.group("sym_key")
            key = str_key or sym_key or "unknown"
            line_no = source_text[: match.start()].count("\n") + 1

            pi_usages.append({"type": "inject", "key": key, "line": line_no})

            # Link inject to enclosing function
            enclosing = self._find_enclosing_function(line_no, nodes)
            if enclosing:
                new_edges.append(
                    Edge(
                        source_id=enclosing.id,
                        target_id=f"__unresolved__:provide:{key}",
                        kind=EdgeKind.CONSUMES_CONTEXT,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_consumes_context",
                            "inject_key": key,
                        },
                    )
                )

        if not pi_usages:
            return None

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="provide_inject",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "provide_inject_usages": pi_usages,
                "provide_count": sum(1 for u in pi_usages if u["type"] == "provide"),
                "inject_count": sum(1 for u in pi_usages if u["type"] == "inject"),
                "injection_key_count": len(injection_keys),
            },
        )

    def _detect_composables(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect custom Vue composable functions.

        Identifies composable definitions (function useXxx / const useXxx)
        and composable usage (useXxx() calls), excluding Vue built-ins
        and store calls.
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        composable_defs: list[str] = []
        composable_calls: list[str] = []

        # Detect composable definitions
        for match in _COMPOSABLE_DEF_RE.finditer(source_text):
            name = match.group("name")
            line_no = source_text[: match.start()].count("\n") + 1

            composable_defs.append(name)

            fn_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.FUNCTION, name),
                kind=NodeKind.FUNCTION,
                name=name,
                qualified_name=f"vue:composable:{name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "composable": True,
                    "composable_name": name,
                },
            )
            new_nodes.append(fn_node)

        # Detect composable usage (calls)
        for match in _COMPOSABLE_USE_RE.finditer(source_text):
            name = match.group("name")

            # Skip Vue built-in composables
            if name in _VUE_BUILTIN_COMPOSABLES:
                continue

            # Skip useXxxStore patterns (handled by store detection)
            if name.endswith("Store"):
                continue

            line_no = source_text[: match.start()].count("\n") + 1

            # Skip if this is actually a definition (already captured above)
            is_def = False
            for d_match in _COMPOSABLE_DEF_RE.finditer(source_text):
                if d_match.start() == match.start() or (
                    d_match.group("name") == name
                    and abs(source_text[: d_match.start()].count("\n") - source_text[: match.start()].count("\n")) == 0
                ):
                    is_def = True
                    break

            if is_def:
                continue

            if name not in composable_calls:
                composable_calls.append(name)

            # Link call to enclosing function
            enclosing = self._find_enclosing_function(line_no, nodes)
            if enclosing:
                new_edges.append(
                    Edge(
                        source_id=enclosing.id,
                        target_id=f"__unresolved__:composable:{name}",
                        kind=EdgeKind.CALLS,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "composable_name": name,
                        },
                    )
                )

        if not composable_defs and not composable_calls:
            return None

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="composables",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "composable_definitions": composable_defs,
                "composable_calls": composable_calls,
                "definition_count": len(composable_defs),
                "call_count": len(composable_calls),
            },
        )

    def _detect_template_patterns(
        self,
        file_path: str,
        source_text: str,
        nodes: list[Node],
    ) -> FrameworkPattern | None:
        """Detect patterns in Vue template blocks.

        Analyzes <template> content for component usage, v-model directives,
        slot definitions/usage, event listeners, and dynamic components.
        """
        # Extract template content
        template_match = _TEMPLATE_BLOCK_RE.search(source_text)
        if not template_match:
            return None

        template_content = template_match.group("content")
        template_start_line = source_text[: template_match.start()].count("\n") + 1

        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        template_info: dict[str, Any] = {}

        # Detect PascalCase component usage
        components_used: list[str] = []
        for match in _TEMPLATE_COMPONENT_RE.finditer(template_content):
            comp_name = match.group("comp")
            if comp_name not in _VUE_BUILTIN_COMPONENTS and comp_name not in components_used:
                components_used.append(comp_name)
                line_no = template_start_line + template_content[: match.start()].count("\n")

                # Create RENDERS edge from this file's component to the used component
                new_edges.append(
                    Edge(
                        source_id=generate_node_id(
                            file_path, 1, NodeKind.COMPONENT, self._component_name_from_path(file_path)
                        ),
                        target_id=f"__unresolved__:component:{comp_name}",
                        kind=EdgeKind.RENDERS,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_renders",
                            "component_name": comp_name,
                        },
                    )
                )

        # Detect kebab-case component usage
        kebab_components: list[str] = []
        for match in _TEMPLATE_KEBAB_COMP_RE.finditer(template_content):
            comp_name = match.group("comp")
            if comp_name not in _HTML_ELEMENTS and comp_name not in kebab_components:
                kebab_components.append(comp_name)
                line_no = template_start_line + template_content[: match.start()].count("\n")

                # Convert kebab-case to PascalCase for the edge target
                pascal_name = self._kebab_to_pascal(comp_name)
                new_edges.append(
                    Edge(
                        source_id=generate_node_id(
                            file_path, 1, NodeKind.COMPONENT, self._component_name_from_path(file_path)
                        ),
                        target_id=f"__unresolved__:component:{pascal_name}",
                        kind=EdgeKind.RENDERS,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_renders",
                            "component_name": pascal_name,
                            "original_tag": comp_name,
                        },
                    )
                )

        template_info["components_used"] = components_used
        template_info["kebab_components"] = kebab_components

        # Detect v-model directives
        v_models: list[str] = []
        for match in _V_MODEL_RE.finditer(template_content):
            arg = match.group("arg")
            v_models.append(arg if arg else "modelValue")
        template_info["v_models"] = v_models

        # Detect slot definitions
        slot_defs: list[str] = []
        for match in _SLOT_DEF_RE.finditer(template_content):
            slot_name = match.group("name")
            slot_defs.append(slot_name if slot_name else "default")
        template_info["slot_definitions"] = slot_defs

        # Detect slot usage
        slot_uses: list[str] = []
        for match in _SLOT_USE_RE.finditer(template_content):
            slot_uses.append(match.group("name"))
        template_info["slot_usages"] = slot_uses

        # Detect event listeners
        events: list[str] = []
        for match in _EVENT_LISTENER_RE.finditer(template_content):
            event_name = match.group("event")
            if event_name not in events:
                events.append(event_name)
        template_info["event_listeners"] = events

        # Detect dynamic components
        dynamic_count = len(_DYNAMIC_COMPONENT_RE.findall(template_content))
        template_info["dynamic_components"] = dynamic_count

        # Only return pattern if we found something interesting
        has_content = (
            components_used or kebab_components or v_models or slot_defs or slot_uses or events or dynamic_count > 0
        )

        if not has_content:
            return None

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="template_patterns",
            nodes=new_nodes,
            edges=new_edges,
            metadata=template_info,
        )

    # ── Utility helpers ───────────────────────────────────────

    @staticmethod
    def _component_name_from_path(file_path: str) -> str:
        """Derive a PascalCase component name from a file path.

        Examples:
            src/components/UserProfile.vue -> UserProfile
            src/components/user-profile.vue -> UserProfile
        """
        from pathlib import PurePosixPath

        stem = PurePosixPath(file_path.replace(os.sep, "/")).stem
        # Convert kebab-case to PascalCase
        parts = stem.replace("_", "-").split("-")
        return "".join(part[0].upper() + part[1:] if part else part for part in parts)

    @staticmethod
    def _kebab_to_pascal(name: str) -> str:
        """Convert kebab-case to PascalCase.

        Examples:
            my-component -> MyComponent
            user-profile-card -> UserProfileCard
        """
        parts = name.split("-")
        return "".join(part[0].upper() + part[1:] if part else part for part in parts)

    @staticmethod
    def _find_enclosing_function(
        line_no: int,
        nodes: list[Node],
    ) -> Node | None:
        """Find the function/component that encloses a given line."""
        candidates = [
            n
            for n in nodes
            if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.VARIABLE)
            and n.start_line is not None
            and n.end_line is not None
            and n.start_line <= line_no <= n.end_line
        ]
        if not candidates:
            return None
        # Return the most specific (smallest range) enclosing function
        return min(
            candidates,
            key=lambda n: (n.end_line or 0) - (n.start_line or 0),
        )
