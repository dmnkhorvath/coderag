"""SCSS language plugin for CodeRAG."""

from coderag.plugins.scss.extractor import SCSSExtractor
from coderag.plugins.scss.plugin import SCSSPlugin
from coderag.plugins.scss.resolver import SCSSResolver

Plugin = SCSSPlugin  # Convention alias for registry discovery

__all__ = ["SCSSExtractor", "SCSSPlugin", "SCSSResolver", "Plugin"]
