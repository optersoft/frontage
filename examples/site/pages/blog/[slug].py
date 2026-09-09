"""One page per post: `static_paths()` says which, `page(slug)` renders each."""

from layouts.site import layout
from posts import posts

from frontage import h


def static_paths():
    return [{"slug": post.slug} for post in posts.entries()]


def page(slug):
    post = posts.get(slug)
    return layout(
        h.article(
            h.h1(post.data["title"]),
            h.p(h.time(post.data["date"]), cls="lede"),
            post.view(),
            h.p(h.a("← every post", href="/blog/")),
        ),
        title=f"{post.data['title']} — Notes",
        description=post.data["summary"],
    )
