"""Tests for advanced Angular edge types (10 new edge types)."""

from __future__ import annotations

import pytest

from coderag.core.models import EdgeKind
from coderag.plugins.typescript.frameworks.angular import AngularDetector


@pytest.fixture
def detector():
    return AngularDetector()


def _edges_by_type(patterns, edge_type):
    edges = []
    for p in patterns:
        for e in p.edges:
            if e.metadata.get("angular_edge_type") == edge_type:
                edges.append(e)
    return edges


def _all_edges(patterns):
    edges = []
    for p in patterns:
        edges.extend(p.edges)
    return edges


# ===========================================================================
# 1. angular_resolves
# ===========================================================================


class TestAngularResolves:
    """Edge #1: angular_resolves in _detect_routes."""

    def test_resolve_object_form(self, detector):
        """resolve: { data: DataResolver, user: UserResolver }"""
        source = b"""
const routes: Routes = [
  {
    path: 'dashboard',
    component: DashboardComponent,
    resolve: { data: DataResolver, user: UserResolver }
  },
];
"""
        patterns = detector.detect("app-routing.module.ts", None, source, [], [])
        resolve_edges = _edges_by_type(patterns, "angular_resolves")
        assert len(resolve_edges) == 2
        targets = {e.target_id for e in resolve_edges}
        assert "__unresolved__:type:DataResolver" in targets
        assert "__unresolved__:type:UserResolver" in targets
        for e in resolve_edges:
            assert e.kind == EdgeKind.DEPENDS_ON
            assert e.confidence == 0.95

    def test_resolve_array_form(self, detector):
        """resolve: [DataResolver]"""
        source = b"""
const routes: Routes = [
  {
    path: 'profile',
    component: ProfileComponent,
    resolve: [ProfileResolver]
  },
];
"""
        patterns = detector.detect("app-routing.module.ts", None, source, [], [])
        resolve_edges = _edges_by_type(patterns, "angular_resolves")
        assert len(resolve_edges) == 1
        assert resolve_edges[0].target_id == "__unresolved__:type:ProfileResolver"

    def test_guard_regex_no_longer_captures_resolve(self, detector):
        """Ensure _ROUTE_GUARD_RE does not capture resolve."""
        source = b"""
const routes: Routes = [
  {
    path: 'admin',
    component: AdminComponent,
    canActivate: [AuthGuard],
    resolve: { data: AdminResolver }
  },
];
"""
        patterns = detector.detect("app-routing.module.ts", None, source, [], [])
        guard_edges = _edges_by_type(patterns, "angular_guards")
        resolve_edges = _edges_by_type(patterns, "angular_resolves")
        # Guards should only have AuthGuard, not AdminResolver
        assert len(guard_edges) == 1
        assert "AuthGuard" in guard_edges[0].target_id
        # Resolve should have AdminResolver
        assert len(resolve_edges) == 1
        assert "AdminResolver" in resolve_edges[0].target_id


# ===========================================================================
# 2. angular_uses_pipe
# ===========================================================================


class TestAngularUsesPipe:
    """Edge #2: angular_uses_pipe in _detect_component."""

    def test_custom_pipe_in_template(self, detector):
        source = b"""
@Component({
  selector: 'app-test',
  template: `<div>{{ value | truncate | highlight }}</div>`
})
export class TestComponent {}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        pipe_edges = _edges_by_type(patterns, "angular_uses_pipe")
        assert len(pipe_edges) == 2
        targets = {e.target_id for e in pipe_edges}
        assert "__unresolved__:pipe:truncate" in targets
        assert "__unresolved__:pipe:highlight" in targets
        for e in pipe_edges:
            assert e.kind == EdgeKind.DEPENDS_ON
            assert e.confidence == 0.85

    def test_builtin_pipes_skipped(self, detector):
        """Built-in pipes like date, uppercase, async should be skipped."""
        source = b"""
@Component({
  selector: 'app-test',
  template: `<div>{{ value | date | uppercase | json }}</div>`
})
export class TestComponent {}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        pipe_edges = _edges_by_type(patterns, "angular_uses_pipe")
        assert len(pipe_edges) == 0

    def test_duplicate_pipes_deduplicated(self, detector):
        source = b"""
@Component({
  selector: 'app-test',
  template: `
    <div>{{ a | myPipe }}</div>
    <div>{{ b | myPipe }}</div>
  `
})
export class TestComponent {}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        pipe_edges = _edges_by_type(patterns, "angular_uses_pipe")
        assert len(pipe_edges) == 1


# ===========================================================================
# 3. angular_uses_directive
# ===========================================================================


class TestAngularUsesDirective:
    """Edge #3: angular_uses_directive in _detect_component."""

    def test_custom_attribute_directive(self, detector):
        source = b"""
@Component({
  selector: 'app-test',
  template: `<div [appHighlight]="color" [appTooltip]="text">Hello</div>`
})
export class TestComponent {}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        dir_edges = _edges_by_type(patterns, "angular_uses_directive")
        assert len(dir_edges) == 2
        targets = {e.target_id for e in dir_edges}
        assert "__unresolved__:directive:appHighlight" in targets
        assert "__unresolved__:directive:appTooltip" in targets
        for e in dir_edges:
            assert e.kind == EdgeKind.DEPENDS_ON
            assert e.confidence == 0.85

    def test_non_app_directives_not_matched(self, detector):
        """Only [appXxx] pattern should match."""
        source = b"""
@Component({
  selector: 'app-test',
  template: `<div [ngClass]="cls" [hidden]="true">Hello</div>`
})
export class TestComponent {}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        dir_edges = _edges_by_type(patterns, "angular_uses_directive")
        assert len(dir_edges) == 0


# ===========================================================================
# 4. angular_binds_input
# ===========================================================================


class TestAngularBindsInput:
    """Edge #4: angular_binds_input in _detect_component."""

    def test_property_bindings(self, detector):
        source = b"""
@Component({
  selector: 'app-parent',
  template: `<app-child [name]="userName" [age]="userAge"></app-child>`
})
export class ParentComponent {}
"""
        patterns = detector.detect("parent.component.ts", None, source, [], [])
        input_edges = _edges_by_type(patterns, "angular_binds_input")
        assert len(input_edges) == 2
        targets = {e.target_id for e in input_edges}
        assert "__unresolved__:input:name" in targets
        assert "__unresolved__:input:age" in targets
        for e in input_edges:
            assert e.kind == EdgeKind.PASSES_PROP
            assert e.confidence == 0.85


# ===========================================================================
# 5. angular_emits_output
# ===========================================================================


class TestAngularEmitsOutput:
    """Edge #5: angular_emits_output in _detect_component."""

    def test_custom_event_bindings(self, detector):
        source = b"""
@Component({
  selector: 'app-parent',
  template: `<app-child (itemSelected)="onSelect($event)" (deleted)="onDelete($event)"></app-child>`
})
export class ParentComponent {}
"""
        patterns = detector.detect("parent.component.ts", None, source, [], [])
        output_edges = _edges_by_type(patterns, "angular_emits_output")
        assert len(output_edges) == 2
        targets = {e.target_id for e in output_edges}
        assert "__unresolved__:output:itemSelected" in targets
        assert "__unresolved__:output:deleted" in targets
        for e in output_edges:
            assert e.kind == EdgeKind.LISTENS_TO
            assert e.confidence == 0.85

    def test_native_dom_events_skipped(self, detector):
        """Native DOM events like click, submit should be skipped."""
        source = b"""
@Component({
  selector: 'app-test',
  template: `<button (click)="onClick()" (submit)="onSubmit()" (focus)="onFocus()">Go</button>`
})
export class TestComponent {}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        output_edges = _edges_by_type(patterns, "angular_emits_output")
        assert len(output_edges) == 0

    def test_mixed_native_and_custom_events(self, detector):
        source = b"""
@Component({
  selector: 'app-test',
  template: `
    <div (click)="onClick()">
      <app-child (customEvent)="onCustom($event)"></app-child>
    </div>
  `
})
export class TestComponent {}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        output_edges = _edges_by_type(patterns, "angular_emits_output")
        assert len(output_edges) == 1
        assert output_edges[0].metadata["event_name"] == "customEvent"


# ===========================================================================
# 6. angular_projects_content
# ===========================================================================


class TestAngularProjectsContent:
    """Edge #6: angular_projects_content in _detect_component."""

    def test_ng_content_detected(self, detector):
        source = b"""
@Component({
  selector: 'app-card',
  template: `
    <div class="card">
      <ng-content></ng-content>
    </div>
  `
})
export class CardComponent {}
"""
        patterns = detector.detect("card.component.ts", None, source, [], [])
        proj_edges = _edges_by_type(patterns, "angular_projects_content")
        assert len(proj_edges) == 1
        assert proj_edges[0].kind == EdgeKind.RENDERS
        assert proj_edges[0].confidence == 0.85
        assert "CardComponent" in proj_edges[0].target_id

    def test_no_ng_content(self, detector):
        source = b"""
@Component({
  selector: 'app-simple',
  template: `<div>Simple</div>`
})
export class SimpleComponent {}
"""
        patterns = detector.detect("simple.component.ts", None, source, [], [])
        proj_edges = _edges_by_type(patterns, "angular_projects_content")
        assert len(proj_edges) == 0


# ===========================================================================
# 7. angular_subscribes_to
# ===========================================================================


class TestAngularSubscribesTo:
    """Edge #7: angular_subscribes_to in _detect_rxjs_patterns and _detect_component."""

    def test_explicit_subscribe(self, detector):
        source = b"""
export class DataService {
  data$: Observable<string[]>;

  getData() {
    this.data$.subscribe(data => console.log(data));
  }
}
"""
        patterns = detector.detect("data.service.ts", None, source, [], [])
        sub_edges = _edges_by_type(patterns, "angular_subscribes_to")
        assert len(sub_edges) >= 1
        assert sub_edges[0].kind == EdgeKind.DEPENDS_ON
        assert sub_edges[0].confidence == 0.85
        assert sub_edges[0].metadata["subscribe_type"] == "explicit"

    def test_async_pipe_in_template(self, detector):
        source = b"""
@Component({
  selector: 'app-test',
  template: `<div>{{ data$ | async }}</div>`
})
export class TestComponent {}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        sub_edges = _edges_by_type(patterns, "angular_subscribes_to")
        assert len(sub_edges) >= 1
        async_edges = [e for e in sub_edges if e.metadata.get("subscribe_type") == "async_pipe"]
        assert len(async_edges) == 1
        assert async_edges[0].target_id == "__unresolved__:observable:async_pipe"

    def test_multiple_subscribes(self, detector):
        source = b"""
export class MultiService {
  a$: Observable<number>;
  b$: Observable<string>;

  init() {
    this.a$.subscribe(a => console.log(a));
    this.b$.subscribe(b => console.log(b));
  }
}
"""
        patterns = detector.detect("multi.service.ts", None, source, [], [])
        sub_edges = _edges_by_type(patterns, "angular_subscribes_to")
        assert len(sub_edges) >= 2


# ===========================================================================
# 8. angular_signal_depends
# ===========================================================================


class TestAngularSignalDepends:
    """Edge #8: angular_signal_depends in _detect_signals."""

    def test_computed_depends_on_signal(self, detector):
        source = b"""
@Component({selector: 'app-counter'})
export class CounterComponent {
  count = signal(0);
  doubled = computed(() => this.count() * 2);
}
"""
        patterns = detector.detect("counter.component.ts", None, source, [], [])
        dep_edges = _edges_by_type(patterns, "angular_signal_depends")
        assert len(dep_edges) == 1
        assert dep_edges[0].kind == EdgeKind.DEPENDS_ON
        assert dep_edges[0].confidence == 0.90
        assert "count" in dep_edges[0].target_id

    def test_computed_depends_on_multiple_signals(self, detector):
        source = b"""
export class CalcComponent {
  a = signal(1);
  b = signal(2);
  sum = computed(() => this.a() + this.b());
}
"""
        patterns = detector.detect("calc.component.ts", None, source, [], [])
        dep_edges = _edges_by_type(patterns, "angular_signal_depends")
        assert len(dep_edges) == 2
        targets = {e.metadata["signal_name"] for e in dep_edges}
        assert "a" in targets
        assert "b" in targets

    def test_no_signal_depends_without_signals(self, detector):
        """computed() referencing non-signal functions should not create edges."""
        source = b"""
export class PlainComponent {
  doubled = computed(() => this.getValue() * 2);
}
"""
        patterns = detector.detect("plain.component.ts", None, source, [], [])
        dep_edges = _edges_by_type(patterns, "angular_signal_depends")
        assert len(dep_edges) == 0


# ===========================================================================
# 9. angular_template_ref
# ===========================================================================


class TestAngularTemplateRef:
    """Edge #9: angular_template_ref in _detect_component."""

    def test_template_url_creates_edge(self, detector):
        source = b"""
@Component({
  selector: 'app-root',
  templateUrl: './app.component.html'
})
export class AppComponent {}
"""
        patterns = detector.detect("app.component.ts", None, source, [], [])
        tpl_edges = _edges_by_type(patterns, "angular_template_ref")
        assert len(tpl_edges) == 1
        assert tpl_edges[0].kind == EdgeKind.DEPENDS_ON
        assert tpl_edges[0].confidence == 0.90
        assert tpl_edges[0].target_id == "__unresolved__:template:./app.component.html"

    def test_no_template_url_no_edge(self, detector):
        """Inline template should not create template_ref edge."""
        source = b"""
@Component({
  selector: 'app-inline',
  template: `<div>Inline</div>`
})
export class InlineComponent {}
"""
        patterns = detector.detect("inline.component.ts", None, source, [], [])
        tpl_edges = _edges_by_type(patterns, "angular_template_ref")
        assert len(tpl_edges) == 0


# ===========================================================================
# 10. angular_style_ref
# ===========================================================================


class TestAngularStyleRef:
    """Edge #10: angular_style_ref in _detect_component."""

    def test_style_urls_creates_edges(self, detector):
        source = b"""
@Component({
  selector: 'app-styled',
  templateUrl: './styled.component.html',
  styleUrls: ['./styled.component.css', './shared.css']
})
export class StyledComponent {}
"""
        patterns = detector.detect("styled.component.ts", None, source, [], [])
        style_edges = _edges_by_type(patterns, "angular_style_ref")
        assert len(style_edges) == 2
        targets = {e.target_id for e in style_edges}
        assert "__unresolved__:stylesheet:./styled.component.css" in targets
        assert "__unresolved__:stylesheet:./shared.css" in targets
        for e in style_edges:
            assert e.kind == EdgeKind.DEPENDS_ON
            assert e.confidence == 0.95

    def test_single_style_url_angular17(self, detector):
        """Angular 17+ styleUrl (singular, no array)."""
        source = b"""
@Component({
  selector: 'app-modern',
  styleUrl: './modern.component.scss'
})
export class ModernComponent {}
"""
        patterns = detector.detect("modern.component.ts", None, source, [], [])
        style_edges = _edges_by_type(patterns, "angular_style_ref")
        assert len(style_edges) == 1
        assert style_edges[0].target_id == "__unresolved__:stylesheet:./modern.component.scss"

    def test_no_styles_no_edge(self, detector):
        source = b"""
@Component({
  selector: 'app-plain',
  template: `<div>No styles</div>`
})
export class PlainComponent {}
"""
        patterns = detector.detect("plain.component.ts", None, source, [], [])
        style_edges = _edges_by_type(patterns, "angular_style_ref")
        assert len(style_edges) == 0


# ===========================================================================
# Combined / Integration tests
# ===========================================================================


class TestCombinedEdgeTypes:
    """Test multiple new edge types in a single component."""

    def test_full_component_with_all_template_edges(self, detector):
        """A component with pipes, directives, inputs, outputs, ng-content, async."""
        source = b"""
@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss'],
  template: `
    <div [appHighlight]="color">
      <app-header [title]="pageTitle" (menuToggled)="onToggle($event)"></app-header>
      <div>{{ data | customFormat }}</div>
      <div>{{ stream$ | async }}</div>
      <ng-content></ng-content>
    </div>
  `
})
export class DashboardComponent {}
"""
        patterns = detector.detect("dashboard.component.ts", None, source, [], [])

        # template_ref
        tpl_edges = _edges_by_type(patterns, "angular_template_ref")
        assert len(tpl_edges) == 1

        # style_ref
        style_edges = _edges_by_type(patterns, "angular_style_ref")
        assert len(style_edges) == 1

        # uses_pipe (customFormat, not async which is builtin)
        pipe_edges = _edges_by_type(patterns, "angular_uses_pipe")
        assert len(pipe_edges) == 1
        assert pipe_edges[0].metadata["pipe_name"] == "customFormat"

        # uses_directive
        dir_edges = _edges_by_type(patterns, "angular_uses_directive")
        assert len(dir_edges) == 1
        assert dir_edges[0].metadata["directive_name"] == "appHighlight"

        # binds_input
        input_edges = _edges_by_type(patterns, "angular_binds_input")
        assert len(input_edges) == 1
        assert input_edges[0].metadata["input_name"] == "title"

        # emits_output
        output_edges = _edges_by_type(patterns, "angular_emits_output")
        assert len(output_edges) == 1
        assert output_edges[0].metadata["event_name"] == "menuToggled"

        # projects_content
        proj_edges = _edges_by_type(patterns, "angular_projects_content")
        assert len(proj_edges) == 1

        # subscribes_to (async pipe)
        sub_edges = _edges_by_type(patterns, "angular_subscribes_to")
        assert len(sub_edges) >= 1

    def test_all_edge_types_count(self, detector):
        """Verify we can produce all 10 new edge types across patterns."""
        # Component with template features
        comp_source = b"""
@Component({
  selector: 'app-full',
  templateUrl: './full.html',
  styleUrls: ['./full.css'],
  template: `
    <div [appDrag]="true">
      <span>{{ val | myFilter }}</span>
      <app-child [data]="d" (saved)="onSave($event)"></app-child>
      <ng-content></ng-content>
      {{ obs$ | async }}
    </div>
  `
})
export class FullComponent {
  count = signal(0);
  doubled = computed(() => this.count() * 2);
}
"""
        patterns = detector.detect("full.component.ts", None, comp_source, [], [])

        edge_types_found = set()
        for p in patterns:
            for e in p.edges:
                et = e.metadata.get("angular_edge_type")
                if et:
                    edge_types_found.add(et)

        expected_new = {
            "angular_template_ref",
            "angular_style_ref",
            "angular_uses_pipe",
            "angular_uses_directive",
            "angular_binds_input",
            "angular_emits_output",
            "angular_projects_content",
            "angular_subscribes_to",
            "angular_signal_depends",
        }
        # All except angular_resolves (which is in routes)
        for et in expected_new:
            assert et in edge_types_found, f"Missing edge type: {et}"

        # Now test resolves separately
        route_source = b"""
const routes: Routes = [
  { path: 'x', component: XComponent, resolve: { d: DResolver } }
];
"""
        route_patterns = detector.detect("routing.ts", None, route_source, [], [])
        resolve_edges = _edges_by_type(route_patterns, "angular_resolves")
        assert len(resolve_edges) >= 1


# ===========================================================================
# Edge type metadata validation
# ===========================================================================


class TestEdgeMetadata:
    """Verify all new edges have correct metadata structure."""

    def test_all_edges_have_framework_key(self, detector):
        source = b"""
@Component({
  selector: 'app-meta',
  templateUrl: './meta.html',
  styleUrls: ['./meta.css'],
  template: `
    <div [appTest]="x">
      {{ v | myPipe }}
      <app-child [inp]="y" (out)="h($event)"></app-child>
      <ng-content></ng-content>
      {{ s$ | async }}
    </div>
  `
})
export class MetaComponent {
  sig = signal(0);
  comp = computed(() => this.sig() * 2);
}
"""
        patterns = detector.detect("meta.component.ts", None, source, [], [])
        all_e = _all_edges(patterns)
        for e in all_e:
            assert "framework" in e.metadata, f"Edge missing framework key: {e.metadata}"
            assert e.metadata["framework"] == "angular"
            assert "angular_edge_type" in e.metadata
