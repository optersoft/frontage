from layouts.site import layout
from posts import of

from frontage import h

TITLE = {"en": "Notes", "es": "Notas", "ca": "Notes"}


def static_paths(site):
    return site.paths()


def page(lang, site):
    return layout(
        h.main(
            h.h1(TITLE[lang]),
            h.ul(
                *[
                    h.li(
                        h.time(post.data["date"]),
                        " ",
                        h.a(post.data["title"], href=site.translate(f"/blog/{post.slug}/", lang)),
                    )
                    for post in of(lang).entries()
                ],
                cls="index",
            ),
        ),
        site,
        site.translate("/blog/", lang),
        lang,
        title=TITLE[lang],
    )
