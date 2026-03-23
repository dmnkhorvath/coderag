"""Vue.js framework detector for CodeRAG.

Detects Vue-specific patterns including Single File Components,
Composition API, Options API, state management (Vuex/Pinia),
Vue Router, provide/inject, composables, template analysis,
and Nuxt.js patterns from already-parsed AST nodes and source code.
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
    r"<template(?P<attrs>[^>]*)>(?P<content>.*)</template>",
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

# ── NEW: Component import detection ───────────────────────────
_COMPONENT_IMPORT_RE = re.compile(r"""import\s+(?P<name>[A-Z]\w+)\s+from\s+['"](?P<path>[^'"]*\.vue)['"]""")

# ── NEW: defineProps array style ──────────────────────────────
_DEFINE_PROPS_ARRAY_RE = re.compile(r"defineProps\s*\(\s*\[(?P<props>[^\]]+)\]")
_DEFINE_PROPS_OBJECT_RE = re.compile(r"defineProps\s*(?:<\{(?P<generics>[^}]+)\}>)?\s*\(\s*\{(?P<props>[^}]*)\}")
_DEFINE_PROPS_GENERIC_RE = re.compile(r"defineProps\s*<\{(?P<props>[^}]+)\}>\s*\(")

# ── NEW: defineEmits array style ──────────────────────────────
_DEFINE_EMITS_ARRAY_RE = re.compile(r"defineEmits\s*\(\s*\[(?P<events>[^\]]+)\]")

# ── NEW: Options API extensions ───────────────────────────────
_COMPONENTS_BLOCK_RE = re.compile(r"components\s*:\s*\{(?P<comps>[^}]+)\}")
_EXTENDS_OPTION_RE = re.compile(r"extends\s*:\s*(?P<comp>[A-Z]\w+)")
_MIXINS_OPTION_RE = re.compile(r"mixins\s*:\s*\[(?P<mixins>[^\]]+)\]")

# ── NEW: Store internals ──────────────────────────────────────
_STORE_DEPENDS_RE = re.compile(r"\buse(?P<name>[A-Z][a-zA-Z0-9]*)Store\s*\(")
_STORE_API_CALL_RE = re.compile(r"""(?:fetch|axios\.\w+|\$fetch|useFetch)\s*\(\s*['"](?P<url>[^'"]+)['"]""")

# ── NEW: Template directive detection ─────────────────────────
_VUE_BUILTIN_DIRECTIVES = frozenset(
    {
        "if",
        "else",
        "else-if",
        "for",
        "show",
        "model",
        "bind",
        "on",
        "slot",
        "text",
        "html",
        "pre",
        "cloak",
        "once",
        "memo",
    }
)
_CUSTOM_DIRECTIVE_RE = re.compile(r"\bv-(?P<directive>[a-z][a-z0-9-]+)")

# ── NEW: Teleport detection ───────────────────────────────────
_TELEPORT_RE = re.compile(r"""<Teleport[^>]*\bto=["'](?P<target>[^"']+)["']""")

# ── NEW: Nuxt patterns ───────────────────────────────────────
_DEFINE_PAGE_META_RE = re.compile(r"definePageMeta\s*\(\s*\{(?P<meta>[^}]*)\}")
_NUXT_LAYOUT_RE = re.compile(r"""layout\s*:\s*['"](?P<layout>[^'"]+)['"]""")
_NUXT_MIDDLEWARE_ARRAY_RE = re.compile(r"middleware\s*:\s*\[(?P<arr>[^\]]+)\]")
_NUXT_MIDDLEWARE_STRING_RE = re.compile(r"""middleware\s*:\s*['"](?P<single>[^'"]+)['"]""")
_NUXT_PROVIDE_RE = re.compile(r"""(?:nuxtApp\.)?provide\s*\(\s*['"](?P<key>[^'"]+)['"]""")
_NUXT_AUTO_IMPORT_RE = re.compile(
    r"\b(?P<name>useHead|useRoute|useRouter|useFetch|useAsyncData"
    r"|useLazyAsyncData|useLazyFetch|useState|useRuntimeConfig"
    r"|useAppConfig|useNuxtApp|useCookie|useRequestHeaders"
    r"|useRequestEvent|navigateTo|abortNavigation"
    r"|defineNuxtComponent|defineNuxtPlugin"
    r"|defineNuxtRouteMiddleware|defineEventHandler)\s*\("
)

# ── NEW: Component tag with prop/event extraction ─────────────
_COMPONENT_TAG_RE = re.compile(
    r"<(?P<comp>[A-Z][A-Za-z0-9]*)"
    r"(?P<attrs>[^>]*)(?:/>|>)",
    re.DOTALL,
)
_BOUND_PROP_RE = re.compile(r":(?P<prop>[a-z][\w-]*)=")
_V_ON_EVENT_RE = re.compile(r"(?:@|v-on:)(?P<event>[\w.-]+)=")
_V_MODEL_ON_COMP_RE = re.compile(r"v-model(?::(?P<arg>\w+))?=")

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
    """Detect Vue.js framework patterns in JavaScript/TypeScript files.

    Supports Vue 2 and Vue 3 patterns including:
    - Single File Components (.vue files)
    - Composition API (defineComponent, ref, reactive, etc.)
    - Options API (data, methods, computed, etc.)
    - State management (Vuex, Pinia)
    - Vue Router
    - Provide/Inject
    - Custom composables
    - Template analysis
    - Nuxt.js patterns
    """

    @property
    def framework_name(self) -> str:
        """Return the framework name."""
        return "vue"

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Vue patterns.

        Currently returns empty — Vue patterns are primarily per-file.
        Future: could detect component registration trees, store module composition.
        """
        return []

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
        """Detect Vue patterns in a single file.

        Runs all detection methods and returns discovered patterns.
        """
        source_text = source.decode("utf-8", errors="replace")
        patterns: list[FrameworkPattern] = []

        # SFC detection (only for .vue files)
        if file_path.endswith(".vue"):
            sfc = self._detect_sfc(file_path, source_text, nodes)
            if sfc:
                patterns.append(sfc)

        # Composition API
        comp_api = self._detect_composition_api(file_path, nodes, source_text)
        if comp_api:
            patterns.append(comp_api)

        # Options API
        opts_api = self._detect_options_api(file_path, nodes, source_text)
        if opts_api:
            patterns.append(opts_api)

        # Stores
        stores = self._detect_stores(file_path, nodes, source_text)
        if stores:
            patterns.append(stores)

        # Router
        router = self._detect_router(file_path, nodes, source_text)
        if router:
            patterns.append(router)

        # Provide/Inject
        pi = self._detect_provide_inject(file_path, nodes, source_text)
        if pi:
            patterns.append(pi)

        # Composables
        composables = self._detect_composables(file_path, nodes, source_text)
        if composables:
            patterns.append(composables)

        # Template patterns
        tpl = self._detect_template_patterns(file_path, source_text, nodes)
        if tpl:
            patterns.append(tpl)

        # Nuxt patterns
        nuxt = self._detect_nuxt_patterns(file_path, source_text, nodes)
        if nuxt:
            patterns.append(nuxt)

        return patterns

    # ── SFC detection ─────────────────────────────────────────

    def _detect_sfc(
        self,
        file_path: str,
        source_text: str,
        nodes: list[Node],
    ) -> FrameworkPattern | None:
        """Detect Vue Single File Component structure.

        Identifies <template>, <script>, and <style> blocks,
        determines script setup mode and language.
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

    # ── Composition API detection ──────────────────────────────

    def _detect_composition_api(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Vue Composition API patterns.

        Identifies defineComponent, defineProps, defineEmits, defineExpose,
        ref, reactive, computed, watch, and lifecycle hooks.
        Also detects component imports, prop definitions, and emit declarations.
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        api_usages: list[str] = []

        component_name = self._component_name_from_path(file_path)
        component_id = generate_node_id(file_path, 1, NodeKind.COMPONENT, component_name)

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

        # ── NEW: Detect component imports (vue_imports_component) ──
        for match in _COMPONENT_IMPORT_RE.finditer(source_text):
            comp_name = match.group("name")
            comp_path = match.group("path")
            line_no = source_text[: match.start()].count("\n") + 1

            new_edges.append(
                Edge(
                    source_id=generate_node_id(file_path, 1, NodeKind.FILE, file_path)
                    if not file_path.endswith(".vue")
                    else component_id,
                    target_id=f"__unresolved__:component:{comp_name}",
                    kind=EdgeKind.IMPORTS,
                    confidence=0.95,
                    line_number=line_no,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "vue_imports_component",
                        "component_name": comp_name,
                        "import_path": comp_path,
                    },
                )
            )

        # ── NEW: Detect defineProps (vue_defines_prop) ──
        # Array style: defineProps(['title', 'count'])
        for match in _DEFINE_PROPS_ARRAY_RE.finditer(source_text):
            props_str = match.group("props")
            line_no = source_text[: match.start()].count("\n") + 1
            prop_names = [p.strip().strip("'\"") for p in props_str.split(",") if p.strip()]
            for prop_name in prop_names:
                prop_node_id = generate_node_id(file_path, line_no, NodeKind.VARIABLE, f"prop:{prop_name}")
                new_nodes.append(
                    Node(
                        id=prop_node_id,
                        kind=NodeKind.VARIABLE,
                        name=prop_name,
                        qualified_name=f"vue:prop:{prop_name}",
                        file_path=file_path,
                        start_line=line_no,
                        end_line=line_no,
                        language="javascript",
                        metadata={
                            "framework": "vue",
                            "prop_name": prop_name,
                            "definition_style": "array",
                        },
                    )
                )
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=prop_node_id,
                        kind=EdgeKind.CONTAINS,
                        confidence=0.95,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_defines_prop",
                            "prop_name": prop_name,
                        },
                    )
                )

        # Generic/object style: defineProps<{title: string}>() or defineProps({title: String})
        for match in _DEFINE_PROPS_GENERIC_RE.finditer(source_text):
            props_str = match.group("props")
            line_no = source_text[: match.start()].count("\n") + 1
            # Extract property names from TypeScript generic: "title: string, count: number"
            prop_names = re.findall(r"(\w+)\s*[:\?]", props_str)
            for prop_name in prop_names:
                prop_node_id = generate_node_id(file_path, line_no, NodeKind.VARIABLE, f"prop:{prop_name}")
                new_nodes.append(
                    Node(
                        id=prop_node_id,
                        kind=NodeKind.VARIABLE,
                        name=prop_name,
                        qualified_name=f"vue:prop:{prop_name}",
                        file_path=file_path,
                        start_line=line_no,
                        end_line=line_no,
                        language="javascript",
                        metadata={
                            "framework": "vue",
                            "prop_name": prop_name,
                            "definition_style": "generic",
                        },
                    )
                )
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=prop_node_id,
                        kind=EdgeKind.CONTAINS,
                        confidence=0.95,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_defines_prop",
                            "prop_name": prop_name,
                        },
                    )
                )

        # ── NEW: Detect defineEmits (vue_emits_event) ──
        for match in _DEFINE_EMITS_ARRAY_RE.finditer(source_text):
            events_str = match.group("events")
            line_no = source_text[: match.start()].count("\n") + 1
            event_names = [e.strip().strip("'\"") for e in events_str.split(",") if e.strip()]
            for event_name in event_names:
                event_node_id = generate_node_id(file_path, line_no, NodeKind.EVENT, f"emit:{event_name}")
                new_nodes.append(
                    Node(
                        id=event_node_id,
                        kind=NodeKind.EVENT,
                        name=event_name,
                        qualified_name=f"vue:emit:{event_name}",
                        file_path=file_path,
                        start_line=line_no,
                        end_line=line_no,
                        language="javascript",
                        metadata={
                            "framework": "vue",
                            "event_name": event_name,
                        },
                    )
                )
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=event_node_id,
                        kind=EdgeKind.DISPATCHES_EVENT,
                        confidence=0.95,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_emits_event",
                            "event_name": event_name,
                        },
                    )
                )

        if not api_usages and not new_edges:
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

    # ── Options API detection ─────────────────────────────────

    def _detect_options_api(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Vue Options API patterns.

        Identifies data(), methods, computed, watch, lifecycle hooks,
        component registration, extends, and mixins.
        """
        options_found: list[str] = []
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        component_name = self._component_name_from_path(file_path)
        component_id = generate_node_id(file_path, 1, NodeKind.COMPONENT, component_name)

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

        # ── NEW: Detect component registration (vue_registers_component) ──
        for match in _COMPONENTS_BLOCK_RE.finditer(source_text):
            comps_str = match.group("comps")
            line_no = source_text[: match.start()].count("\n") + 1
            # Extract component names: identifiers that start with uppercase
            comp_names = re.findall(r"\b([A-Z]\w+)\b", comps_str)
            for comp in comp_names:
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=f"__unresolved__:component:{comp}",
                        kind=EdgeKind.CONTAINS,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_registers_component",
                            "component_name": comp,
                        },
                    )
                )

        # ── NEW: Detect extends (vue_extends_component) ──
        for match in _EXTENDS_OPTION_RE.finditer(source_text):
            comp = match.group("comp")
            line_no = source_text[: match.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=component_id,
                    target_id=f"__unresolved__:component:{comp}",
                    kind=EdgeKind.EXTENDS,
                    confidence=0.90,
                    line_number=line_no,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "vue_extends_component",
                        "base_component": comp,
                    },
                )
            )

        # ── NEW: Detect mixins (vue_uses_mixin) ──
        for match in _MIXINS_OPTION_RE.finditer(source_text):
            mixins_str = match.group("mixins")
            line_no = source_text[: match.start()].count("\n") + 1
            mixin_names = [m.strip() for m in re.findall(r"\b([A-Za-z]\w+)\b", mixins_str)]
            for mixin_name in mixin_names:
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=f"__unresolved__:mixin:{mixin_name}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_uses_mixin",
                            "mixin_name": mixin_name,
                        },
                    )
                )

        if not options_found and not new_edges:
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

    # ── Store detection ────────────────────────────────────────

    def _detect_stores(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Vuex and Pinia store usage.

        Also detects inter-store dependencies and API calls within stores.
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        store_usages: list[dict[str, str]] = []

        # Track store definition ranges for inter-store and API detection
        store_ranges: list[dict[str, Any]] = []

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
            store_ranges.append(
                {
                    "name": store_name,
                    "node_id": store_node.id,
                    "start_line": line_no,
                }
            )

        # Detect useXxxStore() calls (Pinia convention)
        for match in _USE_STORE_RE.finditer(source_text):
            store_name = match.group("name")
            line_no = source_text[: match.start()].count("\n") + 1
            store_usages.append({"type": "pinia", "name": store_name, "action": "use"})

            # Check if this call is inside a store definition (store_depends_on)
            inside_store = None
            for sr in store_ranges:
                if sr["start_line"] <= line_no:
                    inside_store = sr

            if inside_store and inside_store["name"] != store_name:
                # Inter-store dependency
                new_edges.append(
                    Edge(
                        source_id=inside_store["node_id"],
                        target_id=f"__unresolved__:store:{store_name}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "store_depends_on",
                            "store_type": "pinia",
                            "source_store": inside_store["name"],
                            "target_store": store_name,
                        },
                    )
                )
            else:
                # Regular store usage from a component
                enclosing = self._find_enclosing_function(line_no, nodes)
                if enclosing:
                    new_edges.append(
                        Edge(
                            source_id=enclosing.id,
                            target_id=f"__unresolved__:store:{store_name}",
                            kind=EdgeKind.CALLS,
                            confidence=0.90,
                            line_number=line_no,
                            metadata={
                                "framework": "vue",
                                "vue_edge_type": "vue_uses_store",
                                "store_type": "pinia",
                                "store_name": store_name,
                            },
                        )
                    )

        # ── NEW: Detect API calls inside store definitions (store_fetches_api) ──
        for match in _STORE_API_CALL_RE.finditer(source_text):
            url = match.group("url")
            line_no = source_text[: match.start()].count("\n") + 1

            # Find which store this API call belongs to
            parent_store = None
            for sr in store_ranges:
                if sr["start_line"] <= line_no:
                    parent_store = sr

            if parent_store:
                new_edges.append(
                    Edge(
                        source_id=parent_store["node_id"],
                        target_id=f"__unresolved__:api:{url}",
                        kind=EdgeKind.API_CALLS,
                        confidence=0.80,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "store_fetches_api",
                            "api_url": url,
                            "store_name": parent_store["name"],
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

    # ── Router detection ──────────────────────────────────────

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

        # Detect lazy-loaded route components → vue_lazy_loads (DYNAMIC_IMPORTS)
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
                        kind=EdgeKind.DYNAMIC_IMPORTS,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_lazy_loads",
                            "lazy_import": True,
                            "module_path": module_path,
                        },
                    )
                )

        # ── NEW: Detect navigation guards (vue_guards_route) ──
        for match in _NAV_GUARD_RE.finditer(source_text):
            guard_name = match.group("guard")
            line_no = source_text[: match.start()].count("\n") + 1
            router_usages.append({"type": "nav_guard", "guard": guard_name, "line": line_no})

            # Create guard node
            guard_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MIDDLEWARE, f"guard:{guard_name}"),
                kind=NodeKind.MIDDLEWARE,
                name=guard_name,
                qualified_name=f"vue:guard:{guard_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "guard_type": guard_name,
                },
            )
            new_nodes.append(guard_node)

            new_edges.append(
                Edge(
                    source_id=guard_node.id,
                    target_id="__unresolved__:router",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.90,
                    line_number=line_no,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "vue_guards_route",
                        "guard_name": guard_name,
                    },
                )
            )

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

    # ── Provide/Inject detection ───────────────────────────────

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
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_provides",
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
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_injects",
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

    # ── Composables detection ─────────────────────────────────

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
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_uses_composable",
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

    # ── Template patterns detection ───────────────────────────

    def _detect_template_patterns(
        self,
        file_path: str,
        source_text: str,
        nodes: list[Node],
    ) -> FrameworkPattern | None:
        """Detect patterns in Vue template blocks.

        Analyzes <template> content for component usage, v-model directives,
        slot definitions/usage, event listeners, dynamic components,
        custom directives, teleport, prop passing, and event listening.
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

        component_name = self._component_name_from_path(file_path)
        component_id = generate_node_id(file_path, 1, NodeKind.COMPONENT, component_name)

        # ── Detect PascalCase component usage (vue_renders_component) ──
        components_used: list[str] = []
        for match in _TEMPLATE_COMPONENT_RE.finditer(template_content):
            comp_name = match.group("comp")
            if comp_name not in _VUE_BUILTIN_COMPONENTS and comp_name not in components_used:
                components_used.append(comp_name)
                line_no = template_start_line + template_content[: match.start()].count("\n")

                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=f"__unresolved__:component:{comp_name}",
                        kind=EdgeKind.RENDERS,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_renders_component",
                            "component_name": comp_name,
                        },
                    )
                )

        # ── Detect kebab-case component usage (vue_renders_component) ──
        kebab_components: list[str] = []
        for match in _TEMPLATE_KEBAB_COMP_RE.finditer(template_content):
            comp_name = match.group("comp")
            if comp_name not in _HTML_ELEMENTS and comp_name not in kebab_components:
                kebab_components.append(comp_name)
                line_no = template_start_line + template_content[: match.start()].count("\n")

                pascal_name = self._kebab_to_pascal(comp_name)
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=f"__unresolved__:component:{pascal_name}",
                        kind=EdgeKind.RENDERS,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_renders_component",
                            "component_name": pascal_name,
                            "original_tag": comp_name,
                        },
                    )
                )

        template_info["components_used"] = components_used
        template_info["kebab_components"] = kebab_components

        # ── NEW: Detect prop passing and event listening on component tags ──
        all_component_names = set(components_used)
        for kc in kebab_components:
            all_component_names.add(self._kebab_to_pascal(kc))

        for match in _COMPONENT_TAG_RE.finditer(template_content):
            comp_name = match.group("comp")
            if comp_name in _VUE_BUILTIN_COMPONENTS:
                continue
            attrs = match.group("attrs")
            line_no = template_start_line + template_content[: match.start()].count("\n")

            # vue_passes_prop: detect :prop="value" bindings
            for prop_match in _BOUND_PROP_RE.finditer(attrs):
                prop_name = prop_match.group("prop")
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=f"__unresolved__:component:{comp_name}",
                        kind=EdgeKind.PASSES_PROP,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_passes_prop",
                            "prop_name": prop_name,
                            "child_component": comp_name,
                        },
                    )
                )

            # vue_listens_event: detect @event="handler" on component tags
            for event_match in _V_ON_EVENT_RE.finditer(attrs):
                event_name = event_match.group("event")
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=f"__unresolved__:component:{comp_name}",
                        kind=EdgeKind.LISTENS_TO,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_listens_event",
                            "event_name": event_name,
                            "child_component": comp_name,
                        },
                    )
                )

            # vue_v_model_binds: detect v-model on component tags
            for vmodel_match in _V_MODEL_ON_COMP_RE.finditer(attrs):
                arg = vmodel_match.group("arg")
                model_name = arg if arg else "modelValue"
                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=f"__unresolved__:component:{comp_name}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_v_model_binds",
                            "model_name": model_name,
                            "child_component": comp_name,
                        },
                    )
                )

        # ── Detect v-model directives (metadata only) ──
        v_models: list[str] = []
        for match in _V_MODEL_RE.finditer(template_content):
            arg = match.group("arg")
            v_models.append(arg if arg else "modelValue")
        template_info["v_models"] = v_models

        # ── NEW: Detect slot definitions (vue_slot_defines) ──
        slot_defs: list[str] = []
        for match in _SLOT_DEF_RE.finditer(template_content):
            slot_name = match.group("name")
            slot_name = slot_name if slot_name else "default"
            slot_defs.append(slot_name)
            line_no = template_start_line + template_content[: match.start()].count("\n")

            slot_node_id = generate_node_id(file_path, line_no, NodeKind.VARIABLE, f"slot:{slot_name}")
            new_nodes.append(
                Node(
                    id=slot_node_id,
                    kind=NodeKind.VARIABLE,
                    name=f"slot:{slot_name}",
                    qualified_name=f"vue:slot:{slot_name}",
                    file_path=file_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="javascript",
                    metadata={
                        "framework": "vue",
                        "slot_name": slot_name,
                    },
                )
            )
            new_edges.append(
                Edge(
                    source_id=component_id,
                    target_id=slot_node_id,
                    kind=EdgeKind.CONTAINS,
                    confidence=0.90,
                    line_number=line_no,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "vue_slot_defines",
                        "slot_name": slot_name,
                    },
                )
            )
        template_info["slot_definitions"] = slot_defs

        # ── NEW: Detect slot usage (vue_slot_fills) ──
        slot_uses: list[str] = []
        for match in _SLOT_USE_RE.finditer(template_content):
            slot_name = match.group("name")
            slot_uses.append(slot_name)
            line_no = template_start_line + template_content[: match.start()].count("\n")

            new_edges.append(
                Edge(
                    source_id=component_id,
                    target_id=f"__unresolved__:slot:{slot_name}",
                    kind=EdgeKind.RENDERS,
                    confidence=0.85,
                    line_number=line_no,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "vue_slot_fills",
                        "slot_name": slot_name,
                    },
                )
            )
        template_info["slot_usages"] = slot_uses

        # ── Detect event listeners (metadata) ──
        events: list[str] = []
        for match in _EVENT_LISTENER_RE.finditer(template_content):
            event_name = match.group("event")
            if event_name not in events:
                events.append(event_name)
        template_info["event_listeners"] = events

        # ── NEW: Detect custom directives (vue_uses_directive) ──
        directives_used: list[str] = []
        for match in _CUSTOM_DIRECTIVE_RE.finditer(template_content):
            directive_name = match.group("directive")
            if directive_name not in _VUE_BUILTIN_DIRECTIVES and directive_name not in directives_used:
                directives_used.append(directive_name)
                line_no = template_start_line + template_content[: match.start()].count("\n")

                new_edges.append(
                    Edge(
                        source_id=component_id,
                        target_id=f"__unresolved__:directive:{directive_name}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "vue_uses_directive",
                            "directive_name": directive_name,
                        },
                    )
                )
        template_info["custom_directives"] = directives_used

        # ── NEW: Detect Teleport (vue_teleports_to) ──
        for match in _TELEPORT_RE.finditer(template_content):
            target = match.group("target")
            line_no = template_start_line + template_content[: match.start()].count("\n")

            new_edges.append(
                Edge(
                    source_id=component_id,
                    target_id=f"__unresolved__:dom:{target}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.95,
                    line_number=line_no,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "vue_teleports_to",
                        "teleport_target": target,
                    },
                )
            )

        # ── NEW: Detect dynamic components (vue_dynamic_component) ──
        dynamic_count = 0
        for match in _DYNAMIC_COMPONENT_RE.finditer(template_content):
            dynamic_count += 1
            line_no = template_start_line + template_content[: match.start()].count("\n")

            new_edges.append(
                Edge(
                    source_id=component_id,
                    target_id="__unresolved__:dynamic_component",
                    kind=EdgeKind.RENDERS,
                    confidence=0.70,
                    line_number=line_no,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "vue_dynamic_component",
                    },
                )
            )
        template_info["dynamic_components"] = dynamic_count

        # Only return pattern if we found something interesting
        has_content = (
            components_used
            or kebab_components
            or v_models
            or slot_defs
            or slot_uses
            or events
            or dynamic_count > 0
            or directives_used
            or new_edges
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

    # ── Nuxt.js patterns detection ─────────────────────────────

    def _detect_nuxt_patterns(
        self,
        file_path: str,
        source_text: str,
        nodes: list[Node],
    ) -> FrameworkPattern | None:
        """Detect Nuxt.js-specific patterns.

        Identifies file-based routing, layouts, middleware, plugins,
        server API routes, and auto-imported composables.
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        nuxt_usages: list[dict[str, Any]] = []

        # Normalize path separators
        norm_path = file_path.replace(os.sep, "/")
        component_name = self._component_name_from_path(file_path)
        component_id = generate_node_id(file_path, 1, NodeKind.COMPONENT, component_name)
        file_node_id = generate_node_id(file_path, 1, NodeKind.FILE, file_path)

        # ── nuxt_page_route: files in pages/ directory ──
        is_pages = "/pages/" in norm_path or norm_path.startswith("pages/")
        if is_pages and file_path.endswith(".vue"):
            # Derive route path from file path
            if "/pages/" in norm_path:
                pages_idx = norm_path.index("/pages/")
                route_segment = norm_path[pages_idx + len("/pages/") :]
            else:
                route_segment = norm_path[len("pages/") :]
            # Remove .vue extension
            route_segment = route_segment.rsplit(".", 1)[0]
            # Convert index to /
            if route_segment.endswith("/index"):
                route_segment = route_segment[:-6] or "/"
            elif route_segment == "index":
                route_segment = "/"
            else:
                route_segment = "/" + route_segment
            # Convert [param] to :param
            route_segment = re.sub(r"\[([^\]]+)\]", r":\1", route_segment)

            route_node = Node(
                id=generate_node_id(file_path, 1, NodeKind.ROUTE, route_segment),
                kind=NodeKind.ROUTE,
                name=route_segment,
                qualified_name=f"nuxt:route:{route_segment}",
                file_path=file_path,
                start_line=1,
                end_line=1,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "nuxt": True,
                    "route_path": route_segment,
                    "page_file": file_path,
                },
            )
            new_nodes.append(route_node)

            new_edges.append(
                Edge(
                    source_id=component_id,
                    target_id=route_node.id,
                    kind=EdgeKind.ROUTES_TO,
                    confidence=0.98,
                    line_number=1,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "nuxt_page_route",
                        "route_path": route_segment,
                    },
                )
            )
            nuxt_usages.append({"type": "page_route", "route": route_segment})

        # ── nuxt_layout_wraps: definePageMeta({ layout: '...' }) ──
        meta_match = _DEFINE_PAGE_META_RE.search(source_text)
        if meta_match:
            meta_content = meta_match.group("meta")

            layout_match = _NUXT_LAYOUT_RE.search(meta_content)
            if layout_match:
                layout_name = layout_match.group("layout")
                line_no = source_text[: meta_match.start()].count("\n") + 1

                layout_id = f"__unresolved__:layout:{layout_name}"
                new_edges.append(
                    Edge(
                        source_id=layout_id,
                        target_id=component_id,
                        kind=EdgeKind.RENDERS,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "nuxt_layout_wraps",
                            "layout_name": layout_name,
                        },
                    )
                )
                nuxt_usages.append({"type": "layout", "layout": layout_name})

            # ── nuxt_middleware_guards: definePageMeta({ middleware: [...] }) ──
            mw_array_match = _NUXT_MIDDLEWARE_ARRAY_RE.search(meta_content)
            mw_string_match = _NUXT_MIDDLEWARE_STRING_RE.search(meta_content)

            middleware_names: list[str] = []
            if mw_array_match:
                arr_str = mw_array_match.group("arr")
                middleware_names = [m.strip().strip("'\"") for m in arr_str.split(",") if m.strip()]
            elif mw_string_match:
                middleware_names = [mw_string_match.group("single")]

            for mw_name in middleware_names:
                line_no = source_text[: meta_match.start()].count("\n") + 1
                mw_id = f"__unresolved__:middleware:{mw_name}"

                new_edges.append(
                    Edge(
                        source_id=mw_id,
                        target_id=component_id,
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "nuxt_middleware_guards",
                            "middleware_name": mw_name,
                        },
                    )
                )
                nuxt_usages.append({"type": "middleware", "middleware": mw_name})

        # ── nuxt_plugin_provides: provide() in plugins/ directory ──
        if "/plugins/" in norm_path or norm_path.startswith("plugins/"):
            for match in _NUXT_PROVIDE_RE.finditer(source_text):
                key = match.group("key")
                line_no = source_text[: match.start()].count("\n") + 1

                provider_node = Node(
                    id=generate_node_id(file_path, line_no, NodeKind.PROVIDER, f"nuxt:provide:{key}"),
                    kind=NodeKind.PROVIDER,
                    name=f"nuxt:provide:{key}",
                    qualified_name=f"nuxt:plugin:provide:{key}",
                    file_path=file_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="javascript",
                    metadata={
                        "framework": "vue",
                        "nuxt": True,
                        "provide_key": key,
                    },
                )
                new_nodes.append(provider_node)

                new_edges.append(
                    Edge(
                        source_id=file_node_id,
                        target_id=provider_node.id,
                        kind=EdgeKind.PROVIDES_CONTEXT,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "vue",
                            "vue_edge_type": "nuxt_plugin_provides",
                            "provide_key": key,
                        },
                    )
                )
                nuxt_usages.append({"type": "plugin_provides", "key": key})

        # ── nuxt_server_api: files in server/api/ directory ──
        if "/server/api/" in norm_path or norm_path.startswith("server/api/"):
            # Derive API route from file path
            if "/server/api/" in norm_path:
                api_idx = norm_path.index("/server/api/")
                api_segment = norm_path[api_idx + len("/server/api/") :]
            else:
                api_segment = norm_path[len("server/api/") :]
            # Remove extension
            api_segment = api_segment.rsplit(".", 1)[0]
            api_route = "/api/" + api_segment

            api_route_node = Node(
                id=generate_node_id(file_path, 1, NodeKind.ROUTE, api_route),
                kind=NodeKind.ROUTE,
                name=api_route,
                qualified_name=f"nuxt:server:api:{api_route}",
                file_path=file_path,
                start_line=1,
                end_line=1,
                language="javascript",
                metadata={
                    "framework": "vue",
                    "nuxt": True,
                    "api_route": api_route,
                    "server_file": file_path,
                },
            )
            new_nodes.append(api_route_node)

            new_edges.append(
                Edge(
                    source_id=file_node_id,
                    target_id=api_route_node.id,
                    kind=EdgeKind.ROUTES_TO,
                    confidence=0.95,
                    line_number=1,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "nuxt_server_api",
                        "api_route": api_route,
                    },
                )
            )
            nuxt_usages.append({"type": "server_api", "route": api_route})

        # ── nuxt_auto_imports: auto-imported composables ──
        for match in _NUXT_AUTO_IMPORT_RE.finditer(source_text):
            name = match.group("name")
            line_no = source_text[: match.start()].count("\n") + 1

            new_edges.append(
                Edge(
                    source_id=component_id if file_path.endswith(".vue") else file_node_id,
                    target_id=f"__unresolved__:nuxt:{name}",
                    kind=EdgeKind.IMPORTS,
                    confidence=0.80,
                    line_number=line_no,
                    metadata={
                        "framework": "vue",
                        "vue_edge_type": "nuxt_auto_imports",
                        "composable_name": name,
                        "auto_imported": True,
                    },
                )
            )
            nuxt_usages.append({"type": "auto_import", "name": name})

        if not nuxt_usages:
            return None

        return FrameworkPattern(
            framework_name="vue",
            pattern_type="nuxt_patterns",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "nuxt_usages": nuxt_usages,
                "nuxt_usage_count": len(nuxt_usages),
            },
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
