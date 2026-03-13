"""Django framework detector for CodeRAG.

Detects Django-specific patterns including models, views, URL patterns,
middleware, signals, admin registrations, serializers (DRF), and
management commands from already-parsed AST nodes and source code.
"""

from __future__ import annotations

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

# ── Regex patterns ────────────────────────────────────────────────────────

# Django model field types
_DJANGO_FIELD_RE = re.compile(
    r"^\s*(?P<field_name>\w+)\s*=\s*(?:models\.)?(?P<field_type>"
    r"CharField|TextField|IntegerField|FloatField|DecimalField|"
    r"BooleanField|DateField|DateTimeField|TimeField|"
    r"EmailField|URLField|SlugField|UUIDField|"
    r"FileField|ImageField|BinaryField|"
    r"AutoField|BigAutoField|SmallAutoField|"
    r"BigIntegerField|SmallIntegerField|PositiveIntegerField|"
    r"PositiveSmallIntegerField|PositiveBigIntegerField|"
    r"JSONField|ArrayField|HStoreField|"
    r"GenericIPAddressField|IPAddressField|"
    r"DurationField|FilePathField"
    r")\s*\(",
    re.MULTILINE,
)

# Django relationship fields
_DJANGO_RELATION_RE = re.compile(
    r"^\s*(?P<field_name>\w+)\s*=\s*(?:models\.)?(?P<rel_type>"
    r"ForeignKey|OneToOneField|ManyToManyField"
    r")\s*\(\s*[\'\"]?(?P<related>[\w\.]+)[\'\"]?",
    re.MULTILINE,
)

# Django URL patterns: path(), re_path(), url()
_URL_PATTERN_RE = re.compile(
    r"(?:path|re_path|url)\s*\(\s*[\'\"](?P<pattern>[^\'\"]*)[\'\"]\s*,\s*"
    r"(?P<view>[^,\)]+)",
    re.MULTILINE,
)

# Django URL include()
_URL_INCLUDE_RE = re.compile(
    r"path\s*\(\s*[\'\"](?P<prefix>[^\'\"]*)[\'\"]\s*,\s*include\s*\(\s*"
    r"[\'\"](?P<module>[^\'\"]+)[\'\"]\s*\)",
    re.MULTILINE,
)

# Django class-based view base classes
_CBV_BASES = {
    "View",
    "TemplateView",
    "RedirectView",
    "ListView",
    "DetailView",
    "CreateView",
    "UpdateView",
    "DeleteView",
    "FormView",
    "ArchiveIndexView",
    "YearArchiveView",
    "MonthArchiveView",
    "DayArchiveView",
    "DateDetailView",
    # DRF views
    "APIView",
    "GenericAPIView",
    "ViewSet",
    "ModelViewSet",
    "ReadOnlyModelViewSet",
    "ViewSetMixin",
    "GenericViewSet",
    "ListAPIView",
    "RetrieveAPIView",
    "CreateAPIView",
    "UpdateAPIView",
    "DestroyAPIView",
    "ListCreateAPIView",
    "RetrieveUpdateAPIView",
    "RetrieveDestroyAPIView",
    "RetrieveUpdateDestroyAPIView",
}

# Django model base classes
_MODEL_BASES = {
    "Model",
    "AbstractUser",
    "AbstractBaseUser",
    "PermissionsMixin",
}

# DRF serializer base classes
_SERIALIZER_BASES = {
    "Serializer",
    "ModelSerializer",
    "HyperlinkedModelSerializer",
    "ListSerializer",
    "BaseSerializer",
}

# Django admin base classes
_ADMIN_BASES = {
    "ModelAdmin",
    "TabularInline",
    "StackedInline",
    "AdminSite",
}

# Django middleware detection: classes with specific methods
_MIDDLEWARE_METHODS = {
    "__call__",
    "process_request",
    "process_response",
    "process_view",
    "process_exception",
    "process_template_response",
}

# Signal receiver decorator
_SIGNAL_RECEIVER_RE = re.compile(
    r"@receiver\s*\(\s*(?P<signal>[\w\.]+)",
    re.MULTILINE,
)

# Signal connect call
_SIGNAL_CONNECT_RE = re.compile(
    r"(?P<signal>[\w\.]+)\.connect\s*\(\s*(?P<handler>[\w\.]+)",
    re.MULTILINE,
)

# admin.register decorator
_ADMIN_REGISTER_RE = re.compile(
    r"@(?:admin\.)?register\s*\(\s*(?P<models>[^\)]+)\)",
    re.MULTILINE,
)

# FBV decorators that indicate a view
_VIEW_DECORATORS = {
    "api_view",
    "login_required",
    "permission_required",
    "require_http_methods",
    "require_GET",
    "require_POST",
    "csrf_exempt",
    "csrf_protect",
    "never_cache",
    "cache_page",
    "vary_on_headers",
    "vary_on_cookie",
    "condition",
    "require_safe",
}

# Management command base class
_COMMAND_BASES = {"BaseCommand", "LabelCommand", "AppCommand"}

# DRF api_view decorator with methods
_API_VIEW_RE = re.compile(
    r"@api_view\s*\(\s*\[(?P<methods>[^\]]+)\]\s*\)",
    re.MULTILINE,
)

# Serializer Meta class model reference
_SERIALIZER_META_MODEL_RE = re.compile(
    r"class\s+Meta\s*:.*?model\s*=\s*(?P<model>[\w\.]+)",
    re.DOTALL,
)


class DjangoDetector(FrameworkDetector):
    """Detect Django framework patterns in Python projects."""

    @property
    def framework_name(self) -> str:
        return "django"

    def detect_framework(self, project_root: str) -> bool:
        """Check for Django project indicators.

        Detection strategy (any combination):
        1. manage.py at root or up to depth 2 + django in deps
        2. settings.py with INSTALLED_APPS + django in deps
        3. django in deps + wsgi.py/asgi.py with django references
        """
        has_django_dep = self._check_django_dependency(project_root)

        if not has_django_dep:
            return False

        # Check for manage.py at root or up to depth 2
        if os.path.isfile(os.path.join(project_root, "manage.py")):
            return True

        for root, dirs, files in os.walk(project_root):
            depth = root.replace(project_root, "").count(os.sep)
            if depth > 2:
                dirs.clear()
                continue
            if "manage.py" in files:
                return True
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d
                not in (
                    "node_modules",
                    "venv",
                    ".venv",
                    "__pycache__",
                    "env",
                    ".env",
                    ".tox",
                    "dist",
                    "build",
                )
            ]

        # Check for settings.py with INSTALLED_APPS
        for root, dirs, files in os.walk(project_root):
            depth = root.replace(project_root, "").count(os.sep)
            if depth > 3:
                dirs.clear()
                continue
            if "settings.py" in files:
                settings_path = os.path.join(root, "settings.py")
                try:
                    with open(settings_path, encoding="utf-8") as fh:
                        settings_content = fh.read()
                    if "INSTALLED_APPS" in settings_content:
                        return True
                except OSError:
                    pass
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d
                not in (
                    "node_modules",
                    "venv",
                    ".venv",
                    "__pycache__",
                    "env",
                    ".env",
                    ".tox",
                    "dist",
                    "build",
                )
            ]

        # Check for wsgi.py or asgi.py with django references
        for entry in ["wsgi.py", "asgi.py"]:
            for root, dirs, files in os.walk(project_root):
                depth = root.replace(project_root, "").count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                if entry in files:
                    fpath = os.path.join(root, entry)
                    try:
                        with open(fpath, encoding="utf-8") as fh:
                            wsgi_content = fh.read()
                        if "django" in wsgi_content.lower():
                            return True
                    except OSError:
                        pass
                dirs[:] = [
                    d
                    for d in dirs
                    if not d.startswith(".")
                    and d
                    not in (
                        "node_modules",
                        "venv",
                        ".venv",
                        "__pycache__",
                        "env",
                        ".env",
                        ".tox",
                        "dist",
                        "build",
                    )
                ]

        return False

    def _check_django_dependency(self, project_root: str) -> bool:
        """Check if django is listed as a dependency."""
        dep_files = [
            "requirements.txt",
            "requirements/base.txt",
            "requirements/production.txt",
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "Pipfile",
        ]
        for dep_file in dep_files:
            fpath = os.path.join(project_root, dep_file)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, encoding="utf-8") as fh:
                        dep_content = fh.read().lower()
                    if "django" in dep_content:
                        return True
                except OSError:
                    continue
        return False

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect per-file Django patterns from source code and parsed nodes."""
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        # Index class nodes by name for quick lookup
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        func_nodes = [n for n in nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)]
        method_nodes = [n for n in nodes if n.kind == NodeKind.METHOD]

        for cls in class_nodes:
            # Extract base class names from source around the class definition
            bases = self._extract_bases(cls, source_text)
            base_shorts = {b.rsplit(".", 1)[-1] for b in bases}

            # ── Models ────────────────────────────────────────
            if base_shorts & _MODEL_BASES or "models.Model" in bases:
                pattern = self._detect_model(cls, source_text, file_path)
                if pattern:
                    patterns.append(pattern)

            # ── Class-Based Views ─────────────────────────────
            elif base_shorts & _CBV_BASES:
                patterns.append(
                    self._make_controller_pattern(
                        cls,
                        file_path,
                        bases,
                        source_text,
                    )
                )

            # ── Serializers (DRF) ─────────────────────────────
            elif base_shorts & _SERIALIZER_BASES:
                patterns.append(
                    self._make_serializer_pattern(
                        cls,
                        file_path,
                        source_text,
                    )
                )

            # ── Admin ─────────────────────────────────────────
            elif base_shorts & _ADMIN_BASES:
                patterns.append(
                    self._make_admin_pattern(
                        cls,
                        file_path,
                        source_text,
                    )
                )

            # ── Middleware ────────────────────────────────────
            elif self._is_middleware_class(cls, method_nodes, source_text):
                patterns.append(self._make_middleware_pattern(cls, file_path))

            # ── Management Commands ───────────────────────────
            elif base_shorts & _COMMAND_BASES:
                patterns.append(self._make_command_pattern(cls, file_path))

        # ── Function-Based Views (decorated) ──────────────────
        for func in func_nodes:
            if func.kind != NodeKind.FUNCTION:
                continue
            if self._is_fbv(func, nodes, source_text):
                patterns.append(
                    self._make_fbv_pattern(
                        func,
                        file_path,
                        source_text,
                    )
                )

        # ── Signal receivers ──────────────────────────────────
        signal_patterns = self._detect_signals(source_text, file_path, func_nodes)
        patterns.extend(signal_patterns)

        # ── URL patterns (per-file) ───────────────────────────
        url_pattern = self._detect_url_patterns(source_text, file_path)
        if url_pattern:
            patterns.append(url_pattern)

        return patterns

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Django patterns (route tree, signal mappings)."""
        patterns: list[FrameworkPattern] = []

        project_root = self._infer_project_root(store)
        if not project_root:
            logger.warning("Could not infer project root for Django detection")
            return patterns

        # Build global route tree from urls.py files
        route_pattern = self._build_route_tree(store, project_root)
        if route_pattern:
            patterns.append(route_pattern)

        # Connect middleware chain from settings
        mw_pattern = self._extract_middleware_chain(store, project_root)
        if mw_pattern:
            patterns.append(mw_pattern)

        return patterns

    # ── Private helpers ───────────────────────────────────────

    def _infer_project_root(self, store: Any) -> str | None:
        """Infer project root from stored file paths."""
        nodes = store.find_nodes(kind=NodeKind.FILE, limit=5)
        if not nodes:
            return None
        for node in nodes:
            abs_path = os.path.abspath(node.file_path)
            parts = abs_path.split(os.sep)
            for i in range(len(parts), 0, -1):
                candidate = os.sep.join(parts[:i])
                if os.path.isfile(os.path.join(candidate, "manage.py")):
                    return candidate
        return None

    def _extract_bases(self, cls: Node, source_text: str) -> list[str]:
        """Extract base class names from source around the class definition line."""
        lines = source_text.splitlines()
        if cls.start_line < 1 or cls.start_line > len(lines):
            return []

        # Gather the class definition line(s) — may span multiple lines
        class_header = ""
        for i in range(cls.start_line - 1, min(cls.start_line + 4, len(lines))):
            class_header += lines[i]
            if ":" in lines[i]:
                break

        match = re.search(r"class\s+\w+\s*\(([^)]+)\)", class_header)
        if not match:
            return []

        bases_str = match.group(1)
        bases = [b.strip() for b in bases_str.split(",") if b.strip()]
        return bases

    def _get_class_source(self, cls: Node, source_text: str) -> str:
        """Extract source text for a class node."""
        if cls.source_text:
            return cls.source_text
        lines = source_text.splitlines()
        start = max(0, cls.start_line - 1)
        end = min(len(lines), cls.end_line)
        return "\n".join(lines[start:end])

    # ── Model detection ───────────────────────────────────────

    def _detect_model(
        self,
        cls: Node,
        source_text: str,
        file_path: str,
    ) -> FrameworkPattern | None:
        """Detect Django model and its fields/relationships."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        model_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.MODEL, cls.name),
            kind=NodeKind.MODEL,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="python",
            metadata={
                "framework": "django",
                "original_class_id": cls.id,
                "model_type": "django_orm",
            },
        )
        new_nodes.append(model_node)

        class_source = self._get_class_source(cls, source_text)

        # Detect regular fields
        for match in _DJANGO_FIELD_RE.finditer(class_source):
            field_name = match.group("field_name")
            field_type = match.group("field_type")
            line_no = cls.start_line + class_source[: match.start()].count("\n")

            prop_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.PROPERTY, f"{cls.name}.{field_name}"),
                kind=NodeKind.PROPERTY,
                name=field_name,
                qualified_name=f"{cls.qualified_name}.{field_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={
                    "framework": "django",
                    "field_type": field_type,
                    "model_field": True,
                },
            )
            new_nodes.append(prop_node)
            new_edges.append(
                Edge(
                    source_id=model_node.id,
                    target_id=prop_node.id,
                    kind=EdgeKind.CONTAINS,
                    confidence=1.0,
                    line_number=line_no,
                    metadata={"framework": "django"},
                )
            )

        # Detect relationship fields
        for match in _DJANGO_RELATION_RE.finditer(class_source):
            field_name = match.group("field_name")
            rel_type = match.group("rel_type")
            related = match.group("related")
            line_no = cls.start_line + class_source[: match.start()].count("\n")

            # Clean up related model name
            related_name = related.strip("'\"").rsplit(".", 1)[-1]
            if related_name == "self":
                related_name = cls.name

            prop_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.PROPERTY, f"{cls.name}.{field_name}"),
                kind=NodeKind.PROPERTY,
                name=field_name,
                qualified_name=f"{cls.qualified_name}.{field_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={
                    "framework": "django",
                    "field_type": rel_type,
                    "related_model": related_name,
                    "relationship": True,
                },
            )
            new_nodes.append(prop_node)
            new_edges.append(
                Edge(
                    source_id=model_node.id,
                    target_id=prop_node.id,
                    kind=EdgeKind.CONTAINS,
                    confidence=1.0,
                    line_number=line_no,
                    metadata={"framework": "django"},
                )
            )

            # Add DEPENDS_ON edge to related model (unresolved)
            new_edges.append(
                Edge(
                    source_id=model_node.id,
                    target_id=f"__unresolved__:model:{related_name}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.75,
                    line_number=line_no,
                    metadata={
                        "framework": "django",
                        "relationship_type": rel_type,
                        "related_model": related_name,
                    },
                )
            )

        return FrameworkPattern(
            framework_name="django",
            pattern_type="model",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"model_name": cls.qualified_name},
        )

    # ── View detection ────────────────────────────────────────

    def _make_controller_pattern(
        self,
        cls: Node,
        file_path: str,
        bases: list[str],
        source_text: str,
    ) -> FrameworkPattern:
        """Create a controller pattern for a class-based view."""
        base_shorts = {b.rsplit(".", 1)[-1] for b in bases}
        is_drf = bool(
            base_shorts
            & {
                "APIView",
                "GenericAPIView",
                "ViewSet",
                "ModelViewSet",
                "ReadOnlyModelViewSet",
                "ViewSetMixin",
                "GenericViewSet",
                "ListAPIView",
                "RetrieveAPIView",
                "CreateAPIView",
                "UpdateAPIView",
                "DestroyAPIView",
                "ListCreateAPIView",
                "RetrieveUpdateAPIView",
                "RetrieveDestroyAPIView",
                "RetrieveUpdateDestroyAPIView",
            }
        )

        view_type = "drf_viewset" if "ViewSet" in str(base_shorts) else ("drf_apiview" if is_drf else "cbv")

        ctrl_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.CONTROLLER, cls.name),
            kind=NodeKind.CONTROLLER,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="python",
            metadata={
                "framework": "django",
                "original_class_id": cls.id,
                "view_type": view_type,
                "base_classes": bases,
            },
        )
        return FrameworkPattern(
            framework_name="django",
            pattern_type="controller",
            nodes=[ctrl_node],
            edges=[],
            metadata={"controller_name": cls.qualified_name, "view_type": view_type},
        )

    def _is_fbv(
        self,
        func: Node,
        all_nodes: list[Node],
        source_text: str,
    ) -> bool:
        """Check if a function is a Django function-based view."""
        # Check for view-related decorators
        decorators = [
            n
            for n in all_nodes
            if n.kind == NodeKind.DECORATOR and n.start_line < func.start_line and n.start_line >= func.start_line - 5
        ]
        for dec in decorators:
            dec_name = dec.name.rsplit(".", 1)[-1]
            if dec_name in _VIEW_DECORATORS:
                return True

        # Check source for @api_view decorator above function
        lines = source_text.splitlines()
        start = max(0, func.start_line - 6)
        end = func.start_line
        context = "\n".join(lines[start:end])
        if _API_VIEW_RE.search(context):
            return True

        return False

    def _make_fbv_pattern(
        self,
        func: Node,
        file_path: str,
        source_text: str,
    ) -> FrameworkPattern:
        """Create a controller pattern for a function-based view."""
        # Try to extract HTTP methods from @api_view decorator
        http_methods: list[str] = []
        lines = source_text.splitlines()
        start = max(0, func.start_line - 6)
        end = func.start_line
        context = "\n".join(lines[start:end])
        api_match = _API_VIEW_RE.search(context)
        if api_match:
            methods_str = api_match.group("methods")
            http_methods = [m.strip().strip("'\"") for m in methods_str.split(",")]

        ctrl_node = Node(
            id=generate_node_id(file_path, func.start_line, NodeKind.CONTROLLER, func.name),
            kind=NodeKind.CONTROLLER,
            name=func.name,
            qualified_name=func.qualified_name,
            file_path=file_path,
            start_line=func.start_line,
            end_line=func.end_line,
            language="python",
            metadata={
                "framework": "django",
                "original_func_id": func.id,
                "view_type": "fbv",
                "http_methods": http_methods or ["GET"],
            },
        )
        return FrameworkPattern(
            framework_name="django",
            pattern_type="controller",
            nodes=[ctrl_node],
            edges=[],
            metadata={"controller_name": func.qualified_name, "view_type": "fbv"},
        )

    # ── Serializer detection ──────────────────────────────────

    def _make_serializer_pattern(
        self,
        cls: Node,
        file_path: str,
        source_text: str,
    ) -> FrameworkPattern:
        """Create a pattern for a DRF serializer."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        ser_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.CLASS, f"serializer:{cls.name}"),
            kind=NodeKind.CLASS,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="python",
            metadata={
                "framework": "django",
                "original_class_id": cls.id,
                "serializer": True,
                "component_type": "serializer",
            },
        )
        new_nodes.append(ser_node)

        # Try to find Meta.model reference
        class_source = self._get_class_source(cls, source_text)
        meta_match = _SERIALIZER_META_MODEL_RE.search(class_source)
        if meta_match:
            model_name = meta_match.group("model").rsplit(".", 1)[-1]
            new_edges.append(
                Edge(
                    source_id=ser_node.id,
                    target_id=f"__unresolved__:model:{model_name}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.80,
                    metadata={
                        "framework": "django",
                        "relationship": "serializes",
                        "model_name": model_name,
                    },
                )
            )

        return FrameworkPattern(
            framework_name="django",
            pattern_type="serializer",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"serializer_name": cls.qualified_name},
        )

    # ── Admin detection ───────────────────────────────────────

    def _make_admin_pattern(
        self,
        cls: Node,
        file_path: str,
        source_text: str,
    ) -> FrameworkPattern:
        """Create a pattern for a Django admin class."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        admin_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.CLASS, f"admin:{cls.name}"),
            kind=NodeKind.CLASS,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="python",
            metadata={
                "framework": "django",
                "original_class_id": cls.id,
                "admin": True,
                "component_type": "admin",
            },
        )
        new_nodes.append(admin_node)

        # Check for @admin.register(Model) decorator
        lines = source_text.splitlines()
        start = max(0, cls.start_line - 5)
        end = cls.start_line
        context = "\n".join(lines[start:end])
        reg_match = _ADMIN_REGISTER_RE.search(context)
        if reg_match:
            models_str = reg_match.group("models")
            for model_ref in models_str.split(","):
                model_name = model_ref.strip().rsplit(".", 1)[-1]
                if model_name:
                    new_edges.append(
                        Edge(
                            source_id=admin_node.id,
                            target_id=f"__unresolved__:model:{model_name}",
                            kind=EdgeKind.DEPENDS_ON,
                            confidence=0.85,
                            metadata={
                                "framework": "django",
                                "relationship": "registers_admin",
                                "model_name": model_name,
                            },
                        )
                    )

        return FrameworkPattern(
            framework_name="django",
            pattern_type="admin",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"admin_name": cls.qualified_name},
        )

    # ── Middleware detection ───────────────────────────────────

    def _is_middleware_class(
        self,
        cls: Node,
        method_nodes: list[Node],
        source_text: str,
    ) -> bool:
        """Check if a class is a Django middleware."""
        # Check if class has middleware-specific methods
        cls_methods = {
            m.name
            for m in method_nodes
            if m.file_path == cls.file_path and cls.start_line <= m.start_line <= cls.end_line
        }
        if cls_methods & _MIDDLEWARE_METHODS:
            return True

        # Check if "Middleware" is in the class name or path
        if "middleware" in cls.name.lower() or "middleware" in cls.file_path.lower():
            if "__call__" in cls_methods or "__init__" in cls_methods:
                return True

        return False

    def _make_middleware_pattern(self, cls: Node, file_path: str) -> FrameworkPattern:
        mw_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.MIDDLEWARE, cls.name),
            kind=NodeKind.MIDDLEWARE,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="python",
            metadata={"framework": "django", "original_class_id": cls.id},
        )
        return FrameworkPattern(
            framework_name="django",
            pattern_type="middleware",
            nodes=[mw_node],
            edges=[],
            metadata={"middleware_name": cls.qualified_name},
        )

    # ── Management command detection ──────────────────────────

    def _make_command_pattern(self, cls: Node, file_path: str) -> FrameworkPattern:
        cmd_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.FUNCTION, f"command:{cls.name}"),
            kind=NodeKind.FUNCTION,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="python",
            metadata={
                "framework": "django",
                "original_class_id": cls.id,
                "management_command": True,
                "component_type": "management_command",
            },
        )
        return FrameworkPattern(
            framework_name="django",
            pattern_type="management_command",
            nodes=[cmd_node],
            edges=[],
            metadata={"command_name": cls.qualified_name},
        )

    # ── Signal detection ──────────────────────────────────────

    def _detect_signals(
        self,
        source_text: str,
        file_path: str,
        func_nodes: list[Node],
    ) -> list[FrameworkPattern]:
        """Detect signal receivers and connections."""
        patterns: list[FrameworkPattern] = []

        # @receiver(signal) decorators
        for match in _SIGNAL_RECEIVER_RE.finditer(source_text):
            signal_name = match.group("signal").rsplit(".", 1)[-1]
            line_no = source_text[: match.start()].count("\n") + 1

            # Find the function below this decorator
            handler = self._find_func_near_line(line_no, func_nodes, file_path)
            if not handler:
                continue

            event_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.EVENT, signal_name),
                kind=NodeKind.EVENT,
                name=signal_name,
                qualified_name=f"signal:{signal_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={"framework": "django", "signal_type": "receiver"},
            )

            listener_node = Node(
                id=generate_node_id(file_path, handler.start_line, NodeKind.LISTENER, handler.name),
                kind=NodeKind.LISTENER,
                name=handler.name,
                qualified_name=handler.qualified_name,
                file_path=file_path,
                start_line=handler.start_line,
                end_line=handler.end_line,
                language="python",
                metadata={
                    "framework": "django",
                    "original_func_id": handler.id,
                    "signal": signal_name,
                },
            )

            edge = Edge(
                source_id=listener_node.id,
                target_id=event_node.id,
                kind=EdgeKind.LISTENS_TO,
                confidence=0.90,
                line_number=line_no,
                metadata={"framework": "django", "signal": signal_name},
            )

            patterns.append(
                FrameworkPattern(
                    framework_name="django",
                    pattern_type="signal",
                    nodes=[event_node, listener_node],
                    edges=[edge],
                    metadata={"signal_name": signal_name, "handler": handler.name},
                )
            )

        # signal.connect(handler) calls
        for match in _SIGNAL_CONNECT_RE.finditer(source_text):
            signal_name = match.group("signal").rsplit(".", 1)[-1]
            handler_name = match.group("handler").rsplit(".", 1)[-1]
            line_no = source_text[: match.start()].count("\n") + 1

            event_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.EVENT, signal_name),
                kind=NodeKind.EVENT,
                name=signal_name,
                qualified_name=f"signal:{signal_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={"framework": "django", "signal_type": "connect"},
            )

            edge = Edge(
                source_id=f"__unresolved__:func:{handler_name}",
                target_id=event_node.id,
                kind=EdgeKind.LISTENS_TO,
                confidence=0.75,
                line_number=line_no,
                metadata={"framework": "django", "signal": signal_name},
            )

            patterns.append(
                FrameworkPattern(
                    framework_name="django",
                    pattern_type="signal",
                    nodes=[event_node],
                    edges=[edge],
                    metadata={"signal_name": signal_name, "handler": handler_name},
                )
            )

        return patterns

    def _find_func_near_line(
        self,
        line_no: int,
        func_nodes: list[Node],
        file_path: str,
    ) -> Node | None:
        """Find the function defined closest after the given line."""
        closest = None
        closest_dist = float("inf")
        for fn in func_nodes:
            if fn.file_path == file_path and fn.start_line >= line_no:
                dist = fn.start_line - line_no
                if dist < closest_dist and dist <= 5:
                    closest = fn
                    closest_dist = dist
        return closest

    # ── URL pattern detection ─────────────────────────────────

    def _detect_url_patterns(
        self,
        source_text: str,
        file_path: str,
    ) -> FrameworkPattern | None:
        """Detect URL patterns in a single file."""
        if "urlpatterns" not in source_text:
            return None

        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        for match in _URL_PATTERN_RE.finditer(source_text):
            pattern = match.group("pattern")
            view_ref = match.group("view").strip()
            line_no = source_text[: match.start()].count("\n") + 1

            # Determine HTTP method (Django URLs are method-agnostic by default)
            route_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.ROUTE, pattern),
                kind=NodeKind.ROUTE,
                name=pattern or "/",
                qualified_name=f"URL {pattern}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={
                    "framework": "django",
                    "url_pattern": pattern,
                    "view_ref": view_ref,
                    "http_method": "ANY",
                },
            )
            new_nodes.append(route_node)

            # Try to resolve view reference
            view_name = self._extract_view_name(view_ref)
            if view_name:
                new_edges.append(
                    Edge(
                        source_id=route_node.id,
                        target_id=f"__unresolved__:view:{view_name}",
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.80,
                        line_number=line_no,
                        metadata={
                            "framework": "django",
                            "url_pattern": pattern,
                            "view_ref": view_ref,
                        },
                    )
                )

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="django",
            pattern_type="routes",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"route_count": len(new_nodes)},
        )

    def _extract_view_name(self, view_ref: str) -> str | None:
        """Extract a view name from a URL pattern view reference."""
        ref = view_ref.strip()
        # views.MyView.as_view() → MyView
        as_view_match = re.search(r"(\w+)\.as_view\(", ref)
        if as_view_match:
            return as_view_match.group(1)
        # views.my_view → my_view
        dot_match = re.search(r"(\w+)$", ref.split("(")[0])
        if dot_match:
            return dot_match.group(1)
        return None

    # ── Global pattern helpers ────────────────────────────────

    def _build_route_tree(
        self,
        store: Any,
        project_root: str,
    ) -> FrameworkPattern | None:
        """Build a global route tree from all urls.py files."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        # Find all urls.py files
        url_files: list[str] = []
        for root, _dirs, files in os.walk(project_root):
            for fname in files:
                if fname == "urls.py":
                    url_files.append(os.path.join(root, fname))

        for url_file in url_files:
            try:
                with open(url_file, encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue

            rel_path = os.path.relpath(url_file, project_root)

            # Detect include() patterns for route tree
            for match in _URL_INCLUDE_RE.finditer(content):
                prefix = match.group("prefix")
                module = match.group("module")
                line_no = content[: match.start()].count("\n") + 1

                route_node = Node(
                    id=generate_node_id(rel_path, line_no, NodeKind.ROUTE, f"include:{prefix}"),
                    kind=NodeKind.ROUTE,
                    name=f"include({module})",
                    qualified_name=f"URL include {prefix} → {module}",
                    file_path=rel_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="python",
                    metadata={
                        "framework": "django",
                        "url_pattern": prefix,
                        "include_module": module,
                        "route_type": "include",
                    },
                )
                new_nodes.append(route_node)

            # Detect direct URL patterns and resolve views via store
            for match in _URL_PATTERN_RE.finditer(content):
                pattern = match.group("pattern")
                view_ref = match.group("view").strip()
                line_no = content[: match.start()].count("\n") + 1

                route_node = Node(
                    id=generate_node_id(rel_path, line_no, NodeKind.ROUTE, pattern),
                    kind=NodeKind.ROUTE,
                    name=pattern or "/",
                    qualified_name=f"URL {pattern}",
                    file_path=rel_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="python",
                    metadata={
                        "framework": "django",
                        "url_pattern": pattern,
                        "view_ref": view_ref,
                        "http_method": "ANY",
                    },
                )
                new_nodes.append(route_node)

                # Try to resolve view via store
                view_name = self._extract_view_name(view_ref)
                if view_name:
                    target_id = self._resolve_view(view_name, store)
                    if target_id:
                        new_edges.append(
                            Edge(
                                source_id=route_node.id,
                                target_id=target_id,
                                kind=EdgeKind.ROUTES_TO,
                                confidence=0.85,
                                line_number=line_no,
                                metadata={
                                    "framework": "django",
                                    "url_pattern": pattern,
                                },
                            )
                        )

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="django",
            pattern_type="routes",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"route_count": len(new_nodes), "source": "global"},
        )

    def _resolve_view(
        self,
        view_name: str,
        store: Any,
    ) -> str | None:
        """Resolve a view name to a node ID via the store."""
        # Try controller nodes first
        ctrl_nodes = store.find_nodes(
            kind=NodeKind.CONTROLLER,
            name_pattern=view_name,
            limit=10,
        )
        for cn in ctrl_nodes:
            if cn.name == view_name:
                return cn.id

        # Try class nodes
        class_nodes = store.find_nodes(
            kind=NodeKind.CLASS,
            name_pattern=view_name,
            limit=10,
        )
        for cn in class_nodes:
            if cn.name == view_name:
                return cn.id

        # Try function nodes
        func_nodes = store.find_nodes(
            kind=NodeKind.FUNCTION,
            name_pattern=view_name,
            limit=10,
        )
        for fn in func_nodes:
            if fn.name == view_name:
                return fn.id

        return None

    def _extract_middleware_chain(
        self,
        store: Any,
        project_root: str,
    ) -> FrameworkPattern | None:
        """Extract middleware chain from Django settings."""
        # Find settings.py
        settings_files: list[str] = []
        for root, _dirs, files in os.walk(project_root):
            for fname in files:
                if fname == "settings.py" or fname == "base.py":
                    fpath = os.path.join(root, fname)
                    if "settings" in fpath.lower():
                        settings_files.append(fpath)

        if not settings_files:
            return None

        middleware_re = re.compile(
            r"MIDDLEWARE\s*=\s*\[([^\]]+)\]",
            re.DOTALL,
        )

        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        for settings_file in settings_files:
            try:
                with open(settings_file, encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue

            match = middleware_re.search(content)
            if not match:
                continue

            rel_path = os.path.relpath(settings_file, project_root)
            mw_list_str = match.group(1)
            mw_entries = re.findall(r"[\'\"]([^\'\"]+)[\'\"]", mw_list_str)

            prev_node = None
            for idx, mw_path in enumerate(mw_entries):
                mw_name = mw_path.rsplit(".", 1)[-1]
                line_no = content[: match.start()].count("\n") + 1 + idx

                mw_node = Node(
                    id=generate_node_id(rel_path, line_no, NodeKind.MIDDLEWARE, mw_name),
                    kind=NodeKind.MIDDLEWARE,
                    name=mw_name,
                    qualified_name=mw_path,
                    file_path=rel_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="python",
                    metadata={
                        "framework": "django",
                        "middleware_path": mw_path,
                        "order": idx,
                    },
                )
                new_nodes.append(mw_node)

                # Chain middleware in order
                if prev_node:
                    new_edges.append(
                        Edge(
                            source_id=prev_node.id,
                            target_id=mw_node.id,
                            kind=EdgeKind.DEPENDS_ON,
                            confidence=0.90,
                            metadata={
                                "framework": "django",
                                "relationship": "middleware_chain",
                            },
                        )
                    )
                prev_node = mw_node

            break  # Use first settings file found

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="django",
            pattern_type="middleware_chain",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"middleware_count": len(new_nodes)},
        )
