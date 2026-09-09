"""Two parameters in one path: the locale from the directory, the slug from the file."""

from layouts.site import layout
from posts import of

from frontage import h

BACK = {"en": "← every note", "es": "← todas las notas", "ca": "← totes les notes"}


def static_paths(site):
    return [{"lang": lang, "slug": post.slug} for lang in site.locales for post in of(lang).entries()]


def page(lang, slug, site):
    post = of(lang).get(slug)
    return layout(
        h.article(
            h.h1(post.data["title"]),
            h.p(h.time(post.data["date"]), cls="lede"),
            post.view(),
            h.p(h.a(BACK[lang], href=site.translate("/blog/", lang))),
        ),
        site,
        site.translate(f"/blog/{slug}/", lang),
        lang,
        title=post.data["title"],
        description=post.data["summary"],
    )
