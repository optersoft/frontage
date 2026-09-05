"""Frontage: a fine-grained reactive UI framework for Python in the browser.

M1 of the rewrite (see DESIGN.md): the reactive core, the store, reactive views with the
insert rules, delegated events, Show and For, and the DOM renderer. Templates follow in M2.
"""

from .errors import FrontageError, NotReady, RenderError
from .flow import For, Show
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
from .view import Element, Mounted, NodeRef, Text, build, component, h, mount, render_to_string, text

__all__ = [
    "Context",
    "Effect",
    "Element",
    "For",
    "FrontageError",
    "HtmlRenderer",
    "Memo",
    "Mounted",
    "NodeRef",
    "NotReady",
    "Owner",
    "RecordingRenderer",
    "RenderEffect",
    "RenderError",
    "Renderer",
    "Show",
    "Signal",
    "Store",
    "Text",
    "__version__",
    "batch",
    "build",
    "component",
    "get_owner",
    "h",
    "in_browser",
    "mount",
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
