"""MCP Server package for CodeRAG.

Exposes the CodeRAG knowledge graph to LLMs via the
Model Context Protocol (MCP).
"""
from .server import create_server, run_stdio_server

__all__ = ["create_server", "run_stdio_server"]
