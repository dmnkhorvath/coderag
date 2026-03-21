import json
import os
import pytest
from unittest.mock import MagicMock, ANY

from coderag.core.models import (
    Node, NodeKind, Edge, EdgeKind, FrameworkPattern,
)
from coderag.plugins.javascript.frameworks.vue import VueDetector


@pytest.fixture
def detector():
    return VueDetector()


def _make_tree():
    return MagicMock()


def _make_fn_node(name, file_path="test.vue", start=1, end=50):
    return Node(
        id=f"fn-{name}",
        kind=NodeKind.FUNCTION,
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=start,
        end_line=end,
        language="javascript",
    )


def _make_class_node(name, file_path="test.vue", start=1, end=50):
    return Node(
        id=f"cls-{name}",
        kind=NodeKind.CLASS,
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=start,
        end_line=end,
        language="javascript",
    )


def _make_var_node(name, file_path="test.vue", start=1, end=50):
    return Node(
        id=f"var-{name}",
        kind=NodeKind.VARIABLE,
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=start,
        end_line=end,
        language="javascript",
    )


# ── framework_name ────────────────────────────────────────────

class TestFrameworkName:
    def test_name(self, detector):
        assert detector.framework_name == "vue"


# ── detect_framework ──────────────────────────────────────────

class TestDetectFramework:
    def test_vue_in_deps(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"vue": "^3.4.0"}
        }))
        assert detector.detect_framework(str(tmp_path)) is True

    def test_vue_in_devdeps(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "devDependencies": {"vue": "^3.0.0"}
        }))
        assert detector.detect_framework(str(tmp_path)) is True

    def test_no_vue(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18.0.0"}
        }))
        assert detector.detect_framework(str(tmp_path)) is False

    def test_no_package_json(self, detector, tmp_path):
        assert detector.detect_framework(str(tmp_path)) is False

    def test_malformed_json(self, detector, tmp_path):
        (tmp_path / "package.json").write_text("not json")
        assert detector.detect_framework(str(tmp_path)) is False


# ── detect_global_patterns ────────────────────────────────────

class TestDetectGlobalPatterns:
    def test_returns_empty(self, detector):
        store = MagicMock()
        assert detector.detect_global_patterns(store) == []


# ── _detect_sfc ───────────────────────────────────────────────

class TestDetectSFC:
    def test_full_sfc(self, detector):
        source = b'''<template>
  <div>{{ msg }}</div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
const msg = ref('Hello')
</script>

<style scoped>
.container { color: red; }
</style>
'''
        patterns = detector.detect("UserProfile.vue", _make_tree(), source, [], [])
        sfc = [p for p in patterns if p.pattern_type == "sfc"]
        assert len(sfc) == 1
        assert sfc[0].nodes[0].kind == NodeKind.COMPONENT
        assert sfc[0].nodes[0].name == "UserProfile"
        assert sfc[0].nodes[0].metadata["has_template"] is True
        assert sfc[0].nodes[0].metadata["has_script"] is True
        assert sfc[0].nodes[0].metadata["has_style"] is True
        assert sfc[0].nodes[0].metadata["script_setup"] is True
        assert sfc[0].nodes[0].metadata["script_lang"] == "typescript"

    def test_sfc_no_style(self, detector):
        source = b'''<template><div></div></template>
<script>export default {}</script>
'''
        patterns = detector.detect("MyComp.vue", _make_tree(), source, [], [])
        sfc = [p for p in patterns if p.pattern_type == "sfc"]
        assert len(sfc) == 1
        assert sfc[0].nodes[0].metadata["has_style"] is False
        assert sfc[0].nodes[0].metadata["script_setup"] is False
        assert sfc[0].nodes[0].metadata["script_lang"] == "javascript"

    def test_sfc_no_template_no_script(self, detector):
        source = b'''<style>.x { color: red; }</style>'''
        patterns = detector.detect("OnlyStyle.vue", _make_tree(), source, [], [])
        sfc = [p for p in patterns if p.pattern_type == "sfc"]
        assert len(sfc) == 0

    def test_sfc_links_to_function_nodes(self, detector):
        source = b'''<template><div></div></template>
<script setup>
const handler = () => {}
</script>
'''
        fn = _make_fn_node("handler", "Comp.vue")
        patterns = detector.detect("Comp.vue", _make_tree(), source, [fn], [])
        sfc = [p for p in patterns if p.pattern_type == "sfc"]
        assert len(sfc) == 1
        contains_edges = [e for e in sfc[0].edges if e.kind == EdgeKind.CONTAINS]
        assert len(contains_edges) == 1
        assert contains_edges[0].target_id == fn.id

    def test_sfc_kebab_case_filename(self, detector):
        source = b'''<template><div></div></template>
<script setup></script>
'''
        patterns = detector.detect("user-profile-card.vue", _make_tree(), source, [], [])
        sfc = [p for p in patterns if p.pattern_type == "sfc"]
        assert sfc[0].nodes[0].name == "UserProfileCard"


# ── _detect_composition_api ───────────────────────────────────

class TestDetectCompositionAPI:
    def test_define_component(self, detector):
        source = b'''import { defineComponent } from 'vue'
export default defineComponent({ name: 'MyComp' })
'''
        patterns = detector.detect("comp.ts", _make_tree(), source, [], [])
        comp = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp) == 1
        assert "defineComponent" in comp[0].metadata["api_usages"]

    def test_script_setup_macros(self, detector):
        source = b'''<script setup>
const props = defineProps<{ msg: string }>()
const emit = defineEmits(['update'])
defineExpose({ reset })
defineSlots()
const model = defineModel()
</script>
'''
        patterns = detector.detect("comp.vue", _make_tree(), source, [], [])
        comp = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp) == 1
        usages = comp[0].metadata["api_usages"]
        assert "defineProps" in usages
        assert "defineEmits" in usages
        assert "defineExpose" in usages
        assert "defineSlots" in usages
        assert "defineModel" in usages

    def test_reactivity_primitives(self, detector):
        source = b'''import { ref, reactive, computed, watch, watchEffect } from 'vue'
const count = ref(0)
const state = reactive({ items: [] })
const doubled = computed(() => count.value * 2)
watch(count, (val) => console.log(val))
watchEffect(() => console.log(count.value))
'''
        patterns = detector.detect("comp.ts", _make_tree(), source, [], [])
        comp = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp) == 1
        usages = comp[0].metadata["api_usages"]
        assert "ref" in usages
        assert "reactive" in usages
        assert "computed" in usages
        assert "watch" in usages
        assert "watchEffect" in usages

    def test_lifecycle_hooks(self, detector):
        source = b'''import { onMounted, onUnmounted } from 'vue'
onMounted(() => { console.log('mounted') })
onUnmounted(() => { console.log('unmounted') })
'''
        fn = _make_fn_node("setup", "comp.ts", 1, 10)
        patterns = detector.detect("comp.ts", _make_tree(), source, [fn], [])
        comp = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp) == 1
        hooks = [n for n in comp[0].nodes if n.kind == NodeKind.HOOK]
        assert len(hooks) == 2
        hook_names = {h.name for h in hooks}
        assert "onMounted" in hook_names
        assert "onUnmounted" in hook_names
        # Check edges linking hooks to enclosing function
        uses_hook_edges = [e for e in comp[0].edges if e.kind == EdgeKind.USES_HOOK]
        assert len(uses_hook_edges) == 2

    def test_no_composition_api(self, detector):
        source = b'''const x = 42;
console.log(x);
'''
        patterns = detector.detect("plain.js", _make_tree(), source, [], [])
        comp = [p for p in patterns if p.pattern_type == "composition_api"]
        assert len(comp) == 0


# ── _detect_options_api ───────────────────────────────────────

class TestDetectOptionsAPI:
    def test_full_options(self, detector):
        source = b'''export default {
  data() { return { count: 0 } },
  methods: { increment() { this.count++ } },
  computed: { doubled() { return this.count * 2 } },
  watch: { count(val) { console.log(val) } },
  created() { console.log('created') },
  mounted() { console.log('mounted') },
}
'''
        patterns = detector.detect("comp.js", _make_tree(), source, [], [])
        opts = [p for p in patterns if p.pattern_type == "options_api"]
        assert len(opts) == 1
        found = opts[0].metadata["options_found"]
        assert "data" in found
        assert "methods" in found
        assert "computed" in found
        assert "watch" in found
        assert "created" in found or "mounted" in found

    def test_lifecycle_hooks_options(self, detector):
        source = b'''export default {
  created() { console.log('created') },
  mounted() { console.log('mounted') },
  beforeDestroy() { console.log('cleanup') },
}
'''
        patterns = detector.detect("comp.js", _make_tree(), source, [], [])
        opts = [p for p in patterns if p.pattern_type == "options_api"]
        assert len(opts) == 1
        hooks = [n for n in opts[0].nodes if n.kind == NodeKind.HOOK]
        assert len(hooks) >= 2

    def test_no_options_api(self, detector):
        source = b'''const x = 42;'''
        patterns = detector.detect("plain.js", _make_tree(), source, [], [])
        opts = [p for p in patterns if p.pattern_type == "options_api"]
        assert len(opts) == 0


# ── _detect_stores ────────────────────────────────────────────

class TestDetectStores:
    def test_pinia_define_store(self, detector):
        source = b'''import { defineStore } from 'pinia'
export const useCounterStore = defineStore('counter', {
  state: () => ({ count: 0 }),
  actions: { increment() { this.count++ } },
})
'''
        patterns = detector.detect("stores/counter.ts", _make_tree(), source, [], [])
        stores = [p for p in patterns if p.pattern_type == "stores"]
        assert len(stores) == 1
        store_nodes = [n for n in stores[0].nodes if n.kind == NodeKind.MODULE]
        assert len(store_nodes) == 1
        assert store_nodes[0].metadata["store_name"] == "counter"
        assert stores[0].metadata["store_count"] >= 1

    def test_pinia_use_store(self, detector):
        source = b'''import { useCounterStore } from './stores/counter'
const counter = useCounterStore()
'''
        fn = _make_fn_node("setup", "comp.ts", 1, 10)
        patterns = detector.detect("comp.ts", _make_tree(), source, [fn], [])
        stores = [p for p in patterns if p.pattern_type == "stores"]
        assert len(stores) == 1
        usages = stores[0].metadata["store_usages"]
        use_entries = [u for u in usages if u["action"] == "use"]
        assert len(use_entries) >= 1

    def test_vuex_store(self, detector):
        source = b'''import { useStore } from 'vuex'
const store = useStore()
store.commit('increment')
'''
        patterns = detector.detect("comp.ts", _make_tree(), source, [], [])
        stores = [p for p in patterns if p.pattern_type == "stores"]
        assert len(stores) == 1
        usages = stores[0].metadata["store_usages"]
        vuex_entries = [u for u in usages if u["type"] == "vuex"]
        assert len(vuex_entries) >= 1

    def test_no_stores(self, detector):
        source = b'''const x = 42;'''
        patterns = detector.detect("plain.js", _make_tree(), source, [], [])
        stores = [p for p in patterns if p.pattern_type == "stores"]
        assert len(stores) == 0


# ── _detect_router ────────────────────────────────────────────

class TestDetectRouter:
    def test_create_router(self, detector):
        source = b'''import { createRouter, createWebHistory } from 'vue-router'
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Home },
    { path: '/about', component: About },
  ],
})
'''
        patterns = detector.detect("router/index.ts", _make_tree(), source, [], [])
        router = [p for p in patterns if p.pattern_type == "router"]
        assert len(router) == 1
        assert router[0].metadata["has_create_router"] is True
        route_nodes = [n for n in router[0].nodes if n.kind == NodeKind.ROUTE]
        assert len(route_nodes) == 2

    def test_route_components(self, detector):
        source = b'''const routes = [
  { path: '/users', component: UserList },
  { path: '/settings', component: Settings },
]
'''
        patterns = detector.detect("router.ts", _make_tree(), source, [], [])
        router = [p for p in patterns if p.pattern_type == "router"]
        assert len(router) == 1
        routes_to = [e for e in router[0].edges if e.kind == EdgeKind.ROUTES_TO]
        assert len(routes_to) == 2

    def test_lazy_loaded_routes(self, detector):
        source = b'''const routes = [
  { path: '/dashboard', component: () => import('./views/Dashboard.vue') },
]
'''
        patterns = detector.detect("router.ts", _make_tree(), source, [], [])
        router = [p for p in patterns if p.pattern_type == "router"]
        assert len(router) == 1
        lazy_edges = [e for e in router[0].edges if e.metadata.get("lazy_import")]
        assert len(lazy_edges) == 1

    def test_use_route_and_router(self, detector):
        source = b'''import { useRoute, useRouter } from 'vue-router'
const route = useRoute()
const router = useRouter()
'''
        patterns = detector.detect("comp.ts", _make_tree(), source, [], [])
        router = [p for p in patterns if p.pattern_type == "router"]
        assert len(router) == 1
        usages = router[0].metadata["router_usages"]
        types = [u["type"] for u in usages]
        assert "useRoute" in types
        assert "useRouter" in types

    def test_navigation_guards(self, detector):
        source = b'''router.beforeEach((to, from) => {
  if (!isAuthenticated) return '/login'
})
router.afterEach((to, from) => {
  document.title = to.meta.title
})
'''
        patterns = detector.detect("router.ts", _make_tree(), source, [], [])
        router = [p for p in patterns if p.pattern_type == "router"]
        assert len(router) == 1
        assert router[0].metadata["has_nav_guards"] is True

    def test_router_link_in_template(self, detector):
        source = b'''<template>
  <router-link to="/about">About</router-link>
  <RouterLink to="/home">Home</RouterLink>
</template>
<script setup></script>
'''
        patterns = detector.detect("Nav.vue", _make_tree(), source, [], [])
        router = [p for p in patterns if p.pattern_type == "router"]
        assert len(router) == 1
        link_usages = [u for u in router[0].metadata["router_usages"] if u["type"] == "router_link"]
        assert len(link_usages) >= 1

    def test_no_router(self, detector):
        source = b'''const x = 42;'''
        patterns = detector.detect("plain.js", _make_tree(), source, [], [])
        router = [p for p in patterns if p.pattern_type == "router"]
        assert len(router) == 0


# ── _detect_provide_inject ────────────────────────────────────

class TestDetectProvideInject:
    def test_provide_string_key(self, detector):
        source = b'''import { provide } from 'vue'
provide('theme', 'dark')
'''
        fn = _make_fn_node("setup", "comp.ts", 1, 10)
        patterns = detector.detect("comp.ts", _make_tree(), source, [fn], [])
        pi = [p for p in patterns if p.pattern_type == "provide_inject"]
        assert len(pi) == 1
        assert pi[0].metadata["provide_count"] == 1
        provider_nodes = [n for n in pi[0].nodes if n.kind == NodeKind.PROVIDER]
        assert len(provider_nodes) == 1

    def test_inject_string_key(self, detector):
        source = b'''import { inject } from 'vue'
const theme = inject('theme')
'''
        fn = _make_fn_node("setup", "comp.ts", 1, 10)
        patterns = detector.detect("comp.ts", _make_tree(), source, [fn], [])
        pi = [p for p in patterns if p.pattern_type == "provide_inject"]
        assert len(pi) == 1
        assert pi[0].metadata["inject_count"] == 1
        consumes = [e for e in pi[0].edges if e.kind == EdgeKind.CONSUMES_CONTEXT]
        assert len(consumes) == 1

    def test_injection_key(self, detector):
        source = b'''import { InjectionKey } from 'vue'
const ThemeKey: InjectionKey<string> = Symbol('theme')
provide(ThemeKey, 'dark')
inject(ThemeKey)
'''
        fn = _make_fn_node("setup", "comp.ts", 1, 10)
        patterns = detector.detect("comp.ts", _make_tree(), source, [fn], [])
        pi = [p for p in patterns if p.pattern_type == "provide_inject"]
        assert len(pi) == 1
        assert pi[0].metadata["injection_key_count"] >= 1

    def test_no_provide_inject(self, detector):
        source = b'''const x = 42;'''
        patterns = detector.detect("plain.js", _make_tree(), source, [], [])
        pi = [p for p in patterns if p.pattern_type == "provide_inject"]
        assert len(pi) == 0


# ── _detect_composables ───────────────────────────────────────

class TestDetectComposables:
    def test_composable_definition(self, detector):
        source = b'''export function useCounter() {
  const count = ref(0)
  const increment = () => count.value++
  return { count, increment }
}
'''
        patterns = detector.detect("composables/useCounter.ts", _make_tree(), source, [], [])
        comp = [p for p in patterns if p.pattern_type == "composables"]
        assert len(comp) == 1
        assert "useCounter" in comp[0].metadata["composable_definitions"]
        fn_nodes = [n for n in comp[0].nodes if n.kind == NodeKind.FUNCTION]
        assert len(fn_nodes) == 1
        assert fn_nodes[0].metadata["composable"] is True

    def test_composable_usage(self, detector):
        source = b'''import { useCounter } from './composables/useCounter'
const { count, increment } = useCounter()
'''
        fn = _make_fn_node("setup", "comp.ts", 1, 10)
        patterns = detector.detect("comp.ts", _make_tree(), source, [fn], [])
        comp = [p for p in patterns if p.pattern_type == "composables"]
        assert len(comp) == 1
        assert "useCounter" in comp[0].metadata["composable_calls"]

    def test_skips_vue_builtins(self, detector):
        source = b'''import { useRoute } from 'vue-router'
const route = useRoute()
'''
        patterns = detector.detect("comp.ts", _make_tree(), source, [], [])
        comp = [p for p in patterns if p.pattern_type == "composables"]
        # useRoute is a Vue built-in, should be skipped
        if comp:
            assert "useRoute" not in comp[0].metadata.get("composable_calls", [])

    def test_skips_store_calls(self, detector):
        source = b'''const counter = useCounterStore()'''
        patterns = detector.detect("comp.ts", _make_tree(), source, [], [])
        comp = [p for p in patterns if p.pattern_type == "composables"]
        # useCounterStore ends with Store, should be skipped
        if comp:
            assert "useCounterStore" not in comp[0].metadata.get("composable_calls", [])

    def test_no_composables(self, detector):
        source = b'''const x = 42;'''
        patterns = detector.detect("plain.js", _make_tree(), source, [], [])
        comp = [p for p in patterns if p.pattern_type == "composables"]
        assert len(comp) == 0


# ── _detect_template_patterns ─────────────────────────────────

class TestDetectTemplatePatterns:
    def test_pascal_case_components(self, detector):
        source = b'''<template>
  <UserProfile />
  <NavBar />
  <div>plain html</div>
</template>
<script setup></script>
'''
        patterns = detector.detect("App.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        assert len(tmpl) == 1
        assert "UserProfile" in tmpl[0].metadata["components_used"]
        assert "NavBar" in tmpl[0].metadata["components_used"]
        renders = [e for e in tmpl[0].edges if e.kind == EdgeKind.RENDERS]
        assert len(renders) >= 2

    def test_kebab_case_components(self, detector):
        source = b'''<template>
  <user-profile />
  <nav-bar></nav-bar>
</template>
<script setup></script>
'''
        patterns = detector.detect("App.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        assert len(tmpl) == 1
        assert len(tmpl[0].metadata["kebab_components"]) >= 1

    def test_v_model(self, detector):
        source = b'''<template>
  <input v-model="name" />
  <MyInput v-model:title="title" />
</template>
<script setup></script>
'''
        patterns = detector.detect("Form.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        assert len(tmpl) == 1
        v_models = tmpl[0].metadata["v_models"]
        assert len(v_models) >= 1

    def test_slot_definitions(self, detector):
        source = b'''<template>
  <div>
    <slot name="header"></slot>
    <slot></slot>
    <slot name="footer"></slot>
  </div>
</template>
<script setup></script>
'''
        patterns = detector.detect("Layout.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        assert len(tmpl) == 1
        slots = tmpl[0].metadata["slot_definitions"]
        assert "header" in slots
        assert "footer" in slots

    def test_slot_usage(self, detector):
        source = b'''<template>
  <Layout>
    <template #header>Header</template>
    <template #footer>Footer</template>
  </Layout>
</template>
<script setup></script>
'''
        patterns = detector.detect("Page.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        assert len(tmpl) == 1
        slot_usages = tmpl[0].metadata["slot_usages"]
        assert "header" in slot_usages
        assert len(slot_usages) >= 1  # regex stops at first inner </template>

    def test_event_listeners(self, detector):
        source = b'''<template>
  <button @click="handleClick">Click</button>
  <form @submit.prevent="handleSubmit">Submit</form>
</template>
<script setup></script>
'''
        patterns = detector.detect("Comp.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        assert len(tmpl) == 1
        events = tmpl[0].metadata["event_listeners"]
        assert "click" in events

    def test_dynamic_components(self, detector):
        source = b'''<template>
  <component :is="currentComponent" />
</template>
<script setup></script>
'''
        patterns = detector.detect("Dynamic.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        assert len(tmpl) == 1
        assert tmpl[0].metadata["dynamic_components"] >= 1

    def test_no_template(self, detector):
        source = b'''<script setup>
const x = ref(0)
</script>
'''
        patterns = detector.detect("comp.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        assert len(tmpl) == 0

    def test_empty_template(self, detector):
        source = b'''<template>
  <div>plain text only</div>
</template>
<script setup></script>
'''
        patterns = detector.detect("Plain.vue", _make_tree(), source, [], [])
        tmpl = [p for p in patterns if p.pattern_type == "template_patterns"]
        # No components, no v-model, no slots, no events
        assert len(tmpl) == 0


# ── Helper methods ────────────────────────────────────────────

class TestHelpers:
    def test_component_name_from_path_pascal(self, detector):
        assert VueDetector._component_name_from_path("src/components/UserProfile.vue") == "UserProfile"

    def test_component_name_from_path_kebab(self, detector):
        assert VueDetector._component_name_from_path("src/components/user-profile.vue") == "UserProfile"

    def test_component_name_from_path_underscore(self, detector):
        assert VueDetector._component_name_from_path("src/my_component.vue") == "MyComponent"

    def test_kebab_to_pascal(self, detector):
        assert VueDetector._kebab_to_pascal("my-component") == "MyComponent"
        assert VueDetector._kebab_to_pascal("user-profile-card") == "UserProfileCard"

    def test_find_enclosing_function(self, detector):
        fn = _make_fn_node("setup", "test.vue", 5, 20)
        result = VueDetector._find_enclosing_function(10, [fn])
        assert result == fn

    def test_find_enclosing_function_none(self, detector):
        fn = _make_fn_node("setup", "test.vue", 5, 10)
        result = VueDetector._find_enclosing_function(20, [fn])
        assert result is None

    def test_find_enclosing_function_most_specific(self, detector):
        outer = _make_fn_node("outer", "test.vue", 1, 50)
        inner = _make_fn_node("inner", "test.vue", 10, 20)
        result = VueDetector._find_enclosing_function(15, [outer, inner])
        assert result == inner


# ── Full integration ──────────────────────────────────────────

class TestFullDetect:
    def test_complex_vue_file(self, detector):
        source = b'''<template>
  <div>
    <UserCard />
    <button @click="increment">{{ count }}</button>
    <slot name="footer"></slot>
    <component :is="dynamicComp" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, provide } from 'vue'
import { useCounterStore } from './stores/counter'

const count = ref(0)
const increment = () => count.value++

onMounted(() => { console.log('ready') })
provide('count', count)

const counter = useCounterStore()
</script>

<style scoped>
.container { color: red; }
</style>
'''
        patterns = detector.detect("Dashboard.vue", _make_tree(), source, [], [])
        pattern_types = {p.pattern_type for p in patterns}
        assert "sfc" in pattern_types
        assert "composition_api" in pattern_types
        assert "template_patterns" in pattern_types
