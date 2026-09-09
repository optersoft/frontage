from layouts.site import layout
from posts import posts

from frontage import h


def page():
    latest = posts.entries()[:3]
    return layout(
        h.main(
            h.h1("Notes"),
            h.p("A site of files: one module per page, one Markdown file per post.", cls="lede"),
            h.h2("Latest"),
            h.ul(*[_line(post) for post in latest], cls="index"),
        ),
        title="Notes",
    )


def _line(post):
    return h.li(
        h.time(post.data["date"]),
        h.a(post.data["title"], href=f"/blog/{post.slug}/"),
    )
