"""CodeRAG language plugins.

Auto-registers built-in plugins when imported.
"""
from coderag.plugins.php.plugin import PHPPlugin

BUILTIN_PLUGINS = [
    PHPPlugin,
]

__all__ = ["BUILTIN_PLUGINS", "PHPPlugin"]
