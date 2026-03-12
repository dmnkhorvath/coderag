"""CodeRAG language plugins.

Auto-registers built-in plugins when imported.
"""
from coderag.plugins.php.plugin import PHPPlugin
from coderag.plugins.javascript.plugin import JavaScriptPlugin
from coderag.plugins.typescript.plugin import TypeScriptPlugin
from coderag.plugins.python.plugin import PythonPlugin

BUILTIN_PLUGINS = [
    PHPPlugin,
    JavaScriptPlugin,
    TypeScriptPlugin,
    PythonPlugin,
]

__all__ = ["BUILTIN_PLUGINS", "PHPPlugin", "JavaScriptPlugin", "TypeScriptPlugin", "PythonPlugin"]
