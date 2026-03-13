"""PHP plugin package for CodeRAG."""

from coderag.plugins.php.extractor import PHPExtractor
from coderag.plugins.php.plugin import PHPPlugin
from coderag.plugins.php.resolver import PHPResolver

Plugin = PHPPlugin  # Convention alias for registry discovery

__all__ = ["PHPExtractor", "PHPPlugin", "PHPResolver", "Plugin"]
