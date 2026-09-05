"""Frontage: a fine-grained reactive UI framework for Python in the browser.

M2 of the rewrite (see DESIGN.md): the reactive core, the store, reactive views with the
insert rules, templates (`h` and `html(t"…")`), control flow and boundaries, Resource and
Action, delegated events, and the DOM renderer.
"""

from .aio import Action, Resource
from .errors import FrontageError, NotReady, RenderError, format_exception
from .flow import Dynamic, Errored, For, Loading, Match, Portal, Show, Switch
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
    spawn,
    untrack,
    use,
)
from .renderer import HtmlRenderer, RecordingRenderer, Renderer
from .runtime import in_browser, platform
from .store import Store, snapshot
from .template import html
from .version import __version__
from .view import Element, Mounted, NodeRef, Text, build, component, emit, h, mount, render_to_string, text

__all__ = [
    "Action",
    "Context",
    "Dynamic",
    "Effect",
    "Element",
    "Errored",
    "For",
    "FrontageError",
    "HtmlRenderer",
    "Loading",
    "Match",
    "Memo",
    "Mounted",
    "NodeRef",
    "NotReady",
    "Owner",
    "Portal",
    "RecordingRenderer",
    "RenderEffect",
    "RenderError",
    "Renderer",
    "Resource",
    "Show",
    "Signal",
    "Store",
    "Switch",
    "Text",
    "__version__",
    "batch",
    "build",
    "component",
    "emit",
    "format_exception",
    "get_owner",
    "h",
    "html",
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
    "spawn",
    "text",
    "untrack",
    "use",
]
