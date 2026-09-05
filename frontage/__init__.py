"""Frontage: a fine-grained reactive UI framework for Python in the browser.

M0 of the rewrite (see DESIGN.md): the runtime bridge, the renderer seam and a static view
builder. Reactivity, the DOM renderer and templates follow in M1 and M2.
"""

from .errors import FrontageError, NotReady, RenderError
from .renderer import HtmlRenderer, RecordingRenderer, Renderer
from .runtime import in_browser, platform
from .version import __version__
from .view import Element, Text, build, h, render_to_string, text

__all__ = [
    "Element",
    "FrontageError",
    "HtmlRenderer",
    "NotReady",
    "RecordingRenderer",
    "RenderError",
    "Renderer",
    "Text",
    "__version__",
    "build",
    "h",
    "in_browser",
    "platform",
    "render_to_string",
    "text",
]
