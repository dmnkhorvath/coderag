"""Python language plugin for CodeRAG."""

from coderag.plugins.python.extractor import PythonExtractor
from coderag.plugins.python.plugin import PythonPlugin
from coderag.plugins.python.resolver import PythonResolver

Plugin = PythonPlugin  # Convention alias for registry discovery

__all__ = ["PythonExtractor", "PythonPlugin", "PythonResolver", "Plugin"]
