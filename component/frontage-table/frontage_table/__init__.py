"""A virtualised data grid for frontage: `st.dataframe`, without the dataframe.

**Pure Python and CSS. No JavaScript, no WebAssembly, no dependency.** That is worth a
sentence, because a grid is where component libraries normally reach for a 200 KB dependency:
the expensive part of a grid is not drawing it, it is *not* drawing the 99,970 rows nobody is
looking at, and a fine-grained reactive framework is already built to do exactly that.

The trick is that the window of rows on screen is a fixed set of elements. Scrolling does not
create or destroy them — it changes what they read, and each cell's own text node updates.
So a hundred-thousand-row table costs about as much as a thirty-row one.

    table(rows, columns=[("name", "Name"), ("qty", "Qty", "{:,}")])

`rows` is an accessor returning a list of dicts. Sorting, filtering and the visible slice are
memos over it, so a change recomputes the slice and nothing else on the page.

**Or a windowed source**, when the rows live on a server and should stay there: any object
with `key()` (tracked; changes when the rows should be re-asked) and
`async window(key, offset, limit, sort, descending, search)` returning `(total, offset,
rows)`. The grid then fetches the block it is scrolled to, sorting and searching are the
server's, and a header click or a keystroke is one request for a few dozen rows.
`frontage_polars.Remote.rows` is one such source; PostgREST would be another.
"""

from frontage import For, Memo, Resource, Signal, h

from .style import STYLESHEET

__all__ = ["STYLESHEET", "Column", "table"]

DEFAULT_ROW_HEIGHT = 32
OVERSCAN = 4  # rows kept beyond each edge, so a fast scroll does not show a gap


class Column:
    """One column. `format` is a `str.format` spec applied to the value, or a callable."""

    def __init__(self, key, label=None, format=None, width=None, align=None):
        self.key = key
        self.label = label if label is not None else key
        self.format = format
        self.width = width
        self.align = align or ("right" if format and "," in str(format) else "left")

    def value(self, row):
        """The raw cell value. Sorting uses this, never `text`: formatting 50,000 cells in
        order to compare them measured 914 ms against 111 ms on MicroPython, and it would sort
        numbers as the strings "1,200" and "70"."""
        return row.get(self.key) if hasattr(row, "get") else getattr(row, self.key, None)

    def text(self, row):
        value = self.value(row)
        if value is None:
            return ""
        if callable(self.format):
            return self.format(value)
        if self.format:
            try:
                return ("{:" + self.format + "}").format(value)
            except (ValueError, TypeError):
                return str(value)
        return str(value)


def _columns(spec, rows):
    if spec is not None:
        return [c if isinstance(c, Column) else Column(*c) if isinstance(c, tuple) else Column(c) for c in spec]
    # Inferred from the first row. Pairs, never a dict's own order: MicroPython does not
    # preserve insertion order, so an inferred header would come out shuffled in the browser.
    first = rows[0] if rows else None
    keys = sorted(first) if first is not None else []
    return [Column(key) for key in keys]


def table(rows, columns=None, height=360, row_height=DEFAULT_ROW_HEIGHT, search=None, sort=None, cls=None, **attrs):
    """A scrolling, sortable grid over `rows` (an accessor returning a list of dicts).

    `search` may be a `Signal` of a query string; rows are kept when the query appears in any
    displayed cell. Pass one you own and a text input elsewhere drives the table.

    `sort` is `(key, descending)` for the order the table opens in; a header click changes it.
    """
    sort_key = Signal(sort[0] if sort else None)
    sort_desc = Signal(bool(sort[1]) if sort and len(sort) > 1 else False)
    scrolled = Signal(0)
    first_visible = Memo(lambda: max(0, int(scrolled() / row_height) - OVERSCAN))
    window = Memo(lambda: int(height / row_height) + OVERSCAN * 2)
    remote = hasattr(rows, "window") and hasattr(rows, "key")

    if remote:
        # The rows are elsewhere. One `Resource` fetches the block the viewport is in, aligned
        # to the window size so a small scroll asks for nothing new, and two windows long so
        # the next block is already here. Its `source` is the whole request, so a header click,
        # a search keystroke, a scroll into a new block or a change in the source's own key is
        # one refetch; a superseded fetch never settles.
        def request():
            start = (first_visible() // window()) * window()
            query = (search() if search is not None else "").strip()
            return (rows.key(), start, window() * 2, sort_key(), sort_desc(), query or None)

        async def fetch(req):
            total, offset, page = await rows.window(req[0], req[1], req[2], req[3], req[4], req[5])
            return {"total": total, "offset": offset, "rows": page}

        fetched = Resource(fetch, source=request, initial={"total": 0, "offset": 0, "rows": []})

        def source():
            return fetched()["rows"]

    else:

        def source():
            return rows() if callable(rows) else rows

    # Declared columns never read the rows, so a refetch or an update leaves the header alone.
    spec = Memo(lambda: _columns(columns, None if columns is not None else source()))

    def filtered():
        data = source()
        query = (search() if search is not None else "").strip().lower()
        if not query:
            return data
        cols = spec()
        return [row for row in data if any(query in col.text(row).lower() for col in cols)]

    def ordered():
        data = filtered()
        key = sort_key()
        if key is None:
            return data
        # `sorted` needs a total order and a column may hold None or mixed types; the string
        # form is the only comparison that always works, and it is what the reader sees anyway.
        column = next((c for c in spec() if c.key == key), None)
        if column is None:
            return data
        descending = sort_desc()
        try:
            return sorted(data, key=column.value, reverse=descending)
        except TypeError:
            # A column holding mixed types, or None beside a number. The string form is the
            # only comparison that always works, and it is what the reader sees anyway.
            return sorted(data, key=column.text, reverse=descending)

    if remote:
        # The fetched rows are shown where the server says they sit, so while the next block
        # loads the previous one stays in place rather than jumping to the new scroll position.
        total = Memo(lambda: fetched()["total"])
        base = Memo(lambda: fetched()["offset"])
        visible = Memo(source)
    else:
        body = Memo(ordered)
        total = Memo(lambda: len(body()))
        base = first_visible
        visible = Memo(lambda: body()[first_visible() : first_visible() + window()])

    def toggle(key):
        def click(ev):
            if sort_key() == key:
                sort_desc.set(not sort_desc())
            else:
                sort_key.set(key)
                sort_desc.set(False)

        return click

    def header_class(key):
        return lambda: "fr-th fr-sorted" if sort_key() == key else "fr-th"

    def caret(key):
        return lambda: "" if sort_key() != key else " ▾" if sort_desc() else " ▴"

    def head():
        return h.div(
            *[
                h.button(
                    col.label,
                    caret(col.key),
                    on_click=toggle(col.key),
                    cls=header_class(col.key),
                    type="button",
                    style_text_align=col.align,
                    style_flex=f"0 0 {col.width}" if col.width else "1 1 0",
                )
                for col in spec()
            ],
            cls="fr-tr fr-head",
        )

    def row_view(row, index):
        # Local rows are keyed by identity: `row` is the dict and `index` an accessor. A fetched
        # page replaces every row, so the remote grid runs `For` in index mode instead: the
        # elements are reused by position, `row` is an accessor and `index` a plain int, and a
        # new page updates the text of the cells that changed.
        get_row = row if remote else (lambda: row)
        at = (lambda: index) if remote else index

        def offset():
            return f"{(base() + at()) * row_height}px"

        return h.div(
            *[
                h.div(
                    (lambda c=col: c.text(get_row())),
                    cls="fr-td",
                    style_text_align=col.align,
                    style_flex=f"0 0 {col.width}" if col.width else "1 1 0",
                )
                for col in spec()
            ],
            cls="fr-tr",
            style_height=f"{row_height}px",
            style_transform=lambda: f"translateY({offset()})",
        )

    def on_scroll(ev):
        scrolled.set(int(ev.target.scrollTop))

    viewport = h.div(
        h.div(
            For(visible, row_view, key=False if remote else None),
            cls="fr-rows",
            style_height=lambda: f"{total() * row_height}px",
        ),
        cls="fr-viewport",
        style_height=f"{height}px",
        on_scroll=on_scroll,
    )
    footer = h.div(lambda: f"{total():,} rows", cls="fr-table-footer")
    base_cls = f"fr-table {cls}" if cls else "fr-table"
    table_cls = (lambda: base_cls + " fr-loading" if fetched.loading() else base_cls) if remote else base_cls
    return h.div(head, viewport, footer, cls=table_cls, **attrs)
