"""Tests for coderag.search package.

Covers:
- search/__init__.py (lazy imports, availability detection)
- search/embedder.py (CodeEmbedder)
- search/vector_store.py (VectorStore)
- search/hybrid.py (HybridSearcher, SearchResult)
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from coderag.core.models import Node, NodeKind, Edge, EdgeKind


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_node(id_: str, name: str = "sym", kind: NodeKind = NodeKind.FUNCTION,
               qname: str | None = None, file_path: str = "a.py",
               language: str = "python", start_line: int = 1,
               end_line: int = 10, **kw) -> Node:
    return Node(
        id=id_, kind=kind, name=name,
        qualified_name=qname or name,
        file_path=file_path, start_line=start_line, end_line=end_line,
        language=language, **kw,
    )


# ===================================================================
# search/__init__.py
# ===================================================================

class TestSearchInit:
    """Test the search package __init__ lazy-import machinery."""

    def test_semantic_available_flag_exists(self):
        from coderag.search import SEMANTIC_AVAILABLE
        assert isinstance(SEMANTIC_AVAILABLE, bool)

    def test_is_semantic_available_callable(self):
        from coderag.search import is_semantic_available
        result = is_semantic_available()
        assert isinstance(result, bool)

    def test_require_semantic_when_available(self):
        """If deps are installed, require_semantic should not raise."""
        from coderag.search import is_semantic_available, require_semantic
        if is_semantic_available():
            require_semantic()  # should not raise
        else:
            with pytest.raises(ImportError):
                require_semantic()

    def test_lazy_import_code_embedder(self):
        from coderag.search import CodeEmbedder
        assert CodeEmbedder is not None

    def test_lazy_import_vector_store(self):
        from coderag.search import VectorStore
        assert VectorStore is not None

    def test_lazy_import_hybrid_searcher(self):
        from coderag.search import HybridSearcher
        assert HybridSearcher is not None

    def test_lazy_import_search_result(self):
        from coderag.search import SearchResult
        assert SearchResult is not None

    def test_lazy_import_invalid_attr(self):
        import coderag.search as search_mod
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = search_mod.NonExistentThing

    def test_all_exports(self):
        from coderag.search import __all__
        expected = {
            "SEMANTIC_AVAILABLE", "is_semantic_available", "require_semantic",
            "CodeEmbedder", "VectorStore", "HybridSearcher", "SearchResult",
        }
        assert set(__all__) == expected


# ===================================================================
# search/embedder.py
# ===================================================================

class TestCodeEmbedder:
    """Test CodeEmbedder with mocked sentence-transformers."""

    @pytest.fixture()
    def mock_st(self):
        """Patch sentence_transformers and require_semantic."""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = np.random.randn(384).astype(np.float32)

        mock_st_module = MagicMock()
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict(sys.modules, {"sentence_transformers": mock_st_module}), \
             patch("coderag.search.embedder.require_semantic"):
            from coderag.search.embedder import CodeEmbedder
            yield CodeEmbedder, mock_model

    def test_init_stores_model_name(self, mock_st):
        CodeEmbedder, _ = mock_st
        emb = CodeEmbedder("test-model")
        assert emb.model_name == "test-model"

    def test_default_model_name(self, mock_st):
        CodeEmbedder, _ = mock_st
        emb = CodeEmbedder()
        assert emb.model_name == "all-MiniLM-L6-v2"

    def test_lazy_loading_no_model_on_init(self, mock_st):
        CodeEmbedder, _ = mock_st
        emb = CodeEmbedder()
        assert emb._model is None

    def test_dimension_triggers_model_load(self, mock_st):
        CodeEmbedder, mock_model = mock_st
        emb = CodeEmbedder()
        dim = emb.dimension
        assert dim == 384
        mock_model.get_sentence_embedding_dimension.assert_called()

    def test_embed_text_returns_ndarray(self, mock_st):
        CodeEmbedder, mock_model = mock_st
        emb = CodeEmbedder()
        result = emb.embed_text("hello world")
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        mock_model.encode.assert_called_once()

    def test_embed_batch_returns_2d(self, mock_st):
        CodeEmbedder, mock_model = mock_st
        mock_model.encode.return_value = np.random.randn(3, 384).astype(np.float32)
        emb = CodeEmbedder()
        result = emb.embed_batch(["a", "b", "c"])
        assert result.shape == (3, 384)
        assert result.dtype == np.float32

    def test_embed_batch_empty(self, mock_st):
        CodeEmbedder, mock_model = mock_st
        emb = CodeEmbedder()
        result = emb.embed_batch([])
        assert result.shape[0] == 0

    def test_embed_batch_custom_batch_size(self, mock_st):
        CodeEmbedder, mock_model = mock_st
        mock_model.encode.return_value = np.random.randn(2, 384).astype(np.float32)
        emb = CodeEmbedder()
        emb.embed_batch(["a", "b"], batch_size=64)
        call_kwargs = mock_model.encode.call_args
        assert call_kwargs[1]["batch_size"] == 64

    def test_build_node_text_function(self, mock_st):
        CodeEmbedder, _ = mock_st
        node = _make_node("n1", name="do_stuff", kind=NodeKind.FUNCTION,
                          qname="mod.do_stuff", language="python",
                          metadata={"signature": "def do_stuff(x: int) -> str"})
        text = CodeEmbedder.build_node_text(node)
        assert "function" in text.lower()
        assert "do_stuff" in text
        assert "a.py" in text

    def test_build_node_text_with_parent(self, mock_st):
        CodeEmbedder, _ = mock_st
        node = _make_node("n1", name="method", kind=NodeKind.METHOD)
        text = CodeEmbedder.build_node_text(node, parent_name="MyClass")
        assert "MyClass" in text

    def test_build_node_text_with_docblock(self, mock_st):
        CodeEmbedder, _ = mock_st
        node = _make_node("n1", name="func", kind=NodeKind.FUNCTION,
                          docblock="Does something useful")
        text = CodeEmbedder.build_node_text(node)
        assert "Does something useful" in text

    def test_build_node_text_with_extends(self, mock_st):
        CodeEmbedder, _ = mock_st
        node = _make_node("n1", name="Child", kind=NodeKind.CLASS,
                          metadata={"extends": "Parent"})
        text = CodeEmbedder.build_node_text(node)
        assert "Parent" in text

    def test_build_node_text_with_implements(self, mock_st):
        CodeEmbedder, _ = mock_st
        node = _make_node("n1", name="Svc", kind=NodeKind.CLASS,
                          metadata={"implements": ["Iface1", "Iface2"]})
        text = CodeEmbedder.build_node_text(node)
        assert "Iface1" in text
        assert "Iface2" in text

    def test_build_node_text_implements_string(self, mock_st):
        CodeEmbedder, _ = mock_st
        node = _make_node("n1", name="Svc", kind=NodeKind.CLASS,
                          metadata={"implements": "SingleIface"})
        text = CodeEmbedder.build_node_text(node)
        assert "SingleIface" in text


# ===================================================================
# search/vector_store.py
# ===================================================================

class TestVectorStore:
    """Test VectorStore with mocked FAISS."""

    @pytest.fixture()
    def vs(self):
        """Create a VectorStore with mocked faiss."""
        mock_index = MagicMock()
        mock_index.ntotal = 0

        mock_faiss = MagicMock()
        mock_faiss.IndexFlatIP.return_value = mock_index

        with patch.dict(sys.modules, {"faiss": mock_faiss}), \
             patch("coderag.search.vector_store.require_semantic"):
            from coderag.search.vector_store import VectorStore
            store = VectorStore(384)
            yield store, mock_faiss, mock_index

    def test_init_dimension(self, vs):
        store, _, _ = vs
        assert store.dimension == 384

    def test_size_empty(self, vs):
        store, _, mock_index = vs
        mock_index.ntotal = 0
        assert store.size == 0

    def test_node_ids_empty(self, vs):
        store, _, _ = vs
        assert store.node_ids == []

    def test_build_index(self, vs):
        store, mock_faiss, _ = vs
        new_index = MagicMock()
        mock_faiss.IndexFlatIP.return_value = new_index

        embeddings = np.random.randn(3, 384).astype(np.float32)
        node_ids = ["n1", "n2", "n3"]
        store.build_index(embeddings, node_ids)

        new_index.add.assert_called_once()
        assert store._node_ids == ["n1", "n2", "n3"]
        assert store._id_to_pos == {"n1": 0, "n2": 1, "n3": 2}

    def test_build_index_with_hashes(self, vs):
        store, mock_faiss, _ = vs
        new_index = MagicMock()
        mock_faiss.IndexFlatIP.return_value = new_index

        embeddings = np.random.randn(2, 384).astype(np.float32)
        hashes = {"n1": "abc", "n2": "def"}
        store.build_index(embeddings, ["n1", "n2"], content_hashes=hashes)
        assert store._content_hashes == {"n1": "abc", "n2": "def"}

    def test_build_index_shape_mismatch(self, vs):
        store, _, _ = vs
        embeddings = np.random.randn(3, 384).astype(np.float32)
        with pytest.raises(ValueError, match="same length"):
            store.build_index(embeddings, ["n1", "n2"])

    def test_build_index_wrong_dimension(self, vs):
        store, _, _ = vs
        embeddings = np.random.randn(2, 128).astype(np.float32)
        with pytest.raises(ValueError, match="Expected embeddings"):
            store.build_index(embeddings, ["n1", "n2"])

    def test_search_empty_index(self, vs):
        store, _, mock_index = vs
        mock_index.ntotal = 0
        query = np.random.randn(384).astype(np.float32)
        results = store.search(query, k=5)
        assert results == []

    def test_search_returns_results(self, vs):
        store, _, mock_index = vs
        store._node_ids = ["n1", "n2", "n3"]
        mock_index.ntotal = 3
        mock_index.search.return_value = (
            np.array([[0.95, 0.80, 0.60]]),
            np.array([[0, 2, 1]]),
        )
        query = np.random.randn(384).astype(np.float32)
        results = store.search(query, k=3)
        assert len(results) == 3
        assert results[0] == ("n1", 0.95)
        assert results[1] == ("n3", 0.80)
        assert results[2] == ("n2", 0.60)

    def test_search_skips_negative_indices(self, vs):
        store, _, mock_index = vs
        store._node_ids = ["n1", "n2"]
        mock_index.ntotal = 2
        mock_index.search.return_value = (
            np.array([[0.9, 0.0]]),
            np.array([[0, -1]]),
        )
        query = np.random.randn(384).astype(np.float32)
        results = store.search(query, k=2)
        assert len(results) == 1
        assert results[0][0] == "n1"

    def test_search_k_clamped_to_size(self, vs):
        store, _, mock_index = vs
        store._node_ids = ["n1"]
        mock_index.ntotal = 1
        mock_index.search.return_value = (
            np.array([[0.9]]),
            np.array([[0]]),
        )
        query = np.random.randn(384).astype(np.float32)
        results = store.search(query, k=100)
        # k should be clamped to 1
        call_args = mock_index.search.call_args
        assert call_args[0][1] == 1

    def test_get_content_hash(self, vs):
        store, _, _ = vs
        store._content_hashes = {"n1": "hash1"}
        assert store.get_content_hash("n1") == "hash1"
        assert store.get_content_hash("n2") is None

    def test_add_vectors_new(self, vs):
        store, mock_faiss, mock_index = vs
        # Setup existing state
        store._node_ids = ["n1"]
        store._id_to_pos = {"n1": 0}
        mock_index.ntotal = 1

        embeddings = np.random.randn(1, 384).astype(np.float32)
        store.add_vectors(embeddings, ["n2"])
        mock_index.add.assert_called()

    def test_add_vectors_replace_existing(self, vs):
        store, mock_faiss, mock_index = vs
        # Setup: n1 already exists
        store._node_ids = ["n1", "n2"]
        store._id_to_pos = {"n1": 0, "n2": 1}
        mock_index.ntotal = 2
        mock_index.reconstruct.side_effect = lambda i: np.random.randn(384).astype(np.float32)

        new_index = MagicMock()
        mock_faiss.IndexFlatIP.return_value = new_index

        embeddings = np.random.randn(1, 384).astype(np.float32)
        store.add_vectors(embeddings, ["n1"], content_hashes={"n1": "newhash"})
        # Should have rebuilt index
        new_index.add.assert_called()

    def test_save_and_load(self, vs, tmp_path):
        store, mock_faiss, mock_index = vs
        store._node_ids = ["n1", "n2"]
        store._content_hashes = {"n1": "h1"}
        mock_index.ntotal = 2

        # Make write_index create the file so os.path.getsize works
        def _fake_write(idx, path):
            with open(path, "wb") as fh:
                fh.write(b"FAKE")
        mock_faiss.write_index.side_effect = _fake_write
        
        store.save(str(tmp_path))
        mock_faiss.write_index.assert_called_once()

        # Check meta file was written
        meta_path = tmp_path / "vectors_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["dimension"] == 384
        assert meta["node_ids"] == ["n1", "n2"]
        assert meta["content_hashes"] == {"n1": "h1"}

    def test_exists_true(self, vs, tmp_path):
        (tmp_path / "vectors.faiss").touch()
        (tmp_path / "vectors_meta.json").touch()
        with patch("coderag.search.vector_store.require_semantic"):
            from coderag.search.vector_store import VectorStore
            assert VectorStore.exists(str(tmp_path)) is True

    def test_exists_false(self, vs, tmp_path):
        with patch("coderag.search.vector_store.require_semantic"):
            from coderag.search.vector_store import VectorStore
            assert VectorStore.exists(str(tmp_path)) is False

    def test_load(self, vs, tmp_path):
        _, mock_faiss, _ = vs
        # Write meta file
        meta = {"dimension": 384, "node_ids": ["n1"], "content_hashes": {"n1": "h"}}
        (tmp_path / "vectors_meta.json").write_text(json.dumps(meta))
        (tmp_path / "vectors.faiss").touch()

        loaded_index = MagicMock()
        loaded_index.ntotal = 1
        mock_faiss.read_index.return_value = loaded_index

        with patch("coderag.search.vector_store.require_semantic"):
            from coderag.search.vector_store import VectorStore
            loaded = VectorStore.load(str(tmp_path))
            assert loaded._dimension == 384
            assert loaded._node_ids == ["n1"]
            assert loaded._content_hashes == {"n1": "h"}

    def test_load_missing_files(self, vs, tmp_path):
        with patch("coderag.search.vector_store.require_semantic"):
            from coderag.search.vector_store import VectorStore
            with pytest.raises(FileNotFoundError):
                VectorStore.load(str(tmp_path))


# ===================================================================
# search/hybrid.py
# ===================================================================

class TestSearchResult:
    """Test SearchResult dataclass."""

    def test_create_search_result(self):
        from coderag.search.hybrid import SearchResult
        sr = SearchResult(
            node_id="n1", name="func", kind="function",
            qualified_name="mod.func", file_path="a.py",
            language="python", score=0.85, match_type="both",
            fts_rank=1, vector_rank=2, vector_similarity=0.9,
        )
        assert sr.node_id == "n1"
        assert sr.score == 0.85
        assert sr.match_type == "both"


class TestHybridSearcher:
    """Test HybridSearcher with mocked dependencies."""

    @pytest.fixture()
    def searcher(self):
        mock_store = MagicMock()
        mock_vector_store = MagicMock()
        mock_embedder = MagicMock()

        from coderag.search.hybrid import HybridSearcher
        hs = HybridSearcher(mock_store, mock_vector_store, mock_embedder)
        return hs, mock_store, mock_vector_store, mock_embedder

    def test_search_empty_results(self, searcher):
        hs, mock_store, mock_vs, mock_emb = searcher
        mock_store.search_nodes.return_value = []
        mock_vs.size = 0
        results = hs.search("query", k=5)
        assert results == []

    def test_search_fts_only_alpha_zero(self, searcher):
        hs, mock_store, mock_vs, mock_emb = searcher
        node1 = _make_node("n1", name="func1", qname="mod.func1")
        node2 = _make_node("n2", name="func2", qname="mod.func2")
        mock_store.search_nodes.return_value = [node1, node2]
        mock_store.get_node.side_effect = lambda nid: {"n1": node1, "n2": node2}.get(nid)
        mock_vs.size = 0

        results = hs.search("func", k=5, alpha=0.0)
        assert len(results) >= 1
        assert results[0].node_id == "n1"
        assert results[0].match_type == "fts"

    def test_search_vector_only_alpha_one(self, searcher):
        hs, mock_store, mock_vs, mock_emb = searcher
        mock_vs.size = 10
        mock_emb.embed_text.return_value = np.random.randn(384).astype(np.float32)
        mock_vs.search.return_value = [("n1", 0.95), ("n2", 0.80)]

        node1 = _make_node("n1", name="func1", qname="mod.func1")
        node2 = _make_node("n2", name="func2", qname="mod.func2")
        mock_store.get_node.side_effect = lambda nid: {"n1": node1, "n2": node2}.get(nid)

        results = hs.search("func", k=5, alpha=1.0)
        assert len(results) >= 1
        assert results[0].match_type == "vector"

    def test_search_hybrid_both(self, searcher):
        hs, mock_store, mock_vs, mock_emb = searcher
        node1 = _make_node("n1", name="func1", qname="mod.func1")
        mock_store.search_nodes.return_value = [node1]
        mock_vs.size = 10
        mock_emb.embed_text.return_value = np.random.randn(384).astype(np.float32)
        mock_vs.search.return_value = [("n1", 0.95)]
        mock_store.get_node.side_effect = lambda nid: {"n1": node1}.get(nid)

        results = hs.search("func", k=5, alpha=0.5)
        assert len(results) == 1
        assert results[0].match_type == "both"

    def test_search_with_kind_filter(self, searcher):
        hs, mock_store, mock_vs, mock_emb = searcher
        node_class = _make_node("n1", name="MyClass", kind=NodeKind.CLASS, qname="MyClass")
        node_func = _make_node("n2", name="func", kind=NodeKind.FUNCTION, qname="func")
        mock_store.search_nodes.return_value = [node_class, node_func]
        mock_vs.size = 0
        mock_store.get_node.side_effect = lambda nid: {"n1": node_class, "n2": node_func}.get(nid)

        results = hs.search("test", k=5, alpha=0.0, kind="class")
        assert all(r.kind == "class" for r in results)

    def test_search_alpha_clamped(self, searcher):
        hs, mock_store, mock_vs, mock_emb = searcher
        mock_store.search_nodes.return_value = []
        mock_vs.size = 0
        # alpha > 1.0 should be clamped
        results = hs.search("q", alpha=5.0)
        assert results == []
        # alpha < 0.0 should be clamped
        results = hs.search("q", alpha=-1.0)
        assert results == []

    def test_search_node_not_found_skipped(self, searcher):
        hs, mock_store, mock_vs, mock_emb = searcher
        node1 = _make_node("n1", name="func1", qname="mod.func1")
        mock_store.search_nodes.return_value = [node1]
        mock_vs.size = 0
        # get_node returns None for n1 (deleted between search and lookup)
        mock_store.get_node.return_value = None

        results = hs.search("func", k=5, alpha=0.0)
        assert results == []

    def test_search_result_fields(self, searcher):
        hs, mock_store, mock_vs, mock_emb = searcher
        node1 = _make_node("n1", name="func1", kind=NodeKind.FUNCTION,
                           qname="mod.func1", file_path="src/a.py",
                           language="python")
        mock_store.search_nodes.return_value = [node1]
        mock_vs.size = 10
        mock_emb.embed_text.return_value = np.random.randn(384).astype(np.float32)
        mock_vs.search.return_value = [("n1", 0.92)]
        mock_store.get_node.return_value = node1

        results = hs.search("func", k=5, alpha=0.5)
        assert len(results) == 1
        r = results[0]
        assert r.name == "func1"
        assert r.kind == "function"
        assert r.qualified_name == "mod.func1"
        assert r.file_path == "src/a.py"
        assert r.language == "python"
        assert r.score > 0
        assert r.fts_rank > 0
        assert r.vector_rank > 0
        assert r.vector_similarity > 0


# ── Additional Embedder Tests ─────────────────────────────────────────

class TestCodeEmbedderBuildTextEdgeCases:
    """Test _build_text with various metadata combinations."""

    def test_build_text_with_extends(self):
        from unittest.mock import MagicMock, patch
        with patch("coderag.search.embedder.require_semantic"):
            from coderag.search.embedder import CodeEmbedder
            from coderag.core.models import Node, NodeKind

            embedder = CodeEmbedder.__new__(CodeEmbedder)
            node = Node(
                id="n1",
                kind=NodeKind.CLASS,
                name="Dog",
                qualified_name="animals.Dog",
                file_path="animals.py",
                start_line=1,
                end_line=10,
                language="python",
                source_text="class Dog(Animal): pass",
                metadata={"extends": "Animal"},
            )
            text = CodeEmbedder.build_node_text(node)
            assert "Dog" in text
            assert "Extends: Animal" in text

    def test_build_text_with_implements_list(self):
        from unittest.mock import MagicMock, patch
        with patch("coderag.search.embedder.require_semantic"):
            from coderag.search.embedder import CodeEmbedder
            from coderag.core.models import Node, NodeKind

            embedder = CodeEmbedder.__new__(CodeEmbedder)
            node = Node(
                id="n1",
                kind=NodeKind.CLASS,
                name="MyService",
                qualified_name="services.MyService",
                file_path="services.py",
                start_line=1,
                end_line=10,
                language="python",
                source_text="class MyService: pass",
                metadata={"implements": ["Serializable", "Comparable"]},
            )
            text = CodeEmbedder.build_node_text(node)
            assert "Implements: Serializable, Comparable" in text

    def test_build_text_with_implements_string(self):
        from unittest.mock import MagicMock, patch
        with patch("coderag.search.embedder.require_semantic"):
            from coderag.search.embedder import CodeEmbedder
            from coderag.core.models import Node, NodeKind

            embedder = CodeEmbedder.__new__(CodeEmbedder)
            node = Node(
                id="n1",
                kind=NodeKind.CLASS,
                name="MyService",
                qualified_name="services.MyService",
                file_path="services.py",
                start_line=1,
                end_line=10,
                language="python",
                source_text="class MyService: pass",
                metadata={"implements": "Runnable"},
            )
            text = CodeEmbedder.build_node_text(node)
            assert "Implements: Runnable" in text

    def test_build_text_with_superclass(self):
        from unittest.mock import MagicMock, patch
        with patch("coderag.search.embedder.require_semantic"):
            from coderag.search.embedder import CodeEmbedder
            from coderag.core.models import Node, NodeKind

            embedder = CodeEmbedder.__new__(CodeEmbedder)
            node = Node(
                id="n1",
                kind=NodeKind.CLASS,
                name="Cat",
                qualified_name="animals.Cat",
                file_path="animals.py",
                start_line=1,
                end_line=10,
                language="python",
                source_text="class Cat(Animal): pass",
                metadata={"superclass": "Animal"},
            )
            text = CodeEmbedder.build_node_text(node)
            assert "Extends: Animal" in text


class TestCodeEmbedderEmbedMethods:
    """Test embed_text and embed_batch methods."""

    def test_embed_text(self):
        import numpy as np
        from unittest.mock import MagicMock, patch, PropertyMock
        with patch("coderag.search.embedder.require_semantic"):
            from coderag.search.embedder import CodeEmbedder

            embedder = CodeEmbedder.__new__(CodeEmbedder)
            embedder._model_name = "test-model"
            embedder._dimension = 384
            embedder._model = MagicMock()
            embedder._model.encode.return_value = np.random.randn(384).astype(np.float32)

            result = embedder.embed_text("hello world")
            assert result.shape == (384,)
            assert result.dtype == np.float32
            embedder._model.encode.assert_called_once()

    def test_embed_batch_empty(self):
        import numpy as np
        from unittest.mock import MagicMock, patch
        with patch("coderag.search.embedder.require_semantic"):
            from coderag.search.embedder import CodeEmbedder

            embedder = CodeEmbedder.__new__(CodeEmbedder)
            embedder._model_name = "test-model"
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            embedder._model = mock_model

            result = embedder.embed_batch([])
            assert result.shape == (0, 384)
            mock_model.encode.assert_not_called()

    def test_embed_batch_with_texts(self):
        import numpy as np
        from unittest.mock import MagicMock, patch
        with patch("coderag.search.embedder.require_semantic"):
            from coderag.search.embedder import CodeEmbedder

            embedder = CodeEmbedder.__new__(CodeEmbedder)
            embedder._model_name = "test-model"
            embedder._dimension = 384
            embedder._model = MagicMock()
            embedder._model.encode.return_value = np.random.randn(3, 384).astype(np.float32)

            result = embedder.embed_batch(["a", "b", "c"])
            assert result.shape == (3, 384)
            assert result.dtype == np.float32


class TestVectorStoreRemoveAndSearch:
    """Test VectorStore remove_vectors and search edge cases."""

    def test_remove_vectors_rebuild(self):
        import numpy as np
        from unittest.mock import MagicMock, patch

        mock_faiss = MagicMock()
        mock_index = MagicMock()
        mock_faiss.IndexFlatIP.return_value = mock_index
        mock_index.ntotal = 3

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            with patch("coderag.search.vector_store.require_semantic"):
                from coderag.search.vector_store import VectorStore

                store = VectorStore.__new__(VectorStore)
                store._dimension = 384
                store._index = mock_index
                store._node_ids = ["a", "b", "c"]
                store._id_to_pos = {"a": 0, "b": 1, "c": 2}
                store._content_hashes = {"a": "h1", "b": "h2", "c": "h3"}

                # Mock reconstruct to return vectors
                mock_index.reconstruct.side_effect = lambda i: np.random.randn(384).astype(np.float32)

                store.remove_vectors(["b"])

                # Should have rebuilt index without "b"
                assert "b" not in store._id_to_pos
                assert len(store._node_ids) == 2
                assert "b" not in store._content_hashes

    def test_remove_vectors_all(self):
        import numpy as np
        from unittest.mock import MagicMock, patch

        mock_faiss = MagicMock()
        mock_index = MagicMock()
        mock_faiss.IndexFlatIP.return_value = mock_index

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            with patch("coderag.search.vector_store.require_semantic"):
                from coderag.search.vector_store import VectorStore

                store = VectorStore.__new__(VectorStore)
                store._dimension = 384
                store._index = mock_index
                store._node_ids = ["a", "b"]
                store._id_to_pos = {"a": 0, "b": 1}
                store._content_hashes = {"a": "h1", "b": "h2"}

                store.remove_vectors(["a", "b"])

                assert store._node_ids == []
                assert store._id_to_pos == {}

    def test_search_with_results(self):
        import numpy as np
        from unittest.mock import MagicMock, patch

        mock_faiss = MagicMock()

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            with patch("coderag.search.vector_store.require_semantic"):
                from coderag.search.vector_store import VectorStore

                store = VectorStore.__new__(VectorStore)
                store._dimension = 384
                store._index = MagicMock()
                store._node_ids = ["a", "b", "c"]
                store._id_to_pos = {"a": 0, "b": 1, "c": 2}
                store._content_hashes = {}

                # Mock search to return distances and indices
                store._index.search.return_value = (
                    np.array([[0.9, 0.7]], dtype=np.float32),
                    np.array([[0, 2]], dtype=np.int64),
                )
                store._index.ntotal = 3

                results = store.search(np.random.randn(384).astype(np.float32), k=2)
                assert len(results) == 2
                import pytest as _pt; assert results[0][0] == "a"; assert results[0][1] == _pt.approx(0.9, abs=1e-6)
                import pytest as _pt2; assert results[1][0] == "c"; assert results[1][1] == _pt2.approx(0.7, abs=1e-6)

    def test_search_filters_negative_indices(self):
        import numpy as np
        from unittest.mock import MagicMock, patch

        mock_faiss = MagicMock()

        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            with patch("coderag.search.vector_store.require_semantic"):
                from coderag.search.vector_store import VectorStore

                store = VectorStore.__new__(VectorStore)
                store._dimension = 384
                store._index = MagicMock()
                store._node_ids = ["a", "b"]
                store._id_to_pos = {"a": 0, "b": 1}
                store._content_hashes = {}

                # FAISS returns -1 for missing results
                store._index.search.return_value = (
                    np.array([[0.9, -1.0]], dtype=np.float32),
                    np.array([[0, -1]], dtype=np.int64),
                )
                store._index.ntotal = 2

                results = store.search(np.random.randn(384).astype(np.float32), k=2)
                assert len(results) == 1
                import pytest as _pt; assert results[0][0] == "a"; assert results[0][1] == _pt.approx(0.9, abs=1e-6)
