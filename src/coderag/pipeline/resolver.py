"""Phase 4: Reference Resolver — resolves unresolved references into edges.

After all files are extracted (Phase 3), this module:
1. Builds a lookup table of all known qualified names → node IDs
2. Matches each UnresolvedReference to a known node
3. Creates Edge objects for resolved references (high confidence)
4. Creates placeholder nodes + low-confidence edges for unresolved external refs
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Sequence

from coderag.core.models import (
    Edge,
    EdgeKind,
    ExtractionResult,
    Node,
    NodeKind,
    UnresolvedReference,
)
from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class ReferenceResolver:
    """Resolve unresolved references into graph edges.

    Uses a multi-strategy approach with pre-built indexes for fast lookup:
    1. Exact qualified name match (O(1))
    2. Suffix match via reverse index (O(1) average)
    3. Short name match when unambiguous (O(1))
    4. Placeholder node for external/unresolved references
    """

    # Confidence scores for different resolution strategies
    EXACT_MATCH_CONFIDENCE = 1.0
    SUFFIX_MATCH_CONFIDENCE = 0.85
    SHORT_NAME_MATCH_CONFIDENCE = 0.7
    UNRESOLVED_CONFIDENCE = 0.3

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store
        # qualified_name -> node_id
        self._symbol_table: dict[str, str] = {}
        # short_name (last segment) -> list of (qualified_name, node_id)
        self._short_names: dict[str, list[tuple[str, str]]] = {}
        # suffix segments -> list of (qualified_name, node_id)
        # e.g. "Collection" -> [("Illuminate\Support\Collection", "id1"), ...]
        self._suffix_index: dict[str, list[tuple[str, str]]] = {}

    def build_symbol_table(self) -> int:
        """Build lookup tables from all nodes in the store.

        Returns:
            Number of symbols indexed.
        """
        self._symbol_table.clear()
        self._short_names.clear()
        self._suffix_index.clear()

        short_names: dict[str, list[tuple[str, str]]] = defaultdict(list)
        suffix_index: dict[str, list[tuple[str, str]]] = defaultdict(list)

        conn = self._store._conn
        cursor = conn.execute("SELECT id, qualified_name, name, kind FROM nodes")

        count = 0
        for row in cursor:
            node_id = row[0]
            qname = row[1]
            row[2]

            # Index by qualified name (exact match)
            self._symbol_table[qname] = node_id

            # Also index without leading backslash
            stripped = qname.lstrip("\\")
            if stripped != qname:
                self._symbol_table[stripped] = node_id

            # Index by short name (last segment after \ or ::)
            short = qname.rsplit("\\", 1)[-1].rsplit("::", 1)[-1]
            short_names[short].append((qname, node_id))

            # Build suffix index: index by each suffix segment
            # e.g. "A\B\C" indexes under "C", "B\C", "A\B\C"
            parts = qname.split("\\")
            for i in range(len(parts)):
                suffix = "\\".join(parts[i:])
                if suffix != qname:  # skip full name (already in symbol_table)
                    suffix_index[suffix].append((qname, node_id))

            count += 1

        self._short_names = dict(short_names)
        self._suffix_index = dict(suffix_index)

        logger.info(
            "Symbol table built: %d symbols, %d short names, %d suffix entries",
            count,
            len(self._short_names),
            len(self._suffix_index),
        )
        return count

    def resolve(
        self,
        all_results: Sequence[ExtractionResult],
    ) -> tuple[list[Edge], list[Node], int, int]:
        """Resolve all unresolved references from extraction results.

        Args:
            all_results: Extraction results from Phase 3.

        Returns:
            Tuple of (resolved_edges, placeholder_nodes, resolved_count, unresolved_count).
        """
        if not self._symbol_table:
            self.build_symbol_table()

        resolved_edges: list[Edge] = []
        placeholder_nodes: list[Node] = []
        seen_placeholders: set[str] = set()
        resolved_count = 0
        unresolved_count = 0

        for result in all_results:
            for ref in result.unresolved_references:
                edge, placeholder = self._resolve_one(ref, seen_placeholders)
                if edge is not None:
                    resolved_edges.append(edge)
                    if edge.confidence >= self.SUFFIX_MATCH_CONFIDENCE:
                        resolved_count += 1
                    else:
                        unresolved_count += 1
                    if placeholder is not None:
                        placeholder_nodes.append(placeholder)

        logger.info(
            "Resolution complete: %d resolved, %d unresolved, %d placeholder nodes",
            resolved_count,
            unresolved_count,
            len(placeholder_nodes),
        )
        return resolved_edges, placeholder_nodes, resolved_count, unresolved_count

    def _resolve_one(
        self,
        ref: UnresolvedReference,
        seen_placeholders: set[str],
    ) -> tuple[Edge | None, Node | None]:
        """Try to resolve a single reference using indexed lookups."""
        target_name = ref.reference_name.strip("\\")
        if not target_name:
            return None, None

        # Strategy 1: Exact match (O(1))
        target_id = self._symbol_table.get(target_name)
        if target_id is not None:
            edge = Edge(
                source_id=ref.source_node_id,
                target_id=target_id,
                kind=ref.reference_kind,
                confidence=self.EXACT_MATCH_CONFIDENCE,
                line_number=ref.line_number,
                metadata={"resolution": "exact", "reference_name": ref.reference_name},
            )
            return edge, None

        # Strategy 2: Suffix match via pre-built index (O(1) lookup)
        suffix_matches = self._suffix_index.get(target_name, [])
        if len(suffix_matches) == 1:
            qname, nid = suffix_matches[0]
            edge = Edge(
                source_id=ref.source_node_id,
                target_id=nid,
                kind=ref.reference_kind,
                confidence=self.SUFFIX_MATCH_CONFIDENCE,
                line_number=ref.line_number,
                metadata={"resolution": "suffix", "matched_name": qname, "reference_name": ref.reference_name},
            )
            return edge, None

        # Strategy 3: Short name match (O(1) lookup, only if unambiguous)
        short = target_name.rsplit("\\", 1)[-1].rsplit("::", 1)[-1]
        short_matches = self._short_names.get(short, [])
        if len(short_matches) == 1:
            qname, nid = short_matches[0]
            edge = Edge(
                source_id=ref.source_node_id,
                target_id=nid,
                kind=ref.reference_kind,
                confidence=self.SHORT_NAME_MATCH_CONFIDENCE,
                line_number=ref.line_number,
                metadata={"resolution": "short_name", "matched_name": qname, "reference_name": ref.reference_name},
            )
            return edge, None

        # Strategy 4: Create placeholder for external/unresolved reference
        placeholder_id = "ext:" + hashlib.sha256(target_name.encode()).hexdigest()[:16]
        placeholder = None

        if placeholder_id not in seen_placeholders:
            seen_placeholders.add(placeholder_id)
            node_kind = self._infer_node_kind(ref.reference_kind)
            placeholder = Node(
                id=placeholder_id,
                kind=node_kind,
                name=short,
                qualified_name=target_name,
                file_path="<external>",
                start_line=0,
                end_line=0,
                language="php",
                metadata={"external": True, "placeholder": True},
            )

        edge = Edge(
            source_id=ref.source_node_id,
            target_id=placeholder_id,
            kind=ref.reference_kind,
            confidence=self.UNRESOLVED_CONFIDENCE,
            line_number=ref.line_number,
            metadata={"resolution": "unresolved", "reference_name": ref.reference_name},
        )
        return edge, placeholder

    @staticmethod
    def _infer_node_kind(edge_kind: EdgeKind) -> NodeKind:
        """Infer the most likely target node kind from the edge kind."""
        mapping = {
            EdgeKind.EXTENDS: NodeKind.CLASS,
            EdgeKind.IMPLEMENTS: NodeKind.INTERFACE,
            EdgeKind.USES_TRAIT: NodeKind.TRAIT,
            EdgeKind.CALLS: NodeKind.FUNCTION,
            EdgeKind.IMPORTS: NodeKind.CLASS,
            EdgeKind.INSTANTIATES: NodeKind.CLASS,
        }
        return mapping.get(edge_kind, NodeKind.CLASS)
