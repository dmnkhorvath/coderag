"""Symfony framework detector for CodeRAG.

Detects Symfony-specific patterns including PHP 8 attribute routes,
Doctrine ORM entities, dependency injection, Twig template references,
event system, form types, console commands, and security voters.
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
# Regex patterns for Symfony detection
# =============================================================================

# ---------------------------------------------------------------------------
# Controller detection
# ---------------------------------------------------------------------------
_EXTENDS_CONTROLLER_RE = re.compile(r"class\s+(?P<name>\w+)\s+extends\s+(?:Abstract)?Controller\b")

# ---------------------------------------------------------------------------
# PHP 8 Attribute Route detection
# ---------------------------------------------------------------------------
_ROUTE_ATTR_RE = re.compile(r"""#\[Route\s*\(\s*['"](?P<path>[^'"]+)['"](?P<rest>.*?)\)\s*\]""")
_ROUTE_NAME_RE = re.compile(r"""name\s*:\s*['"](?P<name>[^'"]+)['"]""")
_ROUTE_METHODS_RE = re.compile(r"""methods\s*:\s*\[(?P<methods>[^\]]*)\]""")

# ---------------------------------------------------------------------------
# Doctrine ORM Entity detection (PHP 8 attributes)
# ---------------------------------------------------------------------------
_ENTITY_ATTR_RE = re.compile(r"#\[(?:ORM\\)?Entity(?:\s*\([^)]*\))?\]")
_TABLE_ATTR_RE = re.compile(r"""#\[(?:ORM\\)?Table\s*\(\s*name\s*:\s*['"](?P<name>[^'"]+)['"]\)""")
_COLUMN_ATTR_RE = re.compile(r"#\[(?:ORM\\)?Column\s*\((?P<args>[^)]*)\)\]")
_ID_ATTR_RE = re.compile(r"#\[(?:ORM\\)?Id\]")
_RELATION_ATTR_RE = re.compile(
    r"""#\[(?:ORM\\)?(?P<type>OneToMany|ManyToOne|ManyToMany|OneToOne)\s*\(\s*targetEntity\s*:\s*(?P<target>\w+)(?:::class)?"""
)
_RELATION_ATTR_V2_RE = re.compile(
    r"""#\[(?:ORM\\)?(?P<type>OneToMany|ManyToOne|ManyToMany|OneToOne)\s*\([^)]*targetEntity\s*:\s*(?P<target>\w+)(?:::class)?"""
)
_REPOSITORY_CLASS_RE = re.compile(r"""repositoryClass\s*:\s*(?P<repo>\w+)(?:::class)?""")

# ---------------------------------------------------------------------------
# Entity class detection (for class name extraction)
# ---------------------------------------------------------------------------
_ENTITY_CLASS_RE = re.compile(r"class\s+(?P<name>\w+)")

# ---------------------------------------------------------------------------
# Service / Dependency Injection detection
# ---------------------------------------------------------------------------
_CONSTRUCTOR_INJECT_RE = re.compile(
    r"(?:private|public|protected|readonly)\s+(?:readonly\s+)?(?P<type>[A-Z]\w+)\s+\$(?P<param>\w+)"
)
_AUTOWIRE_ATTR_RE = re.compile(r"#\[Autowire\s*\((?P<args>[^)]*)\)\]")
_TAGGED_ITERATOR_RE = re.compile(r"""#\[TaggedIterator\s*\(['"](?P<tag>[^'"]+)['"]\)\]""")

# ---------------------------------------------------------------------------
# Twig template references in controllers
# ---------------------------------------------------------------------------
_RENDER_TEMPLATE_RE = re.compile(r"""\$this->render\s*\(\s*['"](?P<template>[^'"]+)['"]""")
_TEMPLATE_ATTR_RE = re.compile(r"""#\[Template\s*\(\s*['"](?P<template>[^'"]+)['"]\s*\)\]""")

# ---------------------------------------------------------------------------
# Event system detection
# ---------------------------------------------------------------------------
_EVENT_LISTENER_ATTR_RE = re.compile(r"""#\[AsEventListener\s*\((?:[^)]*event\s*:\s*)?['"]?(?P<event>[\w.]+)['"]?""")
_EVENT_SUBSCRIBER_RE = re.compile(r"implements\s+[^{]*EventSubscriberInterface")
_DISPATCH_EVENT_RE = re.compile(r"->dispatch\s*\(\s*new\s+(?P<event>\w+)\s*\(")

# ---------------------------------------------------------------------------
# Form type detection
# ---------------------------------------------------------------------------
_FORM_TYPE_RE = re.compile(r"class\s+(?P<name>\w+)\s+extends\s+AbstractType\b")

# ---------------------------------------------------------------------------
# Console command detection
# ---------------------------------------------------------------------------
_COMMAND_RE = re.compile(r"class\s+(?P<name>\w+)\s+extends\s+Command\b")
_AS_COMMAND_ATTR_RE = re.compile(r"""#\[AsCommand\s*\([^)]*name\s*:\s*['"](?P<name>[^'"]+)['"]""")

# ---------------------------------------------------------------------------
# Security detection
# ---------------------------------------------------------------------------
_IS_GRANTED_RE = re.compile(r"""#\[IsGranted\s*\(\s*['"](?P<role>[^'"]+)['"]""")
_VOTER_RE = re.compile(r"class\s+(?P<name>\w+)\s+extends\s+Voter\b")

# ---------------------------------------------------------------------------
# PHP method detection (fallback when AST nodes unavailable)
# ---------------------------------------------------------------------------
_PHP_METHOD_RE = re.compile(r"(?:public|protected|private)\s+function\s+(?P<name>\w+)\s*\(")

# ---------------------------------------------------------------------------
# Namespace detection
# ---------------------------------------------------------------------------
_NAMESPACE_RE = re.compile(r"namespace\s+(?P<ns>[\w\\]+)\s*;")


# ---------------------------------------------------------------------------
# Twig template patterns (for .twig file analysis)
# ---------------------------------------------------------------------------
_TWIG_EXTENDS_RE = re.compile(r"""{%\s*extends\s+['"](?P<template>[^'"]+)['"]\s*%}""")
_TWIG_INCLUDE_RE = re.compile(r"""{%\s*include\s+['"](?P<template>[^'"]+)['"]""")
_TWIG_EMBED_RE = re.compile(r"""{%\s*embed\s+['"](?P<template>[^'"]+)['"]""")
_TWIG_IMPORT_MACRO_RE = re.compile(r"""{%\s*from\s+['"](?P<template>[^'"]+)['"]\s+import\s+(?P<macros>[^%]+)%}""")
_TWIG_RENDER_CONTROLLER_RE = re.compile(r"""{{\s*render\s*\(\s*controller\s*\(\s*['"](?P<controller>[^'"]+)['"]""")
_TWIG_PATH_RE = re.compile(r"""(?:path|url)\s*\(\s*['"](?P<route>[^'"]+)['"]""")

# ---------------------------------------------------------------------------
# Stimulus & Asset patterns (for .twig file analysis)
# ---------------------------------------------------------------------------
_STIMULUS_DATA_CONTROLLER_RE = re.compile(r"""data-controller\s*=\s*['"](?P<controllers>[^'"]+)['"]""")
_STIMULUS_FUNCTION_RE = re.compile(r"""stimulus_controller\s*\(\s*['"](?P<controller>[^'"]+)['"]""")
_ASSET_ENCORE_RE = re.compile(
    r"""(?:encore_entry_link_tags|encore_entry_script_tags)\s*\(\s*['"](?P<entry>[^'"]+)['"]"""
)
_ASSET_VITE_RE = re.compile(r"""(?:vite_entry_link_tags|vite_entry_script_tags)\s*\(\s*['"](?P<entry>[^'"]+)['"]""")

# ---------------------------------------------------------------------------
# Validation constraint patterns (for PHP entity files)
# ---------------------------------------------------------------------------
_ASSERT_ATTR_RE = re.compile(r"""#\[Assert\\(?P<constraint>\w+)(?:\s*\([^)]*\))?\]""")

# ---------------------------------------------------------------------------
# Bundle detection
# ---------------------------------------------------------------------------
_BUNDLE_RE = re.compile(r"""class\s+(?P<name>\w+)\s+extends\s+(?:Abstract)?Bundle\b""")

# ---------------------------------------------------------------------------
# Form data_class and builder->add patterns
# ---------------------------------------------------------------------------
_DATA_CLASS_RE = re.compile(r"""data_class['"]?\s*(?:=>|:)\s*(?P<entity>\w+)::class""")
_BUILDER_ADD_RE = re.compile(r"""(?:\$builder)?->add\s*\(\s*['"](?P<field>\w+)['"]""")

# ---------------------------------------------------------------------------
# Voter supports() entity detection
# ---------------------------------------------------------------------------
_VOTER_SUPPORTS_INSTANCEOF_RE = re.compile(r"""\$\w+\s+instanceof\s+(?P<entity>\w+)""")

# =============================================================================
# Symfony Detector
# =============================================================================


class SymfonyDetector(FrameworkDetector):
    """Detect Symfony framework patterns in PHP projects.

    Identifies controllers, routes (PHP 8 attributes), Doctrine ORM
    entities, dependency injection, Twig template references, event
    listeners/subscribers, form types, console commands, and security
    voters/grants.
    """

    # -- FrameworkDetector interface ----------------------------------------

    @property
    def framework_name(self) -> str:
        return "symfony"

    def detect_framework(self, project_root: str) -> bool:
        """Check if this is a Symfony project.

        Looks for:
        1. ``symfony.lock`` in project root (Flex recipe lock)
        2. ``config/bundles.php`` (bundle registration)
        3. ``symfony/framework-bundle`` in composer.json require/require-dev
        """
        # Signal 1: symfony.lock
        if os.path.isfile(os.path.join(project_root, "symfony.lock")):
            return True

        # Signal 2: config/bundles.php
        if os.path.isfile(os.path.join(project_root, "config", "bundles.php")):
            return True

        # Signal 3: composer.json dependency
        composer_path = os.path.join(project_root, "composer.json")
        if os.path.isfile(composer_path):
            try:
                with open(composer_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                all_deps: dict[str, str] = {}
                all_deps.update(data.get("require", {}))
                all_deps.update(data.get("require-dev", {}))
                if "symfony/framework-bundle" in all_deps:
                    return True
            except (json.JSONDecodeError, OSError):
                pass

        return False

    # ------------------------------------------------------------------
    # Main per-file detection
    # ------------------------------------------------------------------

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect Symfony patterns in a single PHP file."""
        patterns: list[FrameworkPattern] = []

        # Process PHP and Twig files
        if not file_path.endswith((".php", ".twig")):
            return patterns

        source_text = source.decode("utf-8", errors="replace")

        # Twig template file analysis
        if file_path.endswith(".twig"):
            twig = self._detect_twig_template_patterns(file_path, source_text)
            if twig:
                patterns.append(twig)
            return patterns

        # Controller detection
        ctrl = self._detect_controller(file_path, nodes, source_text)
        if ctrl:
            patterns.append(ctrl)

        # Route detection (PHP 8 attributes)
        routes = self._detect_routes(file_path, nodes, source_text)
        if routes:
            patterns.append(routes)

        # Entity detection (Doctrine ORM)
        entity = self._detect_entity(file_path, nodes, source_text)
        if entity:
            patterns.append(entity)

        # Dependency injection
        di = self._detect_dependency_injection(file_path, nodes, source_text)
        if di:
            patterns.append(di)

        # Template references
        tpl = self._detect_template_references(file_path, nodes, source_text)
        if tpl:
            patterns.append(tpl)

        # Event system
        events = self._detect_events(file_path, nodes, source_text)
        if events:
            patterns.append(events)

        # Form types
        forms = self._detect_form_types(file_path, nodes, source_text)
        if forms:
            patterns.append(forms)

        # Console commands
        cmds = self._detect_commands(file_path, nodes, source_text)
        if cmds:
            patterns.append(cmds)

        # Security
        sec = self._detect_security(file_path, nodes, source_text)
        if sec:
            patterns.append(sec)

        # Validation constraints
        val = self._detect_validation(file_path, nodes, source_text)
        if val:
            patterns.append(val)

        # Bundle detection
        bun = self._detect_bundles(file_path, nodes, source_text)
        if bun:
            patterns.append(bun)

        return patterns

    # ------------------------------------------------------------------
    # Global patterns (cross-file)
    # ------------------------------------------------------------------

    def detect_global_patterns(
        self,
        store: Any,
    ) -> list[FrameworkPattern]:
        """Detect cross-file Symfony patterns.

        Currently returns an empty list. Future enhancements could
        resolve Twig template inheritance chains, event-listener
        wiring from ``services.yaml``, and route-controller mapping
        from YAML route configuration.
        """
        return []

    # ==================================================================
    # Helper utilities
    # ==================================================================

    @staticmethod
    def _find_enclosing_class(line_no: int, nodes: list[Node]) -> Node | None:
        """Return the narrowest CLASS node enclosing *line_no*."""
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
        return min(candidates, key=lambda n: (n.end_line or 0) - (n.start_line or 0))

    @staticmethod
    def _find_method_after_line(
        line_no: int,
        nodes: list[Node],
        max_gap: int = 5,
    ) -> Node | None:
        """Find the METHOD node declared within *max_gap* lines after *line_no*."""
        candidates = [
            n
            for n in nodes
            if n.kind == NodeKind.METHOD
            and n.start_line is not None
            and n.start_line >= line_no
            and n.start_line <= line_no + max_gap
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda n: n.start_line or 0)

    @staticmethod
    def _find_method_after_line_regex(
        line_no: int,
        source_text: str,
        file_path: str,
        max_gap: int = 5,
    ) -> tuple[str | None, int | None]:
        """Regex fallback: find the next ``function`` declaration after *line_no*.

        Returns ``(method_name, method_line)`` or ``(None, None)``.
        """
        lines = source_text.splitlines()
        for offset in range(0, max_gap + 1):
            idx = line_no - 1 + offset  # 0-based index
            if idx < 0 or idx >= len(lines):
                continue
            m = _PHP_METHOD_RE.search(lines[idx])
            if m:
                return m.group("name"), idx + 1  # 1-based line
        return None, None

    @staticmethod
    def _extract_namespace(source_text: str) -> str:
        """Extract the PHP namespace from source text."""
        m = _NAMESPACE_RE.search(source_text)
        return m.group("ns") if m else ""

    @staticmethod
    def _qualified_name(namespace: str, name: str) -> str:
        """Build a fully-qualified class name."""
        if namespace:
            return f"{namespace}\\{name}"
        return name

    # ==================================================================
    # Detection methods
    # ==================================================================

    # ------------------------------------------------------------------
    # 2a. Controller detection
    # ------------------------------------------------------------------

    def _detect_controller(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect classes extending AbstractController or Controller."""
        m = _EXTENDS_CONTROLLER_RE.search(source_text)
        if not m:
            return None

        class_name = m.group("name")
        namespace = self._extract_namespace(source_text)
        qualified = self._qualified_name(namespace, class_name)
        line_no = source_text[: m.start()].count("\n") + 1

        # Try to find the class node from AST
        cls_node = self._find_enclosing_class(line_no, nodes)
        start_line = cls_node.start_line if cls_node else line_no
        end_line = cls_node.end_line if cls_node else line_no

        ctrl_node = Node(
            id=generate_node_id(file_path, start_line, NodeKind.CONTROLLER, class_name),
            kind=NodeKind.CONTROLLER,
            name=class_name,
            qualified_name=qualified,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            language="php",
            metadata={
                "framework": "symfony",
                "symfony_type": "controller",
                "original_class_id": cls_node.id if cls_node else None,
            },
        )

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="controller",
            nodes=[ctrl_node],
            edges=[],
            metadata={"controller_name": qualified},
        )

    # ------------------------------------------------------------------
    # 2b. Route detection (PHP 8 attributes)
    # ------------------------------------------------------------------

    def _detect_routes(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect #[Route(...)] attributes and link to handler methods."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        for m in _ROUTE_ATTR_RE.finditer(source_text):
            path = m.group("path")
            rest = m.group("rest")
            line_no = source_text[: m.start()].count("\n") + 1

            # Extract optional name
            name_match = _ROUTE_NAME_RE.search(rest)
            route_name = name_match.group("name") if name_match else ""

            # Extract optional methods
            methods_match = _ROUTE_METHODS_RE.search(rest)
            methods: list[str] = []
            if methods_match:
                raw = methods_match.group("methods")
                methods = re.findall(r"['\"]([A-Z]+)['\"]", raw)

            route_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.ROUTE, route_name or path),
                kind=NodeKind.ROUTE,
                name=route_name or path,
                qualified_name=route_name or path,
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="php",
                metadata={
                    "framework": "symfony",
                    "symfony_type": "route",
                    "path": path,
                    "route_name": route_name,
                    "methods": methods,
                },
            )
            new_nodes.append(route_node)

            # Find the method this route attribute decorates
            method_node = self._find_method_after_line(line_no, nodes, max_gap=5)
            if method_node:
                new_edges.append(
                    Edge(
                        source_id=route_node.id,
                        target_id=method_node.id,
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.95,
                        line_number=line_no,
                        metadata={
                            "framework": "symfony",
                            "symfony_edge_type": "symfony_routes_to",
                            "path": path,
                            "route_name": route_name,
                        },
                    )
                )
            else:
                # Regex fallback
                method_name, method_line = self._find_method_after_line_regex(
                    line_no,
                    source_text,
                    file_path,
                    max_gap=5,
                )
                if method_name and method_line:
                    target_id = generate_node_id(
                        file_path,
                        method_line,
                        NodeKind.METHOD,
                        method_name,
                    )
                    new_edges.append(
                        Edge(
                            source_id=route_node.id,
                            target_id=target_id,
                            kind=EdgeKind.ROUTES_TO,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "symfony",
                                "symfony_edge_type": "symfony_routes_to",
                                "path": path,
                                "route_name": route_name,
                                "resolved_via": "regex_fallback",
                            },
                        )
                    )

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="route",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"route_count": len(new_nodes)},
        )

    # ------------------------------------------------------------------
    # 2c. Doctrine ORM Entity detection
    # ------------------------------------------------------------------

    def _detect_entity(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Doctrine ORM entities via #[ORM\\Entity] attributes."""
        if not _ENTITY_ATTR_RE.search(source_text):
            return None

        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        namespace = self._extract_namespace(source_text)

        # Find the entity class name
        entity_line = 0
        for em in _ENTITY_ATTR_RE.finditer(source_text):
            entity_line = source_text[: em.start()].count("\n") + 1
            break

        # Find the class declaration after the entity attribute
        class_match = _ENTITY_CLASS_RE.search(source_text[source_text.find("#[" if entity_line > 0 else "") :])
        # More robust: search for class after the entity attribute position
        after_attr = source_text[source_text.find("Entity") :]
        class_match = _ENTITY_CLASS_RE.search(after_attr)
        class_name = class_match.group("name") if class_match else "UnknownEntity"
        qualified = self._qualified_name(namespace, class_name)

        # Try to find class node from AST
        cls_node = self._find_enclosing_class(entity_line + 2, nodes)
        start_line = cls_node.start_line if cls_node else entity_line
        end_line = cls_node.end_line if cls_node else entity_line

        # Extract table name
        table_match = _TABLE_ATTR_RE.search(source_text)
        table_name = table_match.group("name") if table_match else ""

        # Extract repository class
        repo_match = _REPOSITORY_CLASS_RE.search(source_text)
        repo_class = repo_match.group("repo") if repo_match else ""

        # Count columns and check for ID
        column_count = len(_COLUMN_ATTR_RE.findall(source_text))
        has_id = bool(_ID_ATTR_RE.search(source_text))

        model_node = Node(
            id=generate_node_id(file_path, start_line, NodeKind.MODEL, class_name),
            kind=NodeKind.MODEL,
            name=class_name,
            qualified_name=qualified,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            language="php",
            metadata={
                "framework": "symfony",
                "symfony_type": "entity",
                "table_name": table_name,
                "repository_class": repo_class,
                "column_count": column_count,
                "has_id": has_id,
                "original_class_id": cls_node.id if cls_node else None,
            },
        )
        new_nodes.append(model_node)

        # Detect relationships
        seen_relations: set[str] = set()
        for pattern in (_RELATION_ATTR_RE, _RELATION_ATTR_V2_RE):
            for rm in pattern.finditer(source_text):
                relation_type = rm.group("type")
                target_entity = rm.group("target")
                rel_key = f"{relation_type}:{target_entity}"
                if rel_key in seen_relations:
                    continue
                seen_relations.add(rel_key)

                rel_line = source_text[: rm.start()].count("\n") + 1
                short_name = target_entity.rsplit("\\", 1)[-1] if "\\" in target_entity else target_entity

                new_edges.append(
                    Edge(
                        source_id=model_node.id,
                        target_id=f"__unresolved__:model:{short_name}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.90,
                        line_number=rel_line,
                        metadata={
                            "framework": "symfony",
                            "symfony_edge_type": "doctrine_relates_to",
                            "relationship_type": relation_type,
                            "target_entity": target_entity,
                        },
                    )
                )

        # Repository class edge
        if repo_class:
            new_edges.append(
                Edge(
                    source_id=f"__unresolved__:class:{repo_class}",
                    target_id=model_node.id,
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.90,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "doctrine_repository_for",
                        "repository_class": repo_class,
                    },
                )
            )

        # doctrine_maps_to: Entity maps to database table
        resolved_table = table_name
        if not resolved_table:
            # Convention: CamelCase class name -> snake_case table name
            # re already imported at module level
            resolved_table = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
        new_edges.append(
            Edge(
                source_id=model_node.id,
                target_id=f"__unresolved__:table:{resolved_table}",
                kind=EdgeKind.DEPENDS_ON,
                confidence=0.95,
                line_number=entity_line,
                metadata={
                    "framework": "symfony",
                    "symfony_edge_type": "doctrine_maps_to",
                    "table_name": resolved_table,
                },
            )
        )

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="entity",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"entity_name": qualified, "table_name": table_name},
        )

    # ------------------------------------------------------------------
    # 2d. Dependency Injection detection
    # ------------------------------------------------------------------

    def _detect_dependency_injection(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect constructor injection and #[Autowire] attributes."""
        new_edges: list[Edge] = []

        # Find __construct in source
        construct_match = re.search(r"__construct\s*\(", source_text)
        if not construct_match:
            return None

        construct_line = source_text[: construct_match.start()].count("\n") + 1

        # Find the enclosing class
        cls_node = self._find_enclosing_class(construct_line, nodes)
        if not cls_node:
            # Fallback: find class name via regex
            cls_match = _ENTITY_CLASS_RE.search(source_text)
            if not cls_match:
                return None
            class_name = cls_match.group("name")
            class_line = source_text[: cls_match.start()].count("\n") + 1
            source_id = generate_node_id(file_path, class_line, NodeKind.CLASS, class_name)
        else:
            source_id = cls_node.id

        # Extract the constructor parameter block
        # Find the matching closing parenthesis
        start_idx = construct_match.end()
        paren_depth = 1
        end_idx = start_idx
        while end_idx < len(source_text) and paren_depth > 0:
            ch = source_text[end_idx]
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
            end_idx += 1

        constructor_body = source_text[start_idx:end_idx]

        # Find all type-hinted parameters
        for pm in _CONSTRUCTOR_INJECT_RE.finditer(constructor_body):
            dep_type = pm.group("type")
            dep_param = pm.group("param")
            param_line = construct_line + constructor_body[: pm.start()].count("\n")

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:class:{dep_type}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.85,
                    line_number=param_line,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "symfony_injects",
                        "service_type": dep_type,
                        "param_name": dep_param,
                        "injection_style": "constructor",
                    },
                )
            )

        # Detect #[Autowire] attributes
        for am in _AUTOWIRE_ATTR_RE.finditer(source_text):
            autowire_line = source_text[: am.start()].count("\n") + 1
            autowire_args = am.group("args")
            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:autowire:{autowire_args.strip()}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.90,
                    line_number=autowire_line,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "symfony_autowires",
                        "autowire_args": autowire_args.strip(),
                    },
                )
            )

        # Detect #[TaggedIterator] attributes
        for tm in _TAGGED_ITERATOR_RE.finditer(source_text):
            tag_line = source_text[: tm.start()].count("\n") + 1
            tag_name = tm.group("tag")
            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:tag:{tag_name}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.85,
                    line_number=tag_line,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "symfony_tagged_iterator",
                        "tag": tag_name,
                    },
                )
            )

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="dependency_injection",
            nodes=[],
            edges=new_edges,
            metadata={"injection_count": len(new_edges)},
        )

    # ------------------------------------------------------------------
    # 2e. Twig template references
    # ------------------------------------------------------------------

    def _detect_template_references(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect $this->render() and #[Template()] references to Twig templates."""
        new_edges: list[Edge] = []

        # $this->render('template/path.html.twig', [...])
        for rm in _RENDER_TEMPLATE_RE.finditer(source_text):
            template = rm.group("template")
            line_no = source_text[: rm.start()].count("\n") + 1

            # Find enclosing method or class
            method_node = self._find_enclosing_method(line_no, nodes)
            if method_node:
                source_id = method_node.id
            else:
                cls_node = self._find_enclosing_class(line_no, nodes)
                source_id = (
                    cls_node.id
                    if cls_node
                    else generate_node_id(
                        file_path,
                        line_no,
                        NodeKind.METHOD,
                        "unknown",
                    )
                )

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:template:{template}",
                    kind=EdgeKind.RENDERS,
                    confidence=0.95,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "renders_twig",
                        "template": template,
                    },
                )
            )

        # #[Template('template/path.html.twig')]
        for tm in _TEMPLATE_ATTR_RE.finditer(source_text):
            template = tm.group("template")
            line_no = source_text[: tm.start()].count("\n") + 1

            # Find the method below the attribute
            method_node = self._find_method_after_line(line_no, nodes, max_gap=5)
            if method_node:
                source_id = method_node.id
            else:
                method_name, method_line = self._find_method_after_line_regex(
                    line_no,
                    source_text,
                    file_path,
                    max_gap=5,
                )
                source_id = generate_node_id(
                    file_path,
                    method_line or line_no,
                    NodeKind.METHOD,
                    method_name or "unknown",
                )

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:template:{template}",
                    kind=EdgeKind.RENDERS,
                    confidence=0.90,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "renders_twig",
                        "template": template,
                        "via_attribute": True,
                    },
                )
            )

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="template_reference",
            nodes=[],
            edges=new_edges,
            metadata={"template_count": len(new_edges)},
        )

    @staticmethod
    def _find_enclosing_method(line_no: int, nodes: list[Node]) -> Node | None:
        """Return the narrowest METHOD node enclosing *line_no*."""
        candidates = [
            n
            for n in nodes
            if n.kind == NodeKind.METHOD
            and n.start_line is not None
            and n.end_line is not None
            and n.start_line <= line_no <= n.end_line
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda n: (n.end_line or 0) - (n.start_line or 0))

    # ------------------------------------------------------------------
    # 2g. Event system detection
    # ------------------------------------------------------------------

    def _detect_events(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect event listeners, subscribers, and event dispatching."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        namespace = self._extract_namespace(source_text)

        # #[AsEventListener(event: 'kernel.request')]
        for lm in _EVENT_LISTENER_ATTR_RE.finditer(source_text):
            event_name = lm.group("event")
            line_no = source_text[: lm.start()].count("\n") + 1

            # Find the class this listener belongs to
            cls_node = self._find_enclosing_class(line_no, nodes)
            if not cls_node:
                cls_match = _ENTITY_CLASS_RE.search(source_text)
                if cls_match:
                    class_name = cls_match.group("name")
                    class_line = source_text[: cls_match.start()].count("\n") + 1
                else:
                    continue
            else:
                class_name = cls_node.name
                class_line = cls_node.start_line

            qualified = self._qualified_name(namespace, class_name)

            listener_node = Node(
                id=generate_node_id(file_path, class_line, NodeKind.LISTENER, class_name),
                kind=NodeKind.LISTENER,
                name=class_name,
                qualified_name=qualified,
                file_path=file_path,
                start_line=class_line,
                end_line=cls_node.end_line if cls_node else class_line,
                language="php",
                metadata={
                    "framework": "symfony",
                    "symfony_type": "event_listener",
                    "event": event_name,
                    "original_class_id": cls_node.id if cls_node else None,
                },
            )
            new_nodes.append(listener_node)

            # Create event node (unresolved)
            event_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.EVENT, event_name),
                kind=NodeKind.EVENT,
                name=event_name,
                qualified_name=event_name,
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="php",
                metadata={
                    "framework": "symfony",
                    "symfony_type": "event",
                },
            )
            new_nodes.append(event_node)

            new_edges.append(
                Edge(
                    source_id=listener_node.id,
                    target_id=event_node.id,
                    kind=EdgeKind.LISTENS_TO,
                    confidence=0.95,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "symfony_listens_to",
                        "event": event_name,
                    },
                )
            )

        # implements EventSubscriberInterface
        if _EVENT_SUBSCRIBER_RE.search(source_text):
            cls_match = _ENTITY_CLASS_RE.search(source_text)
            if cls_match:
                class_name = cls_match.group("name")
                class_line = source_text[: cls_match.start()].count("\n") + 1
                qualified = self._qualified_name(namespace, class_name)

                cls_node = self._find_enclosing_class(class_line, nodes)

                listener_node = Node(
                    id=generate_node_id(file_path, class_line, NodeKind.LISTENER, class_name),
                    kind=NodeKind.LISTENER,
                    name=class_name,
                    qualified_name=qualified,
                    file_path=file_path,
                    start_line=class_line,
                    end_line=cls_node.end_line if cls_node else class_line,
                    language="php",
                    metadata={
                        "framework": "symfony",
                        "symfony_type": "event_subscriber",
                        "original_class_id": cls_node.id if cls_node else None,
                    },
                )
                # Avoid duplicate if already added via attribute
                existing_ids = {n.id for n in new_nodes}
                if listener_node.id not in existing_ids:
                    new_nodes.append(listener_node)

        # $dispatcher->dispatch(new SomeEvent())
        for dm in _DISPATCH_EVENT_RE.finditer(source_text):
            event_class = dm.group("event")
            line_no = source_text[: dm.start()].count("\n") + 1

            cls_node = self._find_enclosing_class(line_no, nodes)
            if cls_node:
                source_id = cls_node.id
            else:
                source_id = generate_node_id(
                    file_path,
                    line_no,
                    NodeKind.CLASS,
                    "unknown",
                )

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:event:{event_class}",
                    kind=EdgeKind.DISPATCHES_EVENT,
                    confidence=0.85,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "symfony_dispatches",
                        "event_class": event_class,
                    },
                )
            )

        if not new_nodes and not new_edges:
            return None

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="event_system",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "listener_count": sum(1 for n in new_nodes if n.kind == NodeKind.LISTENER),
                "event_count": sum(1 for n in new_nodes if n.kind == NodeKind.EVENT),
                "dispatch_count": sum(1 for e in new_edges if e.kind == EdgeKind.DISPATCHES_EVENT),
            },
        )

    # ------------------------------------------------------------------
    # 2h. Form type detection
    # ------------------------------------------------------------------

    def _detect_form_types(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect classes extending AbstractType (Symfony Form)."""
        m = _FORM_TYPE_RE.search(source_text)
        if not m:
            return None

        class_name = m.group("name")
        namespace = self._extract_namespace(source_text)
        qualified = self._qualified_name(namespace, class_name)
        line_no = source_text[: m.start()].count("\n") + 1

        cls_node = self._find_enclosing_class(line_no, nodes)
        start_line = cls_node.start_line if cls_node else line_no
        end_line = cls_node.end_line if cls_node else line_no

        form_node = Node(
            id=generate_node_id(file_path, start_line, NodeKind.COMPONENT, class_name),
            kind=NodeKind.COMPONENT,
            name=class_name,
            qualified_name=qualified,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            language="php",
            metadata={
                "framework": "symfony",
                "symfony_type": "form_type",
                "original_class_id": cls_node.id if cls_node else None,
            },
        )

        new_edges: list[Edge] = []

        # form_maps_entity: FormType maps to entity via data_class
        dc_match = _DATA_CLASS_RE.search(source_text)
        if dc_match:
            entity_name = dc_match.group("entity")
            dc_line = source_text[: dc_match.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=form_node.id,
                    target_id=f"__unresolved__:class:{entity_name}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.95,
                    line_number=dc_line,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "form_maps_entity",
                        "entity_class": entity_name,
                    },
                )
            )

            # form_field_maps: FormType field maps to entity property
            for fm in _BUILDER_ADD_RE.finditer(source_text):
                field_name = fm.group("field")
                fm_line = source_text[: fm.start()].count("\n") + 1
                new_edges.append(
                    Edge(
                        source_id=form_node.id,
                        target_id=f"__unresolved__:property:{entity_name}.{field_name}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.85,
                        line_number=fm_line,
                        metadata={
                            "framework": "symfony",
                            "symfony_edge_type": "form_field_maps",
                            "entity_class": entity_name,
                            "field_name": field_name,
                        },
                    )
                )

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="form_type",
            nodes=[form_node],
            edges=new_edges,
            metadata={"form_type_name": qualified},
        )

    # ------------------------------------------------------------------
    # 2i. Console command detection
    # ------------------------------------------------------------------

    def _detect_commands(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect console commands (extends Command or #[AsCommand])."""
        new_nodes: list[Node] = []
        namespace = self._extract_namespace(source_text)

        # #[AsCommand(name: 'app:xxx')]
        command_name = ""
        as_cmd = _AS_COMMAND_ATTR_RE.search(source_text)
        if as_cmd:
            command_name = as_cmd.group("name")

        # class XxxCommand extends Command
        cmd_match = _COMMAND_RE.search(source_text)
        if not cmd_match and not as_cmd:
            return None

        if cmd_match:
            class_name = cmd_match.group("name")
            line_no = source_text[: cmd_match.start()].count("\n") + 1
        else:
            # Only #[AsCommand] found, find the class
            cls_match = _ENTITY_CLASS_RE.search(source_text)
            if not cls_match:
                return None
            class_name = cls_match.group("name")
            line_no = source_text[: cls_match.start()].count("\n") + 1

        qualified = self._qualified_name(namespace, class_name)
        cls_node = self._find_enclosing_class(line_no, nodes)
        start_line = cls_node.start_line if cls_node else line_no
        end_line = cls_node.end_line if cls_node else line_no

        cmd_node = Node(
            id=generate_node_id(file_path, start_line, NodeKind.FUNCTION, class_name),
            kind=NodeKind.FUNCTION,
            name=class_name,
            qualified_name=qualified,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            language="php",
            metadata={
                "framework": "symfony",
                "symfony_type": "console_command",
                "command_name": command_name,
                "original_class_id": cls_node.id if cls_node else None,
            },
        )
        new_nodes.append(cmd_node)

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="console_command",
            nodes=new_nodes,
            edges=[],
            metadata={"command_name": command_name, "class_name": qualified},
        )

    # ------------------------------------------------------------------
    # 2j. Security detection
    # ------------------------------------------------------------------

    def _detect_security(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect #[IsGranted] attributes and Voter classes."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        namespace = self._extract_namespace(source_text)

        # #[IsGranted('ROLE_ADMIN')]
        for gm in _IS_GRANTED_RE.finditer(source_text):
            role = gm.group("role")
            line_no = source_text[: gm.start()].count("\n") + 1

            # Find the method or class this attribute decorates
            method_node = self._find_method_after_line(line_no, nodes, max_gap=5)
            if method_node:
                source_id = method_node.id
            else:
                cls_node = self._find_enclosing_class(line_no, nodes)
                if cls_node:
                    source_id = cls_node.id
                else:
                    method_name, method_line = self._find_method_after_line_regex(
                        line_no,
                        source_text,
                        file_path,
                        max_gap=5,
                    )
                    source_id = generate_node_id(
                        file_path,
                        method_line or line_no,
                        NodeKind.METHOD,
                        method_name or "unknown",
                    )

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:role:{role}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.95,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "secured_by",
                        "role": role,
                    },
                )
            )

        # class XxxVoter extends Voter
        voter_match = _VOTER_RE.search(source_text)
        if voter_match:
            class_name = voter_match.group("name")
            line_no = source_text[: voter_match.start()].count("\n") + 1
            qualified = self._qualified_name(namespace, class_name)

            cls_node = self._find_enclosing_class(line_no, nodes)
            start_line = cls_node.start_line if cls_node else line_no
            end_line = cls_node.end_line if cls_node else line_no

            voter_node = Node(
                id=generate_node_id(file_path, start_line, NodeKind.COMPONENT, class_name),
                kind=NodeKind.COMPONENT,
                name=class_name,
                qualified_name=qualified,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                language="php",
                metadata={
                    "framework": "symfony",
                    "symfony_type": "voter",
                    "original_class_id": cls_node.id if cls_node else None,
                },
            )
            new_nodes.append(voter_node)

            # voter_protects: Voter protects entity via supports() type check
            for vm in _VOTER_SUPPORTS_INSTANCEOF_RE.finditer(source_text):
                entity_name = vm.group("entity")
                vm_line = source_text[: vm.start()].count("\n") + 1
                new_edges.append(
                    Edge(
                        source_id=voter_node.id,
                        target_id=f"__unresolved__:class:{entity_name}",
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.85,
                        line_number=vm_line,
                        metadata={
                            "framework": "symfony",
                            "symfony_edge_type": "voter_protects",
                            "entity_class": entity_name,
                        },
                    )
                )

        if not new_nodes and not new_edges:
            return None

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="security",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "grant_count": len(new_edges),
                "voter_count": len(new_nodes),
            },
        )

    # ------------------------------------------------------------------
    # 2k. Validation constraint detection
    # ------------------------------------------------------------------

    def _detect_validation(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect #[Assert\\*] validation constraints on entity properties."""
        matches = list(_ASSERT_ATTR_RE.finditer(source_text))
        if not matches:
            return None

        new_edges: list[Edge] = []
        namespace = self._extract_namespace(source_text)  # noqa: F841

        for am in matches:
            constraint = am.group("constraint")
            line_no = source_text[: am.start()].count("\n") + 1

            # Find the enclosing class
            cls_node = self._find_enclosing_class(line_no, nodes)
            if cls_node:
                source_id = cls_node.id
            else:
                source_id = generate_node_id(file_path, line_no, NodeKind.CLASS, "unknown")

            new_edges.append(
                Edge(
                    source_id=source_id,
                    target_id=f"__unresolved__:constraint:Assert\\{constraint}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.95,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "validates_with",
                        "constraint": constraint,
                    },
                )
            )

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="validation",
            nodes=[],
            edges=new_edges,
            metadata={"constraint_count": len(new_edges)},
        )

    # ------------------------------------------------------------------
    # 2l. Bundle detection
    # ------------------------------------------------------------------

    def _detect_bundles(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect classes extending Bundle."""
        m = _BUNDLE_RE.search(source_text)
        if not m:
            return None

        class_name = m.group("name")
        namespace = self._extract_namespace(source_text)
        qualified = self._qualified_name(namespace, class_name)
        line_no = source_text[: m.start()].count("\n") + 1

        cls_node = self._find_enclosing_class(line_no, nodes)
        start_line = cls_node.start_line if cls_node else line_no
        end_line = cls_node.end_line if cls_node else line_no

        bundle_node = Node(
            id=generate_node_id(file_path, start_line, NodeKind.COMPONENT, class_name),
            kind=NodeKind.COMPONENT,
            name=class_name,
            qualified_name=qualified,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            language="php",
            metadata={
                "framework": "symfony",
                "symfony_type": "bundle",
                "original_class_id": cls_node.id if cls_node else None,
            },
        )

        # Edge: bundle provides services/config
        bundle_edge = Edge(
            source_id=bundle_node.id,
            target_id=f"__unresolved__:config:{qualified}",
            kind=EdgeKind.DEPENDS_ON,
            confidence=0.90,
            line_number=line_no,
            metadata={
                "framework": "symfony",
                "symfony_edge_type": "bundle_provides",
                "bundle_name": qualified,
            },
        )

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="bundle",
            nodes=[bundle_node],
            edges=[bundle_edge],
            metadata={"bundle_name": qualified},
        )

    # ------------------------------------------------------------------
    # 2m. Twig template pattern detection
    # ------------------------------------------------------------------

    def _detect_twig_template_patterns(
        self,
        file_path: str,
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect patterns in .twig template files.

        Handles: twig_extends, twig_includes, twig_embeds, twig_imports_macro,
        renders_controller, references_route, stimulus_controls, asset_references.
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        # Create a node for this template file
        tpl_node = Node(
            id=generate_node_id(file_path, 1, NodeKind.COMPONENT, os.path.basename(file_path)),
            kind=NodeKind.COMPONENT,
            name=os.path.basename(file_path),
            qualified_name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=source_text.count("\n") + 1,
            language="twig",
            metadata={
                "framework": "symfony",
                "symfony_type": "twig_template",
            },
        )
        new_nodes.append(tpl_node)

        # --- twig_extends ---
        for m in _TWIG_EXTENDS_RE.finditer(source_text):
            template = m.group("template")
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:template:{template}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.98,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "twig_extends",
                        "target_template": template,
                    },
                )
            )

        # --- twig_includes ---
        for m in _TWIG_INCLUDE_RE.finditer(source_text):
            template = m.group("template")
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:template:{template}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.98,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "twig_includes",
                        "target_template": template,
                    },
                )
            )

        # --- twig_embeds ---
        for m in _TWIG_EMBED_RE.finditer(source_text):
            template = m.group("template")
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:template:{template}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.98,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "twig_embeds",
                        "target_template": template,
                    },
                )
            )

        # --- twig_imports_macro ---
        for m in _TWIG_IMPORT_MACRO_RE.finditer(source_text):
            template = m.group("template")
            macros = m.group("macros").strip()
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:template:{template}",
                    kind=EdgeKind.IMPORTS,
                    confidence=0.95,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "twig_imports_macro",
                        "target_template": template,
                        "macros": macros,
                    },
                )
            )

        # --- renders_controller ---
        for m in _TWIG_RENDER_CONTROLLER_RE.finditer(source_text):
            controller = m.group("controller")
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:controller:{controller}",
                    kind=EdgeKind.RENDERS,
                    confidence=0.90,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "renders_controller",
                        "controller": controller,
                    },
                )
            )

        # --- references_route ---
        for m in _TWIG_PATH_RE.finditer(source_text):
            route = m.group("route")
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:route:{route}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.95,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "references_route",
                        "route_name": route,
                    },
                )
            )

        # --- stimulus_controls ---
        for m in _STIMULUS_DATA_CONTROLLER_RE.finditer(source_text):
            controllers_str = m.group("controllers")
            line_no = source_text[: m.start()].count("\n") + 1
            for ctrl in controllers_str.split():
                ctrl = ctrl.strip()
                if ctrl:
                    new_edges.append(
                        Edge(
                            source_id=tpl_node.id,
                            target_id=f"__unresolved__:stimulus:{ctrl}",
                            kind=EdgeKind.DEPENDS_ON,
                            confidence=0.90,
                            line_number=line_no,
                            metadata={
                                "framework": "symfony",
                                "symfony_edge_type": "stimulus_controls",
                                "controller_name": ctrl,
                            },
                        )
                    )

        for m in _STIMULUS_FUNCTION_RE.finditer(source_text):
            ctrl = m.group("controller")
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:stimulus:{ctrl}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.90,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "stimulus_controls",
                        "controller_name": ctrl,
                    },
                )
            )

        # --- asset_references ---
        for m in _ASSET_ENCORE_RE.finditer(source_text):
            entry = m.group("entry")
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:asset:{entry}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.85,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "asset_references",
                        "asset_entry": entry,
                        "bundler": "encore",
                    },
                )
            )

        for m in _ASSET_VITE_RE.finditer(source_text):
            entry = m.group("entry")
            line_no = source_text[: m.start()].count("\n") + 1
            new_edges.append(
                Edge(
                    source_id=tpl_node.id,
                    target_id=f"__unresolved__:asset:{entry}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.85,
                    line_number=line_no,
                    metadata={
                        "framework": "symfony",
                        "symfony_edge_type": "asset_references",
                        "asset_entry": entry,
                        "bundler": "vite",
                    },
                )
            )

        # Only return pattern if we found edges
        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="symfony",
            pattern_type="twig_template",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "template_file": file_path,
                "edge_count": len(new_edges),
            },
        )
