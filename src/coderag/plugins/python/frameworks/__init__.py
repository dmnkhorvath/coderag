"""Python framework detectors for CodeRAG."""

from coderag.plugins.python.frameworks.django import DjangoDetector
from coderag.plugins.python.frameworks.fastapi import FastAPIDetector
from coderag.plugins.python.frameworks.flask import FlaskDetector

__all__ = ["DjangoDetector", "FastAPIDetector", "FlaskDetector"]
