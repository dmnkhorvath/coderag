"""PHP plugin package for CodeRAG."""
from coderag.plugins.php.extractor import PHPExtractor
from coderag.plugins.php.plugin import PHPPlugin
from coderag.plugins.php.resolver import PHPResolver

__all__ = ["PHPExtractor", "PHPPlugin", "PHPResolver"]
