from layouts.site import layout
from posts import posts

from frontage import h


def page():
    return layout(
        h.main(
            h.h1("Blog"),
            h.p("Every post below is a Markdown file, checked by a schema.", cls="lede"),
            h.ul(
                *[
                    h.li(
                        h.time(post.data["date"]),
                        h.a(post.data["title"], href=f"/blog/{post.slug}/"),
                        h.p(post.data["summary"] or ""),
                    )
                    for post in posts.entries()
                ],
                cls="index",
            ),
        ),
        title="Blog — Notes",
    )
