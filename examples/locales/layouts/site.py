"""The layout: the chrome, the alternates, and a language switcher that is plain links."""

from frontage import h
from frontage.head import Meta, Title
from frontage.i18n import hreflang, switcher

NAMES = {"en": "English", "es": "Español", "ca": "Català"}

HOME = {"en": "Home", "es": "Inicio", "ca": "Inici"}
BLOG = {"en": "Notes", "es": "Notas", "ca": "Notes"}


def layout(children, site, path, lang, title, description=None):
    return h.div(
        Title(title),
        Meta(description or title, name="description"),
        # What tells a crawler that these three pages are one page in three languages.
        hreflang(site, path),
        h.header(
            h.nav(
                h.a(HOME[lang], href=site.translate("/", lang)),
                " · ",
                h.a(BLOG[lang], href=site.translate("/blog/", lang)),
            ),
            switcher(site, path, labels=NAMES),
        ),
        children,
        h.footer(
            h.code("frontage site"), " — ", str(len(site.pages)), " pages, ", str(len(site.locales)), " languages"
        ),
    )
