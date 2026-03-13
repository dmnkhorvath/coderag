"""Framework detectors for PHP projects."""

from coderag.plugins.php.frameworks.laravel import LaravelDetector
from coderag.plugins.php.frameworks.symfony import SymfonyDetector

__all__ = ["LaravelDetector", "SymfonyDetector"]
