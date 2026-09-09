from layouts.site import layout
from posts import of

from frontage import h

LEDE = {
    "en": "One page tree, three languages, and no configuration but a list.",
    "es": "Un árbol de páginas, tres idiomas y ninguna configuración salvo una lista.",
    "ca": "Un arbre de pàgines, tres idiomes i cap configuració llevat d'una llista.",
}
LATEST = {"en": "Latest", "es": "Lo último", "ca": "El més recent"}


def static_paths(site):
    return site.paths()


def page(lang, site):
    posts = of(lang).entries()
    return layout(
        h.main(
            h.h1("Tres"),
            h.p(LEDE[lang], cls="lede"),
            h.h2(LATEST[lang]),
            h.ul(
                *[h.li(h.a(post.data["title"], href=site.translate(f"/blog/{post.slug}/", lang))) for post in posts],
                cls="index",
            ),
        ),
        site,
        site.translate("/", lang),
        lang,
        title="Tres",
    )
