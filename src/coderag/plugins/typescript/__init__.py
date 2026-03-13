"""TypeScript language plugin for CodeRAG."""

from coderag.plugins.typescript.extractor import TypeScriptExtractor
from coderag.plugins.typescript.plugin import TypeScriptPlugin

Plugin = TypeScriptPlugin  # Convention alias for registry discovery

__all__ = ["TypeScriptExtractor", "TypeScriptPlugin", "Plugin"]
