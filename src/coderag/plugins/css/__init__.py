"""CSS language plugin for CodeRAG."""
from coderag.plugins.css.extractor import CSSExtractor
from coderag.plugins.css.plugin import CSSPlugin
from coderag.plugins.css.resolver import CSSResolver

Plugin = CSSPlugin  # Convention alias for registry discovery

__all__ = ["CSSExtractor", "CSSPlugin", "CSSResolver", "Plugin"]
