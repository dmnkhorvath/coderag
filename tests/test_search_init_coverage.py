"""Coverage tests for search __init__ - Pass 2.

Targets missing lines: 30-31, 48
"""
import importlib
import sys
from unittest.mock import patch

import pytest


class TestSemanticAvailability:
    """Test semantic search availability detection."""

    def test_is_semantic_available(self):
        """is_semantic_available returns a bool."""
        from coderag.search import is_semantic_available
        result = is_semantic_available()
        assert isinstance(result, bool)

    def test_semantic_available_constant(self):
        """SEMANTIC_AVAILABLE is a bool."""
        from coderag.search import SEMANTIC_AVAILABLE
        assert isinstance(SEMANTIC_AVAILABLE, bool)


class TestRequireSemantic:
    """Test require_semantic function (line 48)."""

    def test_require_semantic_when_available(self):
        """require_semantic does not raise when deps available."""
        from coderag.search import require_semantic, _SEMANTIC_AVAILABLE
        if _SEMANTIC_AVAILABLE:
            require_semantic()  # Should not raise
        else:
            with pytest.raises(ImportError):
                require_semantic()

    def test_require_semantic_when_unavailable(self):
        """require_semantic raises ImportError when deps missing (line 48)."""
        import coderag.search as search_mod
        original_available = search_mod._SEMANTIC_AVAILABLE
        original_error = search_mod._IMPORT_ERROR
        try:
            search_mod._SEMANTIC_AVAILABLE = False
            search_mod._IMPORT_ERROR = "Test: deps not installed"
            with pytest.raises(ImportError, match="Test: deps not installed"):
                search_mod.require_semantic()
        finally:
            search_mod._SEMANTIC_AVAILABLE = original_available
            search_mod._IMPORT_ERROR = original_error


class TestImportErrorHandling:
    """Test ImportError handling during module load (lines 30-31)."""

    def test_import_error_sets_flag(self):
        """When faiss/fastembed not importable, _SEMANTIC_AVAILABLE is False."""
        # Save original module state
        import coderag.search as search_mod

        # We can test the behavior by temporarily modifying the module
        # and checking the error message format
        if not search_mod._SEMANTIC_AVAILABLE:
            # Already unavailable - lines 30-31 were already hit
            assert search_mod._IMPORT_ERROR is not None
            assert "not installed" in search_mod._IMPORT_ERROR
        else:
            # Deps are available, so we need to simulate unavailability
            # by reloading with mocked imports
            saved_faiss = sys.modules.get('faiss')
            saved_fastembed = sys.modules.get('fastembed')
            try:
                sys.modules['faiss'] = None  # Force ImportError
                # Need to reload the module to re-execute the try/except
                importlib.reload(search_mod)
                assert search_mod._SEMANTIC_AVAILABLE is False
                assert search_mod._IMPORT_ERROR is not None
            finally:
                # Restore
                if saved_faiss is not None:
                    sys.modules['faiss'] = saved_faiss
                elif 'faiss' in sys.modules:
                    del sys.modules['faiss']
                if saved_fastembed is not None:
                    sys.modules['fastembed'] = saved_fastembed
                elif 'fastembed' in sys.modules:
                    del sys.modules['fastembed']
                importlib.reload(search_mod)


class TestLazyImports:
    """Test __getattr__ lazy imports."""

    def test_getattr_code_embedder(self):
        """Lazy import of CodeEmbedder."""
        from coderag.search import CodeEmbedder
        assert CodeEmbedder is not None

    def test_getattr_unknown_raises(self):
        """Unknown attribute raises AttributeError."""
        import coderag.search as search_mod
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = search_mod.NonExistentClass

    def test_getattr_vector_store(self):
        """Lazy import of VectorStore."""
        from coderag.search import VectorStore
        assert VectorStore is not None

    def test_getattr_hybrid_searcher(self):
        """Lazy import of HybridSearcher."""
        from coderag.search import HybridSearcher
        assert HybridSearcher is not None

    def test_getattr_search_result(self):
        """Lazy import of SearchResult."""
        from coderag.search import SearchResult
        assert SearchResult is not None
