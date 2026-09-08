"""frontage-table over a windowed source: the rows stay on the server, the grid asks for the
block it shows, and sorting and searching are requests rather than memos."""

import asyncio

from frontage import RecordingRenderer, Signal, mount
from frontage_table import table


class FakeRows:
    """A windowed source over an in-memory list, recording every request it gets."""

    def __init__(self, n=1000):
        self.rows = [{"id": i, "name": f"row {i}"} for i in range(n)]
        self.requests = []
        self.version = Signal(0)

    def key(self):
        return ("rows", self.version())

    async def window(self, key, offset, limit, sort=None, descending=False, search=None):
        self.requests.append((offset, limit, sort, descending, search))
        await asyncio.sleep(0)
        data = self.rows
        if search:
            data = [r for r in data if search in r["name"]]
        if sort:
            data = sorted(data, key=lambda r: r[sort], reverse=descending)
        return len(data), offset, data[offset : offset + limit]


def mounted(view):
    renderer = RecordingRenderer()
    root = renderer.inner.create_element("div")
    mount(view, root, renderer)
    return root


def html(root):
    return "".join(c.to_html() for c in root.children)


async def settle(n=4):
    for _ in range(n):
        await asyncio.sleep(0)


def find(node, cls):
    for child in node.children:
        if child.tag is not None:
            if cls in (child.attrs.get("class") or ""):
                return child
            found = find(child, cls)
            if found is not None:
                return found
    return None


def test_the_grid_asks_for_the_first_block_and_shows_the_servers_total():
    async def scenario():
        rows = FakeRows()
        root = mounted(table(rows, columns=["id", "name"], height=320, row_height=32))
        assert "0 rows" in html(root)
        await settle()
        out = html(root)
        assert "1,000 rows" in out and "row 0" in out and "row 35" in out and "row 36" not in out
        # One request: the block the viewport is in, two windows long (10 + 2*4 = 18 rows each).
        assert rows.requests == [(0, 36, None, False, None)]

    asyncio.run(scenario())


def test_scrolling_into_another_block_is_one_request_and_a_small_scroll_is_none():
    async def scenario():
        rows = FakeRows()
        root = mounted(table(rows, columns=["id", "name"], height=320, row_height=32))
        await settle()
        viewport = find(root, "fr-viewport")
        scroll = viewport.listeners["scroll"][0]

        class Ev:
            def __init__(self, top):
                self.target = type("T", (), {"scrollTop": top})()

        scroll(Ev(64))  # two rows down: still block 0, nothing asked
        await settle()
        assert len(rows.requests) == 1
        scroll(Ev(32 * 700))  # far away: block 19 (700 - 4 = 696 // 18 = 38 * 18 = 684)
        await settle()
        assert rows.requests[-1] == (684, 36, None, False, None)
        out = html(root)
        assert "row 684" in out and "row 0" not in out
        # The rows sit where the server put them, not where the viewport happens to be.
        assert f"translateY({684 * 32}px)" in out

    asyncio.run(scenario())


def test_a_header_click_and_a_search_are_requests_not_memos():
    async def scenario():
        rows = FakeRows()
        query = Signal("")
        root = mounted(table(rows, columns=["id", "name"], search=query, height=320))
        await settle()
        header = find(root, "fr-th")
        header.listeners["click"][0](None)
        await settle()
        assert rows.requests[-1] == (0, 36, "id", False, None)
        header.listeners["click"][0](None)  # the same node: a refetch does not rebuild the header
        await settle()
        assert rows.requests[-1] == (0, 36, "id", True, None)
        assert "row 999" in html(root)
        query.set("row 12")
        await settle()
        assert rows.requests[-1] == (0, 36, "id", True, "row 12")
        assert "11 rows" in html(root)  # 12, 120–129: the server's count, not the page's

    asyncio.run(scenario())


def test_a_change_in_the_sources_key_refetches():
    async def scenario():
        rows = FakeRows()
        mounted(table(rows, columns=["id"], height=320))
        await settle()
        rows.rows.append({"id": 1000, "name": "new"})
        rows.version.set(1)
        await settle()
        assert len(rows.requests) == 2

    asyncio.run(scenario())


def test_the_grid_marks_itself_while_a_block_loads():
    async def scenario():
        rows = FakeRows()
        root = mounted(table(rows, columns=["id"], height=320))
        assert "fr-loading" in html(root)
        await settle()
        assert "fr-loading" not in html(root)

    asyncio.run(scenario())
