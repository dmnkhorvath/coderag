"""Graph visualization renderer.

Injects exported JSON data into the self-contained HTML template
to produce a single-file interactive visualization.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Location of bundled assets inside the package
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class GraphRenderer:
    """Render an interactive D3.js graph visualization.

    Reads the bundled HTML template, inlines D3.js, and embeds the
    supplied graph JSON to produce a single self-contained HTML file.
    """

    @staticmethod
    def render(
        json_data: dict[str, Any] | str,
        output_path: str | Path,
        *,
        title: str = "CodeRAG Visualization",
    ) -> Path:
        """Produce a self-contained HTML visualization.

        Args:
            json_data: Graph data dict (or a JSON string).
            output_path: Where to write the HTML file.
            title: Page title embedded in the HTML.

        Returns:
            Resolved *output_path*.
        """
        if isinstance(json_data, str):
            json_str = json_data
        else:
            json_str = json.dumps(json_data, default=str)

        # Read template
        template_path = _TEMPLATE_DIR / "graph.html"
        template = template_path.read_text(encoding="utf-8")

        # Read D3.js minified source
        d3_path = _TEMPLATE_DIR / "d3.v7.min.js"
        d3_source = d3_path.read_text(encoding="utf-8")

        # Inject into template
        html = template.replace("/* __D3_SOURCE__ */", d3_source)
        html = html.replace("__GRAPH_DATA__", json_str)
        html = html.replace("__TITLE__", _escape_html(title))

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")

        size_kb = out.stat().st_size / 1024
        logger.info("Rendered visualization (%0.1f KB) → %s", size_kb, out)
        return out.resolve()


def _escape_html(text: str) -> str:
    """Minimal HTML escaping for safe title injection."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
