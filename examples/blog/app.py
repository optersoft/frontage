"""A content page: three posts read from disk, checked by a schema, rendered once.

Everything here runs on CPython while `frontage prerender` builds the page. The Markdown is
rendered there, the front matter is checked there, and the page that comes out has no boot
tag — except that one post has an `::: island` in it, and that island brings the runtime when
a reader scrolls to it.
"""

from frontage import h, html, mount
from frontage.content import collection
from frontage.schema import iso_date, record, text

Post = record(
    ("title", text(min=1)),
    ("date", iso_date()),
    ("summary", text(), None),
)

posts = collection("posts", Post)


def entry_line(post):
    return html(t"""
        <li>
            <time>{post.data["date"]}</time> — <b>{post.data["title"]}</b>:
            {post.data["summary"] or ""}
        </li>
    """)


def article(post):
    return h.article(h.h2(post.data["title"]), post.view())


def page():
    found = posts.entries()
    return html(t"""
        <main>
            <h1>Notes</h1>
            <p class="lede">{len(found)} posts, read from disk and rendered once.</p>
            <ul class="index">{[entry_line(p) for p in found]}</ul>
            {[article(p) for p in found]}
        </main>
    """)


mount(page, "#app", when="never")
