"""CodeRAG language plugins.

Auto-registers built-in plugins when imported.
"""
from coderag.plugins.php.plugin import PHPPlugin
from coderag.plugins.javascript.plugin import JavaScriptPlugin

BUILTIN_PLUGINS = [
    PHPPlugin,
    JavaScriptPlugin,
]

__all__ = ["BUILTIN_PLUGINS", "PHPPlugin", "JavaScriptPlugin"]
