"""Tests for Next.js and Vue framework detectors."""

from __future__ import annotations

import json

from coderag.core.models import (
    EdgeKind,
    Node,
    NodeKind,
    generate_node_id,
)
from coderag.plugins.javascript.frameworks.nextjs import NextJSDetector
from coderag.plugins.javascript.frameworks.vue import VueDetector

# ===================================================================
# Helpers
# ===================================================================


def _make_node(
    file_path: str,
    line: int,
    kind: NodeKind,
    name: str,
    *,
    end_line: int | None = None,
    language: str = "typescript",
) -> Node:
    """Create a minimal Node for testing."""
    return Node(
        id=generate_node_id(file_path, line, kind, name),
        kind=kind,
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=line,
        end_line=end_line or line + 10,
        language=language,
    )


def _collect_pattern_nodes(patterns, kind=None):
    """Collect all nodes from a list of FrameworkPattern objects."""
    nodes = []
    for p in patterns:
        for n in p.nodes:
            if kind is None or n.kind == kind:
                nodes.append(n)
    return nodes


def _collect_pattern_edges(patterns, kind=None):
    """Collect all edges from a list of FrameworkPattern objects."""
    edges = []
    for p in patterns:
        for e in p.edges:
            if kind is None or e.kind == kind:
                edges.append(e)
    return edges


# ===================================================================
# Next.js Detector Tests
# ===================================================================


class TestNextJSDetectFramework:
    """Test NextJSDetector.detect_framework()."""

    def test_detects_next_in_dependencies(self, tmp_path):
        pkg = {"dependencies": {"next": "14.0.0", "react": "18.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detector = NextJSDetector()
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detects_next_in_dev_dependencies(self, tmp_path):
        pkg = {"devDependencies": {"next": "14.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detector = NextJSDetector()
        assert detector.detect_framework(str(tmp_path)) is True

    def test_no_next_dependency(self, tmp_path):
        pkg = {"dependencies": {"react": "18.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detector = NextJSDetector()
        assert detector.detect_framework(str(tmp_path)) is False

    def test_no_package_json(self, tmp_path):
        detector = NextJSDetector()
        assert detector.detect_framework(str(tmp_path)) is False

    def test_invalid_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("not valid json")
        detector = NextJSDetector()
        assert detector.detect_framework(str(tmp_path)) is False

    def test_framework_name(self):
        assert NextJSDetector().framework_name == "nextjs"


class TestNextJSAppRouter:
    """Test Next.js App Router route detection."""

    def test_page_tsx_root(self):
        source = b'"use client";\nexport default function Home() {\n  return <div>Home</div>;\n}\n'
        file_path = "app/page.tsx"
        nodes = [_make_node(file_path, 2, NodeKind.FUNCTION, "Home")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        route = route_nodes[0]
        assert route.metadata["router"] == "app"
        assert route.metadata["url_pattern"] == "/"
        assert route.metadata["file_type"] == "page"

    def test_nested_page(self):
        source = b"export default function Settings() {\n  return <div>Settings</div>;\n}\n"
        file_path = "app/dashboard/settings/page.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "Settings")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata["url_pattern"] == "/dashboard/settings"

    def test_dynamic_segment(self):
        source = b"export default function UserPage() {\n  return <div>User</div>;\n}\n"
        file_path = "app/users/[id]/page.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "UserPage")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert "[id]" in route_nodes[0].metadata["url_pattern"]

    def test_catch_all_segment(self):
        source = b"export default function DocsPage() {\n  return <div>Docs</div>;\n}\n"
        file_path = "app/docs/[...slug]/page.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "DocsPage")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert "[...slug]" in route_nodes[0].metadata["url_pattern"]

    def test_route_group_excluded_from_url(self):
        source = b"export default function About() {\n  return <div>About</div>;\n}\n"
        file_path = "app/(marketing)/about/page.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "About")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        url = route_nodes[0].metadata["url_pattern"]
        assert "(marketing)" not in url
        assert url == "/about"

    def test_layout_tsx(self):
        source = (
            b"export default function RootLayout({ children }) {\n  return <html><body>{children}</body></html>;\n}\n"
        )
        file_path = "app/layout.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "RootLayout")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata["file_type"] == "layout"

    def test_loading_tsx(self):
        source = b"export default function Loading() {\n  return <div>Loading...</div>;\n}\n"
        file_path = "app/loading.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "Loading")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata["file_type"] == "loading"

    def test_error_tsx(self):
        source = b'"use client";\nexport default function Error({ error, reset }) {\n  return <div>Error</div>;\n}\n'
        file_path = "app/error.tsx"
        nodes = [_make_node(file_path, 2, NodeKind.FUNCTION, "Error")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata["file_type"] == "error"

    def test_route_handler_with_methods(self):
        source = b"export async function GET(request) {\n  return Response.json({ users: [] });\n}\n\nexport async function POST(request) {\n  return Response.json({ created: true });\n}\n"
        file_path = "app/api/users/route.ts"
        nodes = [
            _make_node(file_path, 1, NodeKind.FUNCTION, "GET"),
            _make_node(file_path, 5, NodeKind.FUNCTION, "POST"),
        ]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) == 2
        methods = {n.metadata["http_method"] for n in route_nodes}
        assert methods == {"GET", "POST"}
        assert all(n.metadata["url_pattern"] == "/api/users" for n in route_nodes)

    def test_routes_to_edges(self):
        source = b"export async function GET(request) {\n  return Response.json({});\n}\n"
        file_path = "app/api/data/route.ts"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "GET")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        edges = _collect_pattern_edges(patterns, EdgeKind.ROUTES_TO)
        assert len(edges) >= 1
        assert edges[0].target_id == nodes[0].id


class TestNextJSPagesRouter:
    """Test Next.js Pages Router detection."""

    def test_pages_index(self):
        source = b"export default function Home() {\n  return <div>Home</div>;\n}\n"
        file_path = "pages/index.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "Home")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata["router"] == "pages"
        assert route_nodes[0].metadata["url_pattern"] == "/"

    def test_pages_nested(self):
        source = b"export default function About() {\n  return <div>About</div>;\n}\n"
        file_path = "pages/about.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "About")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata["url_pattern"] == "/about"

    def test_pages_dynamic(self):
        source = b"export default function UserPage() {\n  return <div>User</div>;\n}\n"
        file_path = "pages/users/[id].tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "UserPage")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert "[id]" in route_nodes[0].metadata["url_pattern"]

    def test_pages_api_route(self):
        source = b'export default function handler(req, res) {\n  res.status(200).json({ message: "Hello" });\n}\n'
        file_path = "pages/api/hello.ts"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "handler")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata["is_api"] is True

    def test_pages_skip_underscore_files(self):
        source = b"export default function App({ Component, pageProps }) {\n  return <Component {...pageProps} />;\n}\n"
        file_path = "pages/_app.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "App")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) == 0


class TestNextJSDirectives:
    """Test use client and use server directive detection."""

    def test_use_client_directive(self):
        source = b'"use client";\nexport default function Counter() {\n  return <button>Count</button>;\n}\n'
        file_path = "app/components/Counter.tsx"
        nodes = [_make_node(file_path, 2, NodeKind.FUNCTION, "Counter")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        comp_nodes = _collect_pattern_nodes(patterns, NodeKind.COMPONENT)
        assert len(comp_nodes) >= 1
        assert comp_nodes[0].metadata["directive"] == "use client"
        assert comp_nodes[0].metadata["component_type"] == "client"

    def test_use_server_directive(self):
        source = b'"use server";\nexport async function CreateUser(data) {\n  // server action\n}\n'
        file_path = "app/actions/user.ts"
        nodes = [_make_node(file_path, 2, NodeKind.FUNCTION, "CreateUser")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        comp_nodes = _collect_pattern_nodes(patterns, NodeKind.COMPONENT)
        assert len(comp_nodes) >= 1
        assert comp_nodes[0].metadata["directive"] == "use server"
        assert comp_nodes[0].metadata["component_type"] == "server"

    def test_no_directive(self):
        source = b"export default function Page() {\n  return <div>Page</div>;\n}\n"
        file_path = "app/components/Page.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "Page")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        directive_patterns = [p for p in patterns if p.pattern_type == "directives"]
        assert len(directive_patterns) == 0


class TestNextJSNonRouteFiles:
    """Test that non-route files are not detected."""

    def test_regular_component_file(self):
        source = b"export default function Button() {\n  return <button>Click</button>;\n}\n"
        file_path = "src/components/Button.tsx"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "Button")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) == 0

    def test_non_route_file_in_app(self):
        source = b"export function formatDate(d) { return d.toISOString(); }\n"
        file_path = "app/utils/format.ts"
        nodes = [_make_node(file_path, 1, NodeKind.FUNCTION, "formatDate")]
        detector = NextJSDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        route_nodes = _collect_pattern_nodes(patterns, NodeKind.ROUTE)
        assert len(route_nodes) == 0


# ===================================================================
# Vue Detector Tests
# ===================================================================


class TestVueDetectFramework:
    """Test VueDetector.detect_framework()."""

    def test_detects_vue_in_dependencies(self, tmp_path):
        pkg = {"dependencies": {"vue": "3.3.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detector = VueDetector()
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detects_vue_in_dev_dependencies(self, tmp_path):
        pkg = {"devDependencies": {"vue": "3.3.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detector = VueDetector()
        assert detector.detect_framework(str(tmp_path)) is True

    def test_no_vue_dependency(self, tmp_path):
        pkg = {"dependencies": {"react": "18.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        detector = VueDetector()
        assert detector.detect_framework(str(tmp_path)) is False

    def test_no_package_json(self, tmp_path):
        detector = VueDetector()
        assert detector.detect_framework(str(tmp_path)) is False

    def test_invalid_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("not valid json")
        detector = VueDetector()
        assert detector.detect_framework(str(tmp_path)) is False

    def test_framework_name(self):
        assert VueDetector().framework_name == "vue"


class TestVueSFC:
    """Test Vue Single File Component detection."""

    def test_basic_sfc(self):
        source = b'<template>\n  <div>{{ message }}</div>\n</template>\n\n<script>\nexport default {\n  data() {\n    return { message: "Hello" };\n  }\n};\n</script>\n\n<style scoped>\ndiv { color: red; }\n</style>\n'
        file_path = "src/components/HelloWorld.vue"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_nodes = _collect_pattern_nodes(patterns, NodeKind.COMPONENT)
        assert len(comp_nodes) >= 1
        comp = comp_nodes[0]
        assert comp.name == "HelloWorld"
        assert comp.metadata["component_type"] == "sfc"
        assert comp.metadata["has_template"] is True
        assert comp.metadata["has_script"] is True
        assert comp.metadata["has_style"] is True

    def test_sfc_script_setup(self):
        source = b'<template>\n  <div>{{ count }}</div>\n</template>\n\n<script setup lang="ts">\nimport { ref } from "vue";\nconst count = ref(0);\n</script>\n'
        file_path = "src/components/Counter.vue"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_nodes = _collect_pattern_nodes(patterns, NodeKind.COMPONENT)
        assert len(comp_nodes) >= 1
        comp = comp_nodes[0]
        assert comp.metadata["script_setup"] is True
        assert comp.metadata["script_lang"] == "typescript"

    def test_sfc_template_only(self):
        source = b"<template>\n  <div>Static content</div>\n</template>\n"
        file_path = "src/components/Static.vue"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_nodes = _collect_pattern_nodes(patterns, NodeKind.COMPONENT)
        assert len(comp_nodes) >= 1
        assert comp_nodes[0].metadata["has_template"] is True
        assert comp_nodes[0].metadata["has_script"] is False

    def test_non_vue_file_no_sfc(self):
        source = b"export function helper() { return 42; }\n"
        file_path = "src/utils/helper.ts"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        sfc_patterns = [p for p in patterns if p.pattern_type == "sfc"]
        assert len(sfc_patterns) == 0

    def test_kebab_case_name(self):
        source = b"<template><div>Test</div></template>\n<script>export default {}</script>\n"
        file_path = "src/components/user-profile-card.vue"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_nodes = _collect_pattern_nodes(patterns, NodeKind.COMPONENT)
        assert len(comp_nodes) >= 1
        assert comp_nodes[0].name == "UserProfileCard"


class TestVueCompositionAPI:
    """Test Vue Composition API pattern detection."""

    def test_ref_and_reactive(self):
        source = (
            b'import { ref, reactive } from "vue";\nconst count = ref(0);\nconst state = reactive({ name: "test" });\n'
        )
        file_path = "src/composables/useCounter.ts"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_patterns = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp_patterns) >= 1
        usages = comp_patterns[0].metadata["api_usages"]
        assert "ref" in usages
        assert "reactive" in usages

    def test_computed_and_watch(self):
        source = b'import { computed, watch, ref } from "vue";\nconst count = ref(0);\nconst doubled = computed(() => count.value * 2);\nwatch(count, (newVal) => console.log(newVal));\n'
        file_path = "src/composables/useDoubled.ts"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_patterns = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp_patterns) >= 1
        usages = comp_patterns[0].metadata["api_usages"]
        assert "computed" in usages
        assert "watch" in usages

    def test_lifecycle_hooks(self):
        source = b'import { onMounted, onUnmounted } from "vue";\nfunction setup() {\n  onMounted(() => console.log("mounted"));\n  onUnmounted(() => console.log("unmounted"));\n}\n'
        file_path = "src/composables/useLifecycle.ts"
        nodes = [_make_node(file_path, 2, NodeKind.FUNCTION, "setup", end_line=5)]
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        hook_nodes = _collect_pattern_nodes(patterns, NodeKind.HOOK)
        assert len(hook_nodes) >= 2
        hook_names = {n.name for n in hook_nodes}
        assert "onMounted" in hook_names
        assert "onUnmounted" in hook_names

    def test_define_props_and_emits(self):
        source = b'const props = defineProps<{ title: string }>();\nconst emit = defineEmits<{ (e: "update", value: string): void }>();\n'
        file_path = "src/components/MyComponent.vue"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_patterns = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp_patterns) >= 1
        usages = comp_patterns[0].metadata["api_usages"]
        assert "defineProps" in usages
        assert "defineEmits" in usages

    def test_define_component(self):
        source = b'import { defineComponent, ref } from "vue";\nexport default defineComponent({\n  setup() {\n    const count = ref(0);\n    return { count };\n  }\n});\n'
        file_path = "src/components/Counter.ts"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_patterns = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp_patterns) >= 1
        usages = comp_patterns[0].metadata["api_usages"]
        assert "defineComponent" in usages
        assert "ref" in usages

    def test_no_composition_api(self):
        source = b"export function add(a, b) { return a + b; }\n"
        file_path = "src/utils/math.ts"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        comp_patterns = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp_patterns) == 0


class TestVueOptionsAPI:
    """Test Vue Options API pattern detection."""

    def test_data_and_methods(self):
        source = b"export default {\n  data() {\n    return { count: 0 };\n  },\n  methods: {\n    increment() { this.count++; }\n  }\n};\n"
        file_path = "src/components/Counter.vue"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        opt_patterns = [p for p in patterns if p.pattern_type == "options_api"]
        assert len(opt_patterns) >= 1
        options = opt_patterns[0].metadata["options_found"]
        assert "data" in options
        assert "methods" in options

    def test_computed_and_watch_options(self):
        source = b"export default {\n  computed: {\n    doubled() { return this.count * 2; }\n  },\n  watch: {\n    count(newVal) { console.log(newVal); }\n  }\n};\n"
        file_path = "src/components/Watcher.vue"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        opt_patterns = [p for p in patterns if p.pattern_type == "options_api"]
        assert len(opt_patterns) >= 1
        options = opt_patterns[0].metadata["options_found"]
        assert "computed" in options
        assert "watch" in options

    def test_lifecycle_hooks_options(self):
        source = b'export default {\n  mounted() {\n    console.log("mounted");\n  },\n  beforeUnmount() {\n    console.log("cleanup");\n  }\n};\n'
        file_path = "src/components/Lifecycle.vue"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        opt_patterns = [p for p in patterns if p.pattern_type == "options_api"]
        assert len(opt_patterns) >= 1
        options = opt_patterns[0].metadata["options_found"]
        assert "mounted" in options
        assert "beforeUnmount" in options


class TestVueStores:
    """Test Vuex and Pinia store detection."""

    def test_pinia_define_store(self):
        source = b'import { defineStore } from "pinia";\nexport const useCounterStore = defineStore("counter", {\n  state: () => ({ count: 0 }),\n  actions: {\n    increment() { this.count++; }\n  }\n});\n'
        file_path = "src/stores/counter.ts"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        store_patterns = [p for p in patterns if p.pattern_type == "stores"]
        assert len(store_patterns) >= 1
        store_nodes = _collect_pattern_nodes(patterns, NodeKind.MODULE)
        assert len(store_nodes) >= 1
        assert store_nodes[0].metadata["store_type"] == "pinia"
        assert store_nodes[0].metadata["store_name"] == "counter"

    def test_pinia_use_store(self):
        source = b'import { useCounterStore } from "@/stores/counter";\nfunction setup() {\n  const store = useCounterStore();\n  return { store };\n}\n'
        file_path = "src/components/Counter.vue"
        nodes = [_make_node(file_path, 2, NodeKind.FUNCTION, "setup", end_line=5)]
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        store_patterns = [p for p in patterns if p.pattern_type == "stores"]
        assert len(store_patterns) >= 1
        usages = store_patterns[0].metadata["store_usages"]
        assert any(u["name"] == "Counter" and u["action"] == "use" for u in usages)

    def test_vuex_usage(self):
        source = b'import { createStore } from "vuex";\nconst store = createStore({\n  state: { count: 0 },\n  mutations: { increment(state) { state.count++; } }\n});\n'
        file_path = "src/store/index.ts"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        store_patterns = [p for p in patterns if p.pattern_type == "stores"]
        assert len(store_patterns) >= 1
        usages = store_patterns[0].metadata["store_usages"]
        assert any(u["type"] == "vuex" for u in usages)

    def test_no_store_usage(self):
        source = b"export function add(a, b) { return a + b; }\n"
        file_path = "src/utils/math.ts"
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, [], [])
        store_patterns = [p for p in patterns if p.pattern_type == "stores"]
        assert len(store_patterns) == 0


class TestVueEdges:
    """Test that Vue detector creates appropriate edges."""

    def test_sfc_contains_edges(self):
        source = b"<template><div>Test</div></template>\n<script>\nexport default {\n  methods: { doSomething() {} }\n};\n</script>\n"
        file_path = "src/components/Test.vue"
        nodes = [_make_node(file_path, 4, NodeKind.FUNCTION, "doSomething")]
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        contains_edges = _collect_pattern_edges(patterns, EdgeKind.CONTAINS)
        assert len(contains_edges) >= 1

    def test_lifecycle_hook_uses_hook_edge(self):
        source = b'import { onMounted } from "vue";\nfunction setup() {\n  onMounted(() => console.log("ready"));\n}\n'
        file_path = "src/composables/useSetup.ts"
        nodes = [_make_node(file_path, 2, NodeKind.FUNCTION, "setup", end_line=4)]
        detector = VueDetector()
        patterns = detector.detect(file_path, None, source, nodes, [])
        hook_edges = _collect_pattern_edges(patterns, EdgeKind.USES_HOOK)
        assert len(hook_edges) >= 1
        assert hook_edges[0].source_id == nodes[0].id
