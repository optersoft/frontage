"""A panel over the running page: what is mounted, and the ownership tree under it.

`frontage serve` compiles this module and runs it in the page, so it is never part of an app
and never in a build. Running it installs the panel; **Ctrl+Shift+D** shows and hides it, and
the button on it re-reads the tree.

It touches the document directly rather than mounting a view of its own, on purpose: a devtools
panel built out of signals and effects would appear in the tree it is trying to show, and would
re-render itself while you read it.
"""

# Absolute imports, unlike every other module here: the dev server hands this module's
# bytecode straight to the runtime, which runs it as `__main__`, and a relative import has no
# package to resolve against there.
from frontage import view
from frontage.reactive import tree
from frontage.runtime import create_proxy, document, in_browser

__all__ = ["install", "refresh", "toggle"]

_ID = "frontage-devtools"
_PANEL = (
    "position:fixed;right:0;bottom:0;z-index:2147483646;width:min(30rem,100vw);max-height:60vh;"
    "overflow:auto;background:#111;color:#eee;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;"
    "border-top:1px solid #333;border-left:1px solid #333;border-radius:8px 0 0 0;box-shadow:0 0 24px #0006"
)
_BAR = "display:flex;gap:.75rem;align-items:center;padding:.5rem .75rem;border-bottom:1px solid #333;position:sticky;top:0;background:#111"
_BUTTON = "background:#222;color:#eee;border:1px solid #444;border-radius:4px;padding:.15rem .5rem;cursor:pointer;font:inherit"


def _panel():
    return document.getElementById(_ID)


def install():
    """Put the panel in the page, hidden, and listen for Ctrl+Shift+D."""
    if not in_browser or _panel() is not None:
        return
    panel = document.createElement("div")
    panel.id = _ID
    panel.setAttribute("style", _PANEL)
    panel.hidden = True

    bar = document.createElement("div")
    bar.setAttribute("style", _BAR)
    label = document.createElement("strong")
    label.textContent = "frontage devtools"
    label.setAttribute("style", "flex:1")
    again = document.createElement("button")
    again.textContent = "refresh"
    again.setAttribute("style", _BUTTON)
    again.addEventListener("click", create_proxy(lambda ev: refresh()))
    close = document.createElement("button")
    close.textContent = "hide"
    close.setAttribute("style", _BUTTON)
    close.addEventListener("click", create_proxy(lambda ev: toggle(False)))
    bar.appendChild(label)
    bar.appendChild(again)
    bar.appendChild(close)

    body = document.createElement("pre")
    body.id = _ID + "-body"
    body.setAttribute("style", "margin:0;padding:.75rem;white-space:pre-wrap")
    panel.appendChild(bar)
    panel.appendChild(body)
    document.body.appendChild(panel)

    def key(event):
        if event.ctrlKey and event.shiftKey and str(event.key).lower() == "d":
            event.preventDefault()
            toggle()

    document.addEventListener("keydown", create_proxy(key))


def toggle(show=None):
    """Show the panel, hide it, or flip it. Showing it re-reads the tree."""
    panel = _panel()
    if panel is None:
        return
    visible = not panel.hidden
    panel.hidden = visible if show is None else not show
    if not panel.hidden:
        refresh()


def refresh():
    """Re-read the page: every live mount, and the ownership tree under each."""
    panel = _panel()
    if panel is None:
        return
    document.getElementById(_ID + "-body").textContent = report()


def report():
    """What the panel shows, as text — useful on its own from a console."""
    mounts = list(view._mounted)
    if not mounts:
        return "nothing is mounted"
    blocks = []
    for handle in mounts:
        lines = tree(handle)
        blocks.append(f"{_target(handle)} — {len(lines.splitlines())} owners\n{lines}")
    return "\n\n".join(blocks)


def _target(handle):
    """What a mount was mounted into, as well as we can say it."""
    parent = getattr(handle, "parent", None)
    node = getattr(parent, "id", None) or getattr(parent, "tag", None)
    return f"#{node}" if getattr(parent, "id", None) else str(node or "mount")


install()
