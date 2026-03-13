"""JavaScript language plugin for CodeRAG."""

from coderag.plugins.javascript.extractor import JavaScriptExtractor
from coderag.plugins.javascript.plugin import JavaScriptPlugin
from coderag.plugins.javascript.resolver import JSResolver

Plugin = JavaScriptPlugin  # Convention alias for registry discovery

__all__ = ["JavaScriptExtractor", "JavaScriptPlugin", "JSResolver", "Plugin"]
