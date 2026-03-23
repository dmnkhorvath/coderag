"""Tests for enhanced Vue detector edge types.

Covers all 29 new/renamed edge types across 9 categories.
"""

import pytest

from coderag.core.models import Edge, EdgeKind, Node, NodeKind, generate_node_id
from coderag.plugins.javascript.frameworks.vue import VueDetector

# ── Helpers ────────────────────────────────────────────────────


def _make_fn_node(
    name: str,
    file_path: str = "test.vue",
    start: int = 1,
    end: int = 50,
) -> Node:
    return Node(
        id=generate_node_id(file_path, start, NodeKind.FUNCTION, name),
        kind=NodeKind.FUNCTION,
        name=name,
        qualified_name=name,
        file_path=file_path,
        start_line=start,
        end_line=end,
        language="javascript",
    )


def _collect_edges(patterns, vue_edge_type: str) -> list[Edge]:
    """Collect all edges with a specific vue_edge_type from patterns."""
    edges = []
    for p in patterns:
        for e in p.edges:
            if e.metadata.get("vue_edge_type") == vue_edge_type:
                edges.append(e)
    return edges


def _collect_all_edge_types(patterns) -> set[str]:
    """Collect all vue_edge_type values from patterns."""
    types = set()
    for p in patterns:
        for e in p.edges:
            t = e.metadata.get("vue_edge_type")
            if t:
                types.add(t)
    return types


def _collect_pattern_nodes(patterns, kind: NodeKind) -> list[Node]:
    nodes = []
    for p in patterns:
        for n in p.nodes:
            if n.kind == kind:
                nodes.append(n)
    return nodes


@pytest.fixture
def detector():
    return VueDetector()


# ══════════════════════════════════════════════════════════════
# Category 1: Component Relationships
# ══════════════════════════════════════════════════════════════


class TestComponentRelationships:
    """Tests for component import, registration, rendering, extends, mixins."""

    def test_vue_imports_component(self, detector):
        source = b"""<script setup>
import UserCard from './UserCard.vue'
import ProfileHeader from '../components/ProfileHeader.vue'
</script>
<template><div></div></template>
"""
        patterns = detector.detect("src/components/Page.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_imports_component")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.IMPORTS for e in edges)
        assert all(e.confidence == 0.95 for e in edges)
        names = {e.metadata["component_name"] for e in edges}
        assert "UserCard" in names
        assert "ProfileHeader" in names

    def test_vue_registers_component(self, detector):
        source = b"""export default {
  components: { ChildComp, OtherComp, ThirdOne },
  data() { return {} }
}
"""
        patterns = detector.detect("src/components/Parent.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_registers_component")
        assert len(edges) >= 3
        assert all(e.kind == EdgeKind.CONTAINS for e in edges)
        names = {e.metadata["component_name"] for e in edges}
        assert "ChildComp" in names
        assert "OtherComp" in names
        assert "ThirdOne" in names

    def test_vue_renders_component(self, detector):
        source = b"""<template>
  <div>
    <UserCard />
    <ProfileHeader title="test" />
  </div>
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Page.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_renders_component")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.RENDERS for e in edges)
        names = {e.metadata["component_name"] for e in edges}
        assert "UserCard" in names
        assert "ProfileHeader" in names

    def test_vue_extends_component(self, detector):
        source = b"""import BaseComponent from './BaseComponent.vue'
export default {
  extends: BaseComponent,
  data() { return { extra: true } }
}
"""
        patterns = detector.detect("src/components/Extended.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_extends_component")
        assert len(edges) >= 1
        assert edges[0].kind == EdgeKind.EXTENDS
        assert edges[0].confidence == 0.90

    def test_vue_uses_mixin(self, detector):
        source = b"""export default {
  mixins: [MixinA, MixinB],
  data() { return {} }
}
"""
        patterns = detector.detect("src/components/Mixed.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_uses_mixin")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.DEPENDS_ON for e in edges)
        names = {e.metadata["mixin_name"] for e in edges}
        assert "MixinA" in names
        assert "MixinB" in names


# ══════════════════════════════════════════════════════════════
# Category 2: Props & Events
# ══════════════════════════════════════════════════════════════


class TestPropsAndEvents:
    """Tests for defineProps, defineEmits, prop passing, event listening, v-model."""

    def test_vue_defines_prop_array(self, detector):
        source = b"""<script setup>
const props = defineProps(['title', 'count', 'isActive'])
</script>
<template><div></div></template>
"""
        patterns = detector.detect("src/components/MyComp.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_defines_prop")
        assert len(edges) >= 3
        assert all(e.kind == EdgeKind.CONTAINS for e in edges)
        prop_names = {e.metadata["prop_name"] for e in edges}
        assert "title" in prop_names
        assert "count" in prop_names

    def test_vue_defines_prop_generic(self, detector):
        source = b"""<script setup lang="ts">
const props = defineProps<{ title: string; count: number }>()
</script>
<template><div></div></template>
"""
        patterns = detector.detect("src/components/MyComp.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_defines_prop")
        # Generic style may detect fewer individual props but should detect at least the defineProps
        assert len(edges) >= 1

    def test_vue_emits_event_array(self, detector):
        source = b"""<script setup>
const emit = defineEmits(['update', 'delete', 'refresh'])
</script>
<template><div></div></template>
"""
        patterns = detector.detect("src/components/MyComp.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_emits_event")
        assert len(edges) >= 3
        assert all(e.kind == EdgeKind.DISPATCHES_EVENT for e in edges)
        event_names = {e.metadata["event_name"] for e in edges}
        assert "update" in event_names
        assert "delete" in event_names

    def test_vue_passes_prop(self, detector):
        source = b"""<template>
  <ChildComp :title="myTitle" :count="total" />
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Parent.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_passes_prop")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.PASSES_PROP for e in edges)
        props = {e.metadata["prop_name"] for e in edges}
        assert "title" in props
        assert "count" in props

    def test_vue_listens_event(self, detector):
        source = b"""<template>
  <ChildComp @update="onUpdate" @delete="onDelete" />
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Parent.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_listens_event")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.LISTENS_TO for e in edges)
        events = {e.metadata["event_name"] for e in edges}
        assert "update" in events
        assert "delete" in events

    def test_vue_v_model_binds(self, detector):
        source = b"""<template>
  <CustomInput v-model="username" />
  <DatePicker v-model:date="selectedDate" />
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Form.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_v_model_binds")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.DEPENDS_ON for e in edges)


# ══════════════════════════════════════════════════════════════
# Category 3: Provide/Inject
# ══════════════════════════════════════════════════════════════


class TestProvideInject:
    """Tests for renamed provide/inject edge types."""

    def test_vue_provides(self, detector):
        source = b"""import { provide } from 'vue'
function setup() {
  provide('theme', 'dark')
  provide('user', currentUser)
}
"""
        nodes = [_make_fn_node("setup", "src/App.vue", 2, 5)]
        patterns = detector.detect("src/App.vue", None, source, nodes, [])
        edges = _collect_edges(patterns, "vue_provides")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.PROVIDES_CONTEXT for e in edges)
        keys = {e.metadata["provide_key"] for e in edges}
        assert "theme" in keys
        assert "user" in keys

    def test_vue_injects(self, detector):
        source = b"""import { inject } from 'vue'
function setup() {
  const theme = inject('theme')
  const user = inject('user')
}
"""
        nodes = [_make_fn_node("setup", "src/Child.vue", 2, 5)]
        patterns = detector.detect("src/Child.vue", None, source, nodes, [])
        edges = _collect_edges(patterns, "vue_injects")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.CONSUMES_CONTEXT for e in edges)
        keys = {e.metadata["inject_key"] for e in edges}
        assert "theme" in keys
        assert "user" in keys


# ══════════════════════════════════════════════════════════════
# Category 4: Composables & Stores
# ══════════════════════════════════════════════════════════════


class TestComposablesAndStores:
    """Tests for composable and store edge types."""

    def test_vue_uses_composable(self, detector):
        source = b"""import { useAuth } from './composables/useAuth'
function setup() {
  const { user, login } = useAuth()
  const { items } = useCart()
}
"""
        nodes = [_make_fn_node("setup", "src/App.vue", 2, 5)]
        patterns = detector.detect("src/App.vue", None, source, nodes, [])
        edges = _collect_edges(patterns, "vue_uses_composable")
        assert len(edges) >= 1
        assert all(e.kind == EdgeKind.CALLS for e in edges)

    def test_vue_uses_store(self, detector):
        source = b"""import { useUserStore } from './stores/user'
function setup() {
  const userStore = useUserStore()
  const cartStore = useCartStore()
}
"""
        nodes = [_make_fn_node("setup", "src/App.vue", 2, 5)]
        patterns = detector.detect("src/App.vue", None, source, nodes, [])
        edges = _collect_edges(patterns, "vue_uses_store")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.CALLS for e in edges)


# ══════════════════════════════════════════════════════════════
# Category 5: Routing
# ══════════════════════════════════════════════════════════════


class TestRouting:
    """Tests for routing edge types."""

    def test_vue_routes_to(self, detector):
        source = b"""import { createRouter } from 'vue-router'
const routes = [
  { path: '/home', component: HomeView },
  { path: '/about', component: AboutView },
]
"""
        patterns = detector.detect("src/router/index.ts", None, source, [], [])
        edges = _collect_edges(patterns, "vue_routes_to")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.ROUTES_TO for e in edges)

    def test_vue_lazy_loads(self, detector):
        source = b"""import { createRouter } from 'vue-router'
const routes = [
  { path: '/home', component: () => import('./views/Home.vue') },
  { path: '/about', component: () => import('./views/About.vue') },
]
"""
        patterns = detector.detect("src/router/index.ts", None, source, [], [])
        edges = _collect_edges(patterns, "vue_lazy_loads")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.DYNAMIC_IMPORTS for e in edges)
        assert all(e.confidence == 0.85 for e in edges)

    def test_vue_guards_route(self, detector):
        source = b"""import { createRouter } from 'vue-router'
const router = createRouter({ history: createWebHistory(), routes: [] })
router.beforeEach((to, from, next) => {
  if (!isAuthenticated) next('/login')
  else next()
})
router.afterEach((to, from) => {
  document.title = to.meta.title
})
"""
        patterns = detector.detect("src/router/index.ts", None, source, [], [])
        edges = _collect_edges(patterns, "vue_guards_route")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.DEPENDS_ON for e in edges)
        guard_names = {e.metadata["guard_name"] for e in edges}
        assert "beforeEach" in guard_names
        assert "afterEach" in guard_names


# ══════════════════════════════════════════════════════════════
# Category 6: Slots
# ══════════════════════════════════════════════════════════════


class TestSlots:
    """Tests for slot definition and usage edge types."""

    def test_vue_slot_defines(self, detector):
        source = b"""<template>
  <div>
    <slot></slot>
    <slot name="header"></slot>
    <slot name="footer"></slot>
  </div>
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Layout.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_slot_defines")
        assert len(edges) >= 2  # at least named slots
        assert all(e.kind == EdgeKind.CONTAINS for e in edges)

    def test_vue_slot_fills(self, detector):
        source = b"""<template>
  <Layout>
    <template #header>
      <h1>Title</h1>
    </template>
    <template #footer>
      <p>Footer</p>
    </template>
  </Layout>
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Page.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_slot_fills")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.RENDERS for e in edges)
        slot_names = {e.metadata["slot_name"] for e in edges}
        assert "header" in slot_names
        assert "footer" in slot_names


# ══════════════════════════════════════════════════════════════
# Category 7: Directives & Dynamic
# ══════════════════════════════════════════════════════════════


class TestDirectivesAndDynamic:
    """Tests for custom directives, teleport, and dynamic components."""

    def test_vue_uses_directive(self, detector):
        source = b"""<template>
  <div v-focus v-tooltip="msg" v-if="show">
    <input v-mask="pattern" />
  </div>
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Form.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_uses_directive")
        # Should detect v-focus, v-tooltip, v-mask but NOT v-if (built-in)
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.DEPENDS_ON for e in edges)
        directive_names = {e.metadata["directive_name"] for e in edges}
        assert "focus" in directive_names or "v-focus" in directive_names
        # v-if should NOT be in the list
        for e in edges:
            assert e.metadata["directive_name"] not in ("if", "for", "show", "model", "bind", "on")

    def test_vue_teleports_to(self, detector):
        source = b"""<template>
  <div>
    <Teleport to="#modal">
      <div class="modal">Content</div>
    </Teleport>
    <Teleport to="body">
      <div class="overlay"></div>
    </Teleport>
  </div>
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Modal.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_teleports_to")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.DEPENDS_ON for e in edges)
        targets = {e.metadata["teleport_target"] for e in edges}
        assert "#modal" in targets
        assert "body" in targets

    def test_vue_dynamic_component(self, detector):
        source = b"""<template>
  <component :is="currentComponent" />
  <component :is="tabComponent" />
</template>
<script setup></script>
"""
        patterns = detector.detect("src/components/Dynamic.vue", None, source, [], [])
        edges = _collect_edges(patterns, "vue_dynamic_component")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.RENDERS for e in edges)
        assert all(e.confidence == 0.70 for e in edges)


# ══════════════════════════════════════════════════════════════
# Category 8: Store Internals
# ══════════════════════════════════════════════════════════════


class TestStoreInternals:
    """Tests for inter-store dependencies and API calls."""

    def test_store_depends_on(self, detector):
        source = b"""import { defineStore } from 'pinia'
export const useCartStore = defineStore('cart', {
  actions: {
    checkout() {
      const userStore = useUserStore()
      const paymentStore = usePaymentStore()
    }
  }
})
"""
        patterns = detector.detect("src/stores/cart.ts", None, source, [], [])
        edges = _collect_edges(patterns, "store_depends_on")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.DEPENDS_ON for e in edges)
        stores = {e.metadata["target_store"] for e in edges}
        assert "User" in stores or "user" in stores.union({e.metadata.get("target_store", "").lower() for e in edges})

    def test_store_fetches_api(self, detector):
        source = b"""import { defineStore } from 'pinia'
export const useProductStore = defineStore('products', {
  actions: {
    async fetchProducts() {
      const data = await fetch('/api/products')
      const users = await axios.get('/api/users')
    }
  }
})
"""
        patterns = detector.detect("src/stores/products.ts", None, source, [], [])
        edges = _collect_edges(patterns, "store_fetches_api")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.API_CALLS for e in edges)
        urls = {e.metadata["api_url"] for e in edges}
        assert "/api/products" in urls
        assert "/api/users" in urls


# ══════════════════════════════════════════════════════════════
# Category 9: Nuxt-specific
# ══════════════════════════════════════════════════════════════


class TestNuxtPatterns:
    """Tests for Nuxt.js-specific edge types."""

    def test_nuxt_page_route(self, detector):
        source = b"""<template>
  <div>User Profile</div>
</template>
<script setup></script>
"""
        patterns = detector.detect("pages/users/[id].vue", None, source, [], [])
        edges = _collect_edges(patterns, "nuxt_page_route")
        assert len(edges) >= 1
        assert edges[0].kind == EdgeKind.ROUTES_TO
        assert edges[0].confidence == 0.98
        assert ":id" in edges[0].metadata["route_path"]

    def test_nuxt_page_route_index(self, detector):
        source = b"<template><div>Home</div></template>\n<script setup></script>"
        patterns = detector.detect("pages/index.vue", None, source, [], [])
        edges = _collect_edges(patterns, "nuxt_page_route")
        assert len(edges) >= 1
        assert edges[0].metadata["route_path"] == "/"

    def test_nuxt_layout_wraps(self, detector):
        source = b"""<script setup>
definePageMeta({
  layout: 'admin'
})
</script>
<template><div>Admin Page</div></template>
"""
        patterns = detector.detect("pages/admin/dashboard.vue", None, source, [], [])
        edges = _collect_edges(patterns, "nuxt_layout_wraps")
        assert len(edges) >= 1
        assert edges[0].kind == EdgeKind.RENDERS
        assert edges[0].metadata["layout_name"] == "admin"

    def test_nuxt_middleware_guards(self, detector):
        source = b"""<script setup>
definePageMeta({
  middleware: ['auth', 'admin']
})
</script>
<template><div>Protected Page</div></template>
"""
        patterns = detector.detect("pages/admin/settings.vue", None, source, [], [])
        edges = _collect_edges(patterns, "nuxt_middleware_guards")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.DEPENDS_ON for e in edges)
        mw_names = {e.metadata["middleware_name"] for e in edges}
        assert "auth" in mw_names
        assert "admin" in mw_names

    def test_nuxt_middleware_guards_single(self, detector):
        source = b"""<script setup>
definePageMeta({
  middleware: 'auth'
})
</script>
<template><div>Protected</div></template>
"""
        patterns = detector.detect("pages/profile.vue", None, source, [], [])
        edges = _collect_edges(patterns, "nuxt_middleware_guards")
        assert len(edges) >= 1
        assert edges[0].metadata["middleware_name"] == "auth"

    def test_nuxt_plugin_provides(self, detector):
        source = b"""export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.provide('api', apiClient)
  nuxtApp.provide('analytics', analyticsService)
})
"""
        patterns = detector.detect("plugins/api.ts", None, source, [], [])
        edges = _collect_edges(patterns, "nuxt_plugin_provides")
        assert len(edges) >= 2
        assert all(e.kind == EdgeKind.PROVIDES_CONTEXT for e in edges)
        keys = {e.metadata["provide_key"] for e in edges}
        assert "api" in keys
        assert "analytics" in keys

    def test_nuxt_server_api(self, detector):
        source = b"""export default defineEventHandler((event) => {
  return { hello: 'world' }
})
"""
        patterns = detector.detect("server/api/hello.ts", None, source, [], [])
        edges = _collect_edges(patterns, "nuxt_server_api")
        assert len(edges) >= 1
        assert edges[0].kind == EdgeKind.ROUTES_TO
        assert "/api/hello" in edges[0].metadata["api_route"]

    def test_nuxt_auto_imports(self, detector):
        source = b"""<script setup>
const route = useRoute()
const { data } = await useFetch('/api/items')
const config = useRuntimeConfig()
useHead({ title: 'My Page' })
</script>
<template><div></div></template>
"""
        patterns = detector.detect("pages/items.vue", None, source, [], [])
        edges = _collect_edges(patterns, "nuxt_auto_imports")
        assert len(edges) >= 4
        assert all(e.kind == EdgeKind.IMPORTS for e in edges)
        names = {e.metadata["composable_name"] for e in edges}
        assert "useRoute" in names
        assert "useFetch" in names
        assert "useRuntimeConfig" in names
        assert "useHead" in names


# ══════════════════════════════════════════════════════════════
# Integration: Verify all 29 edge types can be produced
# ══════════════════════════════════════════════════════════════


class TestEdgeTypeCompleteness:
    """Verify that all 29 edge types are detectable."""

    EXPECTED_EDGE_TYPES = {
        "vue_imports_component",
        "vue_registers_component",
        "vue_renders_component",
        "vue_extends_component",
        "vue_uses_mixin",
        "vue_defines_prop",
        "vue_emits_event",
        "vue_passes_prop",
        "vue_listens_event",
        "vue_v_model_binds",
        "vue_provides",
        "vue_injects",
        "vue_uses_composable",
        "vue_uses_store",
        "vue_routes_to",
        "vue_lazy_loads",
        "vue_guards_route",
        "vue_slot_defines",
        "vue_slot_fills",
        "vue_uses_directive",
        "vue_teleports_to",
        "vue_dynamic_component",
        "store_depends_on",
        "store_fetches_api",
        "nuxt_page_route",
        "nuxt_layout_wraps",
        "nuxt_middleware_guards",
        "nuxt_plugin_provides",
        "nuxt_server_api",
        "nuxt_auto_imports",
    }

    def test_all_edge_types_exist(self, detector):
        """Smoke test: run detector on various sources and collect all edge types."""
        all_types: set[str] = set()

        # Component relationships
        src1 = b"""<template><UserCard :title="t" @click="h" v-model="v" v-focus /><component :is="c" /><Teleport to="#m"><slot name="s"></slot></Teleport></template>
<script setup>
import UserCard from './UserCard.vue'
const props = defineProps(['title'])
const emit = defineEmits(['update'])
</script>"""
        patterns = detector.detect("src/components/Test.vue", None, src1, [], [])
        all_types |= _collect_all_edge_types(patterns)

        # Options API
        src2 = b"""export default {
  extends: BaseComp,
  mixins: [MixA],
  components: { Child },
  data() { return {} }
}"""
        patterns = detector.detect("src/components/Opts.vue", None, src2, [], [])
        all_types |= _collect_all_edge_types(patterns)

        # Provide/Inject
        src3 = b"""function setup() {
  provide('key', val)
  const x = inject('key')
}"""
        nodes3 = [_make_fn_node("setup", "src/PI.vue", 1, 4)]
        patterns = detector.detect("src/PI.vue", None, src3, nodes3, [])
        all_types |= _collect_all_edge_types(patterns)

        # Composables
        src4 = b"""function setup() {
  const auth = useAuth()
}"""
        nodes4 = [_make_fn_node("setup", "src/C.vue", 1, 3)]
        patterns = detector.detect("src/C.vue", None, src4, nodes4, [])
        all_types |= _collect_all_edge_types(patterns)

        # Stores
        src5 = b"""import { defineStore } from 'pinia'
export const useCartStore = defineStore('cart', {
  actions: {
    go() {
      const u = useUserStore()
      fetch('/api/x')
    }
  }
})"""
        patterns = detector.detect("src/stores/cart.ts", None, src5, [], [])
        all_types |= _collect_all_edge_types(patterns)

        # Store usage from component
        src5b = b"""function setup() {
  const store = useCartStore()
}"""
        nodes5b = [_make_fn_node("setup", "src/X.vue", 1, 3)]
        patterns = detector.detect("src/X.vue", None, src5b, nodes5b, [])
        all_types |= _collect_all_edge_types(patterns)

        # Router
        src6 = b"""import { createRouter } from 'vue-router'
const routes = [
  { path: '/home', component: HomeView },
  { path: '/about', component: () => import('./About.vue') },
]
router.beforeEach(() => {})"""
        patterns = detector.detect("src/router.ts", None, src6, [], [])
        all_types |= _collect_all_edge_types(patterns)

        # Slots
        src7 = b"""<template><slot name="header"></slot><Layout><template #footer>x</template></Layout></template>
<script setup></script>"""
        patterns = detector.detect("src/S.vue", None, src7, [], [])
        all_types |= _collect_all_edge_types(patterns)

        # Nuxt
        src8 = b"""<script setup>
definePageMeta({ layout: 'default', middleware: ['auth'] })
const route = useRoute()
</script>
<template><div></div></template>"""
        patterns = detector.detect("pages/index.vue", None, src8, [], [])
        all_types |= _collect_all_edge_types(patterns)

        src9 = b"""export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.provide('svc', svc)
})"""
        patterns = detector.detect("plugins/svc.ts", None, src9, [], [])
        all_types |= _collect_all_edge_types(patterns)

        src10 = b"export default defineEventHandler(() => ({}))"
        patterns = detector.detect("server/api/health.ts", None, src10, [], [])
        all_types |= _collect_all_edge_types(patterns)

        # Check coverage
        missing = self.EXPECTED_EDGE_TYPES - all_types
        assert not missing, f"Missing edge types: {missing}"
