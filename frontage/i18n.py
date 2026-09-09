"""What a page in more than one language has to say about itself.

A frontage site does locales with the tree and nothing else: `pages/[lang]/…`, a
`static_paths()` that returns `site.paths()`, and `LOCALES` in `site.py` whose first entry
is the default and so has no URL segment. That is the whole routing story
(`frontage.cli.site`); this module is the two things a *page* still has to write.

    from frontage.i18n import hreflang, switcher

    def page(lang, site):
        return layout(
            hreflang(site, "/es/blog/"),        # <link rel="alternate" hreflang=…> per locale
            switcher(site, "/es/blog/"),        # the language switcher, as plain links
            ...,
        )

**The switcher is links, not an island.** Every URL the site makes is known at build time, so
the other languages of a page are `<a href>`s — a reader following one waits for a document,
not for a runtime. A switcher that is an island is a runtime downloaded to do what an anchor
already does.

Nothing here is browser code. It runs where the page is rendered, which for a site is always
CPython at build time.
"""

from .view import h

__all__ = ["alternates", "hreflang", "switcher"]

#: What `x-default` should point at: the default locale's copy, which is what a search engine
#: shows a reader whose language matches none of ours.
X_DEFAULT = "x-default"


def alternates(site, path):
    """`[(locale, path)]` for this page in every locale, the current one included."""
    return site.alternates(path)


def hreflang(site, path, x_default=True):
    """The `<link rel="alternate" hreflang=…>` tags for this page, one per locale.

    A crawler reads these and nothing else to learn that `/blog/` and `/es/blog/` are the
    same page in two languages; a page that sets them from script sets them for nobody. They
    are absolute when `BASE` is set, because that is what the tag is specified to carry.
    """
    found = alternates(site, path)
    tags = [h.link(rel="alternate", hreflang=locale, href=site.url(other)) for locale, other in found]
    if x_default and found:
        default = site.default_locale
        target = next((other for locale, other in found if locale == default), found[0][1])
        tags.append(h.link(rel="alternate", hreflang=X_DEFAULT, href=site.url(target)))
    return tags


def switcher(site, path, labels=None, current="current", cls="locales"):
    """The language switcher: one link per locale, and no link for the page you are on.

    `labels` is a mapping from a locale to what to call it — `{"en": "English", "es":
    "Español"}` — because a reader looking for their language is looking for its name in it,
    not for a two-letter code. Without one the code is the label.
    """
    labels = labels or {}
    here = site.locale_of(path)
    items = []
    for locale, other in alternates(site, path):
        label = labels.get(locale, locale)
        if locale == here:
            items.append(h.span(label, cls=current, lang=locale, **{"aria-current": "true"}))
        else:
            items.append(h.a(label, href=other, lang=locale, hreflang=locale))
    return h.nav(*items, cls=cls, **{"aria-label": "Language"})
