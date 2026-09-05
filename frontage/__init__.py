"""Frontage: a fine-grained reactive UI framework for Python in the browser.

M1 of the rewrite (see DESIGN.md), in progress: the reactive core and the store are in;
the DOM renderer, reactive views and templates follow.
"""

from .errors import FrontageError, NotReady, RenderError
from .reactive import (
    Context,
    Effect,
    Memo,
    Owner,
    RenderEffect,
    Signal,
    batch,
    get_owner,
    on,
    on_cleanup,
    on_mount,
    provide,
    run_with_owner,
    selector,
    untrack,
    use,
)
from .renderer import HtmlRenderer, RecordingRenderer, Renderer
from .runtime import in_browser, platform
from .store import Store, snapshot
from .version import __version__
from .view import Element, Text, build, h, render_to_string, text

__all__ = [
    "Context",
    "Effect",
    "Element",
    "FrontageError",
    "HtmlRenderer",
    "Memo",
    "NotReady",
    "Owner",
    "RecordingRenderer",
    "RenderEffect",
    "RenderError",
    "Renderer",
    "Signal",
    "Store",
    "Text",
    "__version__",
    "batch",
    "build",
    "get_owner",
    "h",
    "in_browser",
    "on",
    "on_cleanup",
    "on_mount",
    "platform",
    "provide",
    "render_to_string",
    "run_with_owner",
    "selector",
    "snapshot",
    "text",
    "untrack",
    "use",
]
