"""What the server knows: HTML, and the part of it frontage spells differently.

The HTML half is deliberately small — the tags and attributes people actually write, one
line each. Completing every attribute in the specification would bury the six that matter
here, which are frontage's own prefixes: `on:`, `prop:`, `class:`, `style:`, `bind:`,
`attr:` and `ref`. Those are the thing nobody can guess and no other tool will offer, so
they sort first and carry the longest documentation.

The prefix table is the one in `view._classify_uncached`, in the spelling `template.py`
documents. Both spellings work — `on:click` and `on_click` classify the same — but the colon
form is the one for templates and the underscore form the one for the `h` builder, so that
is the order they are offered in.
"""

# --- frontage's own attribute prefixes ----------------------------------------------------------

PREFIXES = [
    (
        "on:",
        "event",
        "A delegated event handler. `on:click={go}` calls `go(event)`; the listener lives on the "
        "mount root, not the node, so a `For` of a thousand rows adds no listeners.",
    ),
    (
        "oncapture:",
        "event",
        "The same, in the capture phase — before the event reaches its target.",
    ),
    (
        "prop:",
        "property",
        "A DOM *property* rather than an attribute. Form controls need this: `prop:value` is what "
        "the input actually shows, `value` is only its initial markup.",
    ),
    (
        "class:",
        "class",
        "Toggle one class from a boolean. `class:active={is_open}` adds and removes `active` and "
        "leaves the rest of `class` alone. Underscores become dashes.",
    ),
    (
        "style:",
        "style",
        "One CSS property. `style:color={shade}` sets it and re-sets it when the signal changes. "
        "Underscores become dashes, so `style:font_size` is `font-size`.",
    ),
    (
        "bind:",
        "two-way",
        "Two-way binding to a signal: `bind:value={name}` reads it into the control and writes the "
        "control back into it. `bind:value`, `bind:checked` and `bind:group` are the three.",
    ),
    (
        "attr:",
        "attribute",
        "Force a plain attribute, for a name that would otherwise be read as a prefix.",
    ),
]

# Spelled without a trailing name.
BARE = [
    (
        "ref",
        "A `NodeRef`: `ref={node}` gives you the DOM node once it exists. The only way to reach a "
        "node the framework made.",
    ),
    (
        "class",
        "The class attribute. May be a string, or a dict of `{name: truthy}` toggles — `cls` and "
        "`class_` spell it too, for the builder, where `class` is a keyword.",
    ),
]

BIND_TARGETS = {
    "value": "The control's value, as text. Inputs, textareas, selects.",
    "checked": "A checkbox's or radio's checked state, as a bool.",
    "group": "A radio group or a multi-select: the signal holds the chosen value, or a list of them.",
}

EVENTS = [
    "click", "dblclick", "input", "change", "submit", "focus", "blur", "keydown", "keyup", "keypress",
    "mousedown", "mouseup", "mouseenter", "mouseleave", "mousemove", "mouseover", "mouseout",
    "pointerdown", "pointerup", "pointermove", "pointerenter", "pointerleave", "touchstart", "touchend",
    "touchmove", "wheel", "scroll", "drag", "dragstart", "dragend", "dragover", "drop", "paste", "copy",
    "cut", "select", "reset", "invalid", "load", "error", "animationend", "transitionend", "contextmenu",
]  # fmt: skip

# --- HTML ---------------------------------------------------------------------------------------

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

TAGS = {
    "a": "A hyperlink. Inside a router, prefer frontage's `A` so it navigates without a page load.",
    "abbr": "An abbreviation, with its expansion in `title`.",
    "address": "Contact details for the nearest article or body.",
    "article": "A self-contained composition.",
    "aside": "Content tangential to what surrounds it.",
    "audio": "Sound content.",
    "b": "Draws attention without extra importance. `<strong>` if you mean importance.",
    "blockquote": "A quotation set off from the text.",
    "body": "The document's content.",
    "br": "A line break.",
    "button": 'A button. `type="button"` unless you want it to submit a form.',
    "canvas": "A bitmap you draw on with a script.",
    "caption": "A table's title.",
    "cite": "The title of a work.",
    "code": "A fragment of computer code.",
    "col": "A column in a `<colgroup>`.",
    "colgroup": "A group of table columns.",
    "datalist": "Suggested values for an input.",
    "dd": "The description in a description list.",
    "details": "A disclosure widget.",
    "dialog": "A dialog box or modal.",
    "div": "A generic block container with no meaning of its own.",
    "dl": "A description list.",
    "dt": "The term in a description list.",
    "em": "Stress emphasis.",
    "embed": "External content, by plugin.",
    "fieldset": "A group of form controls.",
    "figcaption": "A caption for a `<figure>`.",
    "figure": "Self-contained content with an optional caption.",
    "footer": "A footer for the nearest section.",
    "form": "A form. With frontage's `ActionForm` it submits through an `Action`.",
    "h1": "A top-level heading. One per page.",
    "h2": "A section heading.",
    "h3": "A sub-section heading.",
    "h4": "A fourth-level heading.",
    "h5": "A fifth-level heading.",
    "h6": "A sixth-level heading.",
    "head": "Metadata about the document.",
    "header": "Introductory content for the nearest section.",
    "hr": "A thematic break.",
    "i": "An alternate voice — a term, a taxonomic name, a thought.",
    "iframe": "A nested browsing context.",
    "img": "An image. `alt` is not optional.",
    "input": "A form control. Bind it with `bind:value` or `bind:checked`.",
    "label": "A caption for a control. `for` ties it to the control's id.",
    "legend": "A caption for a `<fieldset>`.",
    "li": "A list item.",
    "link": "A link to an external resource, usually a stylesheet.",
    "main": "The dominant content of the document. One per page.",
    "map": "An image map.",
    "mark": "Text marked for reference.",
    "menu": "A list of commands.",
    "meta": "Metadata that no other element expresses.",
    "meter": "A scalar value within a known range.",
    "nav": "A section of navigation links.",
    "noscript": "Content for when scripts are off.",
    "object": "External resource, treated as an image or nested context.",
    "ol": "An ordered list.",
    "optgroup": "A group of options.",
    "option": "One option in a select.",
    "output": "The result of a calculation.",
    "p": "A paragraph. It cannot contain a block element — the browser closes it first.",
    "picture": "An image with several sources.",
    "pre": "Preformatted text; whitespace is kept.",
    "progress": "Progress of a task.",
    "q": "A short inline quotation.",
    "s": "Text no longer accurate.",
    "samp": "Sample output from a program.",
    "script": "A script. In a frontage page the app is loaded by PyScript, not here.",
    "section": "A generic standalone section.",
    "select": "A drop-down. Bind it with `bind:value`.",
    "small": "Side comments, small print.",
    "source": "One media or image source.",
    "span": "A generic inline container with no meaning of its own.",
    "strong": "Strong importance.",
    "style": "Style information for the document.",
    "sub": "Subscript.",
    "summary": "The visible heading of a `<details>`.",
    "sup": "Superscript.",
    "svg": "An SVG fragment.",
    "table": "Tabular data. A `<tr>` needs a `<tbody>` around it — write it, or the browser will.",
    "tbody": "The body rows of a table.",
    "td": "A table cell.",
    "template": "Markup that is not rendered until a script clones it.",
    "textarea": "A multi-line text control.",
    "tfoot": "The footer rows of a table.",
    "th": "A table header cell.",
    "thead": "The header rows of a table.",
    "time": "A date or time, machine-readable in `datetime`.",
    "tr": "A table row.",
    "track": "A text track for media.",
    "u": "Text with a non-textual annotation.",
    "ul": "An unordered list.",
    "var": "A variable.",
    "video": "Video content.",
    "wbr": "An optional line-break opportunity.",
}

GLOBAL_ATTRS = {
    "id": "A unique id. `unique_id()` gives you one that survives prerendering.",
    "class": "The class list; a dict of toggles also works.",
    "style": "Inline styles.",
    "title": "Advisory text, shown as a tooltip.",
    "hidden": "Hide the element.",
    "lang": "The element's language.",
    "dir": "Text direction: ltr, rtl, auto.",
    "tabindex": "Where the element sits in tab order.",
    "role": "The ARIA role.",
    "draggable": "Whether the element can be dragged.",
    "contenteditable": "Whether the element's content is editable.",
    "spellcheck": "Whether to spell-check the content.",
    "accesskey": "A keyboard shortcut.",
    "autofocus": "Focus this element when the page loads.",
    "inert": "Make the element and its subtree non-interactive.",
    "part": "Shadow-DOM part names.",
    "slot": "The slot this element goes in.",
}

TAG_ATTRS = {
    "a": {
        "href": "The destination.",
        "target": "Where to open it.",
        "rel": "The relationship.",
        "download": "Download rather than navigate.",
    },
    "img": {
        "src": "The image URL.",
        "alt": "Text alternative. Required.",
        "width": "Intrinsic width.",
        "height": "Intrinsic height.",
        "loading": "eager or lazy.",
        "srcset": "Candidate sources.",
        "sizes": "Sizes for srcset.",
        "decoding": "sync, async or auto.",
    },
    "input": {
        "type": "The control's kind.",
        "name": "The name submitted with the form.",
        "value": "The initial value — use `prop:value` for the live one.",
        "placeholder": "Hint text.",
        "checked": "Initially checked.",
        "disabled": "Not interactive.",
        "readonly": "Cannot be edited.",
        "required": "Must have a value.",
        "min": "Minimum.",
        "max": "Maximum.",
        "step": "Granularity.",
        "pattern": "A validation regex.",
        "autocomplete": "Autofill hint.",
        "multiple": "Accept more than one value.",
        "accept": "File types for type=file.",
    },
    "textarea": {
        "rows": "Visible rows.",
        "cols": "Visible columns.",
        "placeholder": "Hint text.",
        "disabled": "Not interactive.",
        "readonly": "Cannot be edited.",
        "required": "Must have a value.",
        "maxlength": "Maximum length.",
        "wrap": "hard or soft.",
    },
    "select": {
        "name": "The name submitted with the form.",
        "multiple": "Allow several.",
        "size": "Visible rows.",
        "disabled": "Not interactive.",
        "required": "Must have a value.",
    },
    "option": {
        "value": "The value submitted.",
        "selected": "Initially selected.",
        "disabled": "Not selectable.",
        "label": "Shorter label.",
    },
    "button": {
        "type": "button, submit or reset.",
        "disabled": "Not interactive.",
        "name": "Submitted name.",
        "value": "Submitted value.",
        "form": "The form it belongs to.",
    },
    "form": {
        "action": "Where to submit.",
        "method": "get or post.",
        "novalidate": "Skip validation.",
        "enctype": "Encoding for post.",
        "autocomplete": "Autofill hint.",
    },
    "label": {"for": "The id of the control. Spelled `for_` in the builder."},
    "td": {"colspan": "Columns spanned.", "rowspan": "Rows spanned.", "headers": "Ids of the header cells."},
    "th": {
        "colspan": "Columns spanned.",
        "rowspan": "Rows spanned.",
        "scope": "row, col, rowgroup or colgroup.",
        "abbr": "Short label.",
    },
    "link": {
        "rel": "The relationship.",
        "href": "The resource.",
        "type": "Its MIME type.",
        "media": "Which media it applies to.",
    },
    "meta": {
        "name": "The metadata name.",
        "content": "Its value.",
        "charset": "The encoding.",
        "property": "An Open Graph property.",
    },
    "script": {
        "src": "The script URL.",
        "type": "Its type.",
        "defer": "Run after parsing.",
        "async": "Run as soon as it loads.",
    },
    "video": {
        "src": "The video URL.",
        "controls": "Show the controls.",
        "autoplay": "Start on load.",
        "loop": "Repeat.",
        "muted": "Start muted.",
        "poster": "A still to show first.",
        "playsinline": "Do not go fullscreen on mobile.",
    },
    "audio": {
        "src": "The audio URL.",
        "controls": "Show the controls.",
        "autoplay": "Start on load.",
        "loop": "Repeat.",
        "muted": "Start muted.",
    },
    "details": {"open": "Start expanded."},
    "dialog": {"open": "Start shown."},
    "ol": {"start": "First number.", "reversed": "Count down.", "type": "Numbering style."},
    "time": {"datetime": "The machine-readable value."},
    "progress": {"value": "How far along.", "max": "The total."},
    "meter": {
        "value": "The value.",
        "min": "Minimum.",
        "max": "Maximum.",
        "low": "Low bound.",
        "high": "High bound.",
        "optimum": "The optimum.",
    },
    "iframe": {
        "src": "The URL.",
        "title": "What it contains. Required for accessibility.",
        "loading": "eager or lazy.",
        "sandbox": "Restrictions.",
        "allow": "Permissions policy.",
    },
}

# --- frontage's own API, for hover and for completing inside `{…}` -------------------------------

API = {
    "Signal": "A value that remembers who read it. `count = Signal(0)`; `count()` reads, `count.set(1)` writes.",
    "Memo": "A derived value, recomputed only when what it read changed. Async when its function returns a coroutine.",
    "Effect": "Runs after the render phase, and again when its dependencies change.",
    "RenderEffect": "An effect that owns part of the page. A transition parks its output until the new state is ready.",
    "Owner": "The scope a reactive graph belongs to; disposing it disposes everything under it.",
    "batch": "Apply several writes and notify once.",
    "untrack": "Read without becoming a dependency.",
    "on": "Explicit dependencies for an effect or memo, instead of whatever it happens to read.",
    "on_mount": "Run once, after the first render.",
    "on_cleanup": "Run when the owning scope is disposed.",
    "provide": "Put a value in the context of the current owner.",
    "use": "Read the nearest provided value.",
    "selector": "Turn one signal into many cheap per-item booleans — a selected row costs two updates, not n.",
    "spawn": "Start a coroutine under the current owner, with a name for the debug warnings.",
    "transition": "Build the new state off screen and swap it in when it is ready.",
    "use_transition": "A `(is_pending, start)` pair for driving a transition from an event.",
    "is_pending": "True while the enclosing transition is still resolving.",
    "Optimistic": "A value that shows the expected result immediately; effects downstream of it never park.",
    "Store": "A deep reactive wrapper over dicts and lists; reads track the path they touched.",
    "reconcile": "Replace a store's contents while keeping the identity of rows that did not change.",
    "snapshot": "A plain, non-reactive copy of a store.",
    "html": 'Build a view from a template string: `html(t"<p>{name}</p>")`.',
    "h": "The builder form of the same thing, for when a template string will not do.",
    "component": "Mark a function as a component: it gets its own owner, so its effects die with it.",
    "mount": "Attach a view to a DOM node. `hydrate=True` adopts prerendered HTML instead of building it.",
    "unique_id": "An id that is the same on the server and in the browser. Counts per mount.",
    "render_to_string": "Render a view to HTML without a browser.",
    "Show": "Render one branch or the other. The branch is built lazily.",
    "For": "Render a list by identity, so a reorder moves nodes instead of rebuilding them.",
    "Switch": "The first `Match` whose condition holds.",
    "Match": "One arm of a `Switch`.",
    "Loading": "A boundary that shows a fallback while the resources under it are unresolved.",
    "Errored": "A boundary that catches errors raised under it and renders a fallback.",
    "Dynamic": "Render a component chosen at runtime.",
    "Portal": "Render into a different part of the document.",
    "Resource": "An async read tied to its inputs; refetches when they change, and hydrates by creation order.",
    "Action": "An async write, with pending and error state you can render.",
    "interval": "Call something on a timer, cleaned up with its owner.",
    "poll": "Re-run a resource on a timer.",
    "Router": "The routing tree. Three modes: hash, history and memory.",
    "Route": "One route in the tree.",
    "A": "A link that navigates inside the app instead of loading a page.",
    "Navigate": "Navigate as a side effect of rendering.",
    "Redirect": "Replace the current entry rather than pushing one.",
    "ActionForm": "A `<form>` that submits through an `Action`.",
    "use_params": "The current route's path parameters.",
    "use_query": "The current query string, as a reactive mapping.",
    "use_location": "The current location.",
    "use_navigate": "A function that navigates.",
    "State": "A class whose `field`s are signals and whose `computed`s are memos.",
    "field": "A reactive field on a `State`.",
    "computed": "A derived value on a `State`.",
    "NodeRef": "What `ref={…}` fills in: the DOM node, once it exists.",
    "NotReady": "Raised by a resource that has not resolved; a `Loading` boundary catches it.",
}

# Components that take children, offered as snippets inside `{…}`.
FLOW_SNIPPETS = {
    "Show": "Show(when=${1:cond}, fallback=${2:None})",
    "For": "For(each=${1:items}, key=${2:None})",
    "Switch": "Switch(",
    "Match": "Match(when=${1:cond})",
    "Loading": "Loading(fallback=${1:spinner})",
    "Errored": "Errored(fallback=${1:show_error})",
    "Dynamic": "Dynamic(component=${1:which})",
    "Portal": 'Portal(mount="${1:#modal}")',
}


def attributes_for(tag):
    """Every attribute worth offering on `tag`, most specific first."""
    merged = {}
    merged.update(TAG_ATTRS.get(tag, {}))
    for name, doc in GLOBAL_ATTRS.items():
        merged.setdefault(name, doc)
    return merged
