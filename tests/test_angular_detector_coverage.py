"""Targeted tests for Angular detector coverage.

Covers missing lines: 244, 262, 265, 323-324, 409, 463, 489-492, 548, 605,
763, 823, 962-964, 980, 1017-1023, 1063-1068, 1204-1215, 1247-1264,
1308-1309, 1314-1359
"""

from __future__ import annotations

import pytest

from coderag.core.models import EdgeKind, Node, NodeKind
from coderag.plugins.typescript.frameworks.angular import AngularDetector


@pytest.fixture
def detector():
    return AngularDetector()


def _make_node(id, kind, name, fpath, start, end, lang="typescript", **kw):
    return Node(
        id=id,
        kind=kind,
        name=name,
        qualified_name=kw.pop("qname", name),
        file_path=fpath,
        start_line=start,
        end_line=end,
        language=lang,
        **kw,
    )


# ---------------------------------------------------------------------------
# Non-TypeScript files
# ---------------------------------------------------------------------------


class TestNonTsFiles:
    """Line 244: non-TS files return empty patterns."""

    def test_js_file_returns_empty(self, detector):
        source = b'@Component({selector: "app-root"}) class AppComponent {}'
        patterns = detector.detect("app.js", None, source, [], [])
        assert patterns == []

    def test_py_file_returns_empty(self, detector):
        source = b"class Foo: pass"
        patterns = detector.detect("app.py", None, source, [], [])
        assert patterns == []


# ---------------------------------------------------------------------------
# Component detection
# ---------------------------------------------------------------------------


class TestComponentDetection:
    """Lines 323-324, 409, 1308-1309, 1314-1359."""

    def test_basic_component(self, detector):
        source = b"""
@Component({
  selector: \'app-root\',
  templateUrl: \'./app.component.html\',
  styleUrls: [\'./app.component.css\']
})
export class AppComponent {
  title = \'my-app\';
}
"""
        patterns = detector.detect("app.component.ts", None, source, [], [])
        assert len(patterns) >= 1
        comp_pattern = next((p for p in patterns if p.pattern_type == "components"), None)
        assert comp_pattern is not None
        assert len(comp_pattern.nodes) == 1
        assert comp_pattern.nodes[0].name == "AppComponent"
        assert comp_pattern.nodes[0].metadata["selector"] == "app-root"
        assert comp_pattern.nodes[0].metadata["templateUrl"] == "./app.component.html"
        assert "./app.component.css" in comp_pattern.nodes[0].metadata["styleUrls"]

    def test_standalone_component(self, detector):
        """Lines 1308-1309: standalone: true flag."""
        source = b"""
@Component({
  selector: \'app-standalone\',
  standalone: true,
  template: \'<div>Hello</div>\'
})
export class StandaloneComponent {}
"""
        patterns = detector.detect("standalone.component.ts", None, source, [], [])
        comp_pattern = next((p for p in patterns if p.pattern_type == "components"), None)
        assert comp_pattern is not None
        assert comp_pattern.nodes[0].metadata["standalone"] is True

    def test_component_with_inline_template_child_selectors(self, detector):
        """Lines 1314-1359: inline template analysis for child components."""
        source = b"""
@Component({
  selector: \'app-parent\',
  template: `
    <div>
      <app-header></app-header>
      <app-sidebar></app-sidebar>
    </div>
  `
})
export class ParentComponent {}
"""
        patterns = detector.detect("parent.component.ts", None, source, [], [])
        comp_pattern = next((p for p in patterns if p.pattern_type == "components"), None)
        assert comp_pattern is not None
        # Should have RENDERS edges for child selectors
        render_edges = [e for e in comp_pattern.edges if e.kind == EdgeKind.RENDERS]
        assert len(render_edges) >= 2
        targets = {e.target_id for e in render_edges}
        assert any("app-header" in t for t in targets)
        assert any("app-sidebar" in t for t in targets)

    def test_component_no_class_name_skipped(self, detector):
        """Component decorator without a class should be skipped."""
        source = b"@Component({selector: 'app-x'})\n// no class here\n"
        patterns = detector.detect("broken.ts", None, source, [], [])
        comp_pattern = next((p for p in patterns if p.pattern_type == "components"), None)
        assert comp_pattern is None

    def test_component_with_existing_class_node(self, detector):
        """Component with matching class node in nodes list."""
        source = b"""
@Component({
  selector: \'app-test\'
})
export class TestComponent {
  doStuff() {}
}
"""
        class_node = _make_node(
            "test.ts:5:class:TestComponent",
            NodeKind.CLASS,
            "TestComponent",
            "test.component.ts",
            5,
            7,
        )
        patterns = detector.detect("test.component.ts", None, source, [class_node], [])
        comp_pattern = next((p for p in patterns if p.pattern_type == "components"), None)
        assert comp_pattern is not None
        assert comp_pattern.nodes[0].name == "TestComponent"


# ---------------------------------------------------------------------------
# Service detection
# ---------------------------------------------------------------------------


class TestServiceDetection:
    """Lines 463, 489-492."""

    def test_injectable_service(self, detector):
        source = b"""
@Injectable({
  providedIn: \'root\'
})
export class UserService {
  getUsers() {}
}
"""
        patterns = detector.detect("user.service.ts", None, source, [], [])
        svc_pattern = next((p for p in patterns if p.pattern_type == "services"), None)
        assert svc_pattern is not None
        assert svc_pattern.nodes[0].name == "UserService"
        assert svc_pattern.nodes[0].metadata["providedIn"] == "root"

    def test_injectable_without_provided_in(self, detector):
        source = b"""
@Injectable()
export class DataService {
  fetchData() {}
}
"""
        patterns = detector.detect("data.service.ts", None, source, [], [])
        svc_pattern = next((p for p in patterns if p.pattern_type == "services"), None)
        assert svc_pattern is not None
        assert svc_pattern.nodes[0].name == "DataService"

    def test_injectable_no_class_skipped(self, detector):
        source = b"@Injectable()\n// no class\n"
        patterns = detector.detect("broken.ts", None, source, [], [])
        svc_pattern = next((p for p in patterns if p.pattern_type == "services"), None)
        assert svc_pattern is None


# ---------------------------------------------------------------------------
# NgModule detection
# ---------------------------------------------------------------------------


class TestModuleDetection:
    """Lines 548, 605, 1204-1215, 1247-1264."""

    def test_ngmodule_with_declarations_imports_exports(self, detector):
        source = b"""
@NgModule({
  declarations: [AppComponent, HeaderComponent],
  imports: [BrowserModule, FormsModule],
  exports: [AppComponent],
  providers: [UserService],
  bootstrap: [AppComponent]
})
export class AppModule {}
"""
        patterns = detector.detect("app.module.ts", None, source, [], [])
        mod_pattern = next((p for p in patterns if p.pattern_type == "modules"), None)
        assert mod_pattern is not None
        assert mod_pattern.nodes[0].name == "AppModule"
        # Check edges
        edge_types = {e.metadata.get("angular_edge_type") for e in mod_pattern.edges}
        assert "angular_declares" in edge_types
        assert "angular_imports_module" in edge_types
        assert "angular_exports" in edge_types
        assert "angular_provides" in edge_types
        assert "angular_bootstraps" in edge_types

    def test_ngmodule_no_class_skipped(self, detector):
        source = b"@NgModule({declarations: []})\n// no class\n"
        patterns = detector.detect("broken.ts", None, source, [], [])
        mod_pattern = next((p for p in patterns if p.pattern_type == "modules"), None)
        assert mod_pattern is None


# ---------------------------------------------------------------------------
# Directive detection
# ---------------------------------------------------------------------------


class TestDirectiveDetection:
    """Lines 1063-1068."""

    def test_directive_with_selector(self, detector):
        source = b"""
@Directive({
  selector: \'[appHighlight]\'
})
export class HighlightDirective {
  constructor(private el: ElementRef) {}
}
"""
        patterns = detector.detect("highlight.directive.ts", None, source, [], [])
        dir_pattern = next((p for p in patterns if p.pattern_type == "directives"), None)
        assert dir_pattern is not None
        assert dir_pattern.nodes[0].name == "HighlightDirective"
        assert dir_pattern.nodes[0].metadata["selector"] == "[appHighlight]"

    def test_directive_no_class_skipped(self, detector):
        source = b"@Directive({selector: '[x]'})\n// no class\n"
        patterns = detector.detect("broken.ts", None, source, [], [])
        dir_pattern = next((p for p in patterns if p.pattern_type == "directives"), None)
        assert dir_pattern is None


# ---------------------------------------------------------------------------
# Pipe detection
# ---------------------------------------------------------------------------


class TestPipeDetection:
    """Lines 962-964, 980."""

    def test_pipe_with_name(self, detector):
        source = b"""
@Pipe({
  name: \'truncate\'
})
export class TruncatePipe implements PipeTransform {
  transform(value: string): string {
    return value.substring(0, 10);
  }
}
"""
        patterns = detector.detect("truncate.pipe.ts", None, source, [], [])
        pipe_pattern = next((p for p in patterns if p.pattern_type == "pipes"), None)
        assert pipe_pattern is not None
        assert pipe_pattern.nodes[0].name == "TruncatePipe"
        assert pipe_pattern.nodes[0].metadata["pipe_name"] == "truncate"

    def test_pipe_no_class_skipped(self, detector):
        source = b"@Pipe({name: 'x'})\n// no class\n"
        patterns = detector.detect("broken.ts", None, source, [], [])
        pipe_pattern = next((p for p in patterns if p.pattern_type == "pipes"), None)
        assert pipe_pattern is None


# ---------------------------------------------------------------------------
# Route detection
# ---------------------------------------------------------------------------


class TestRouteDetection:
    """Lines 1017-1023."""

    def test_routes_with_component(self, detector):
        source = b"""
const routes: Routes = [
  { path: \'home\', component: HomeComponent },
  { path: \'about\', component: AboutComponent },
];
"""
        patterns = detector.detect("app-routing.module.ts", None, source, [], [])
        route_pattern = next((p for p in patterns if p.pattern_type == "routes"), None)
        assert route_pattern is not None
        assert len(route_pattern.nodes) >= 2
        route_names = {n.name for n in route_pattern.nodes}
        assert "home" in route_names
        assert "about" in route_names
        # Check ROUTES_TO edges
        routes_to = [e for e in route_pattern.edges if e.kind == EdgeKind.ROUTES_TO]
        assert len(routes_to) >= 2

    def test_routes_with_lazy_loading(self, detector):
        source = b"""
const routes: Routes = [
  {
    path: \'admin\',
    loadComponent: () => import(\'./admin/admin.component\').then(m => m.AdminComponent)
  },
];
"""
        patterns = detector.detect("app-routing.module.ts", None, source, [], [])
        route_pattern = next((p for p in patterns if p.pattern_type == "routes"), None)
        assert route_pattern is not None
        lazy_edges = [e for e in route_pattern.edges if e.kind == EdgeKind.DYNAMIC_IMPORTS]
        assert len(lazy_edges) >= 1

    def test_routes_with_lazy_children(self, detector):
        source = b"""
const routes: Routes = [
  {
    path: \'dashboard\',
    loadChildren: () => import(\'./dashboard/dashboard.module\').then(m => m.DashboardModule)
  },
];
"""
        patterns = detector.detect("app-routing.module.ts", None, source, [], [])
        route_pattern = next((p for p in patterns if p.pattern_type == "routes"), None)
        assert route_pattern is not None
        lazy_edges = [e for e in route_pattern.edges if e.kind == EdgeKind.DYNAMIC_IMPORTS]
        assert len(lazy_edges) >= 1
        assert lazy_edges[0].metadata["lazy_type"] == "loadChildren"

    def test_routes_with_guards(self, detector):
        source = b"""
const routes: Routes = [
  {
    path: \'protected\',
    component: ProtectedComponent,
    canActivate: [AuthGuard, RoleGuard]
  },
];
"""
        patterns = detector.detect("app-routing.module.ts", None, source, [], [])
        route_pattern = next((p for p in patterns if p.pattern_type == "routes"), None)
        assert route_pattern is not None
        guard_edges = [e for e in route_pattern.edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(guard_edges) >= 2

    def test_no_routes_in_non_routing_file(self, detector):
        source = b"export class Foo {}\n"
        patterns = detector.detect("foo.ts", None, source, [], [])
        route_pattern = next((p for p in patterns if p.pattern_type == "routes"), None)
        assert route_pattern is None


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


class TestDependencyInjection:
    """Lines 262, 265."""

    def test_constructor_injection(self, detector):
        source = b"""
@Component({selector: \'app-test\'})
export class TestComponent {
  constructor(private userService: UserService, private http: HttpClient) {}
}
"""
        patterns = detector.detect("test.component.ts", None, source, [], [])
        di_pattern = next((p for p in patterns if p.pattern_type == "dependency_injection"), None)
        assert di_pattern is not None
        assert len(di_pattern.edges) >= 2

    def test_inject_function(self, detector):
        """Angular 14+ inject() function."""
        source = b"""
@Component({selector: \'app-modern\'})
export class ModernComponent {
  private userService = inject(UserService);
  private router = inject(Router);
}
"""
        patterns = detector.detect("modern.component.ts", None, source, [], [])
        di_pattern = next((p for p in patterns if p.pattern_type == "dependency_injection"), None)
        assert di_pattern is not None
        assert len(di_pattern.edges) >= 2


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


class TestSignalDetection:
    """Lines 763, 823."""

    def test_signal_detection(self, detector):
        source = b"""
@Component({selector: \'app-counter\'})
export class CounterComponent {
  count = signal(0);
  doubled = computed(() => this.count() * 2);

  constructor() {
    effect(() => console.log(this.count()));
  }
}
"""
        patterns = detector.detect("counter.component.ts", None, source, [], [])
        sig_pattern = next((p for p in patterns if p.pattern_type == "signals"), None)
        assert sig_pattern is not None
        signal_nodes = [n for n in sig_pattern.nodes if n.metadata.get("signal_kind") == "writable"]
        computed_nodes = [n for n in sig_pattern.nodes if n.metadata.get("signal_kind") == "computed"]
        assert len(signal_nodes) >= 1
        assert len(computed_nodes) >= 1
        assert sig_pattern.metadata["effect_count"] >= 1

    def test_effect_only(self, detector):
        source = b"""
export class EffectComponent {
  constructor() {
    effect(() => console.log(\'hello\'));
  }
}
"""
        patterns = detector.detect("effect.ts", None, source, [], [])
        sig_pattern = next((p for p in patterns if p.pattern_type == "signals"), None)
        assert sig_pattern is not None
        assert sig_pattern.metadata["effect_count"] >= 1

    def test_no_signals(self, detector):
        source = b"export class PlainComponent {}\n"
        patterns = detector.detect("plain.ts", None, source, [], [])
        sig_pattern = next((p for p in patterns if p.pattern_type == "signals"), None)
        assert sig_pattern is None


# ---------------------------------------------------------------------------
# RxJS / HTTP patterns
# ---------------------------------------------------------------------------


class TestRxJSPatterns:
    def test_observable_subject_subscribe(self, detector):
        source = b"""
export class DataService {
  data$: Observable<string[]>;
  private subject = new BehaviorSubject<number>(0);

  getData() {
    this.data$.subscribe(data => console.log(data));
    this.data$.pipe(map(x => x));
  }
}
"""
        patterns = detector.detect("data.service.ts", None, source, [], [])
        rxjs_pattern = next((p for p in patterns if p.pattern_type == "rxjs"), None)
        assert rxjs_pattern is not None

    def test_http_client_calls(self, detector):
        source = b"""
export class ApiService {
  constructor(private http: HttpClient) {}

  getUsers() {
    return this.http.get<User[]>(\'/api/users\');
  }

  createUser(user: User) {
    return this.http.post<User>(\'/api/users\', user);
  }

  deleteUser(id: number) {
    return this.http.delete(\'/api/users/\' + id);
  }
}
"""
        patterns = detector.detect("api.service.ts", None, source, [], [])
        rxjs_pattern = next((p for p in patterns if p.pattern_type == "rxjs"), None)
        assert rxjs_pattern is not None
        api_edges = [e for e in rxjs_pattern.edges if e.kind == EdgeKind.API_CALLS]
        assert len(api_edges) >= 3

    def test_http_client_without_url(self, detector):
        """HTTP calls without extractable URL."""
        source = b"""
export class ApiService {
  constructor(private http: HttpClient) {}

  getData() {
    return this.http.get<Data>(this.baseUrl + \'/data\');
  }
}
"""
        patterns = detector.detect("api.service.ts", None, source, [], [])
        rxjs_pattern = next((p for p in patterns if p.pattern_type == "rxjs"), None)
        assert rxjs_pattern is not None


# ---------------------------------------------------------------------------
# Multiple patterns in one file
# ---------------------------------------------------------------------------


class TestMultiplePatterns:
    def test_component_with_di_and_signals(self, detector):
        source = b"""
@Component({
  selector: \'app-dashboard\',
  template: `<div>{{ count() }}</div>`
})
export class DashboardComponent {
  count = signal(0);
  doubled = computed(() => this.count() * 2);

  constructor(private userService: UserService) {
    effect(() => console.log(this.count()));
  }
}
"""
        patterns = detector.detect("dashboard.component.ts", None, source, [], [])
        pattern_types = {p.pattern_type for p in patterns}
        assert "components" in pattern_types
        assert "signals" in pattern_types
        assert "dependency_injection" in pattern_types


# ---------------------------------------------------------------------------
# detect_global_patterns
# ---------------------------------------------------------------------------


class TestGlobalPatterns:
    def test_global_patterns_no_store(self, detector):
        """Global patterns with None store."""
        patterns = detector.detect_global_patterns(None)
        # Should not crash, may return empty
        assert isinstance(patterns, list)
