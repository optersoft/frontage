"""Every page of frontage.optersoft.com: the chrome with this site's brand and links.

The footer is the chrome's default — the company — which is what makes this page and
optersoft.com read as one company at the bottom even though the top of it is the product's.
"""

import optersoft_brand as brand

from frontage import h

BRAND = {"href": "/", "name": "Frontage"}

LINKS = [
    brand.link("https://academy.optersoft.com/python/frontage", "Documentation"),
    brand.link("/gallery/", "Gallery"),
    brand.link("/playground/", "Playground"),
    brand.link("https://pypi.org/project/frontage/", "PyPI"),
    brand.link("https://github.com/optersoft/frontage", "Source"),
]


def layout(children, title, description, canonical=None, noindex=False):
    return [
        brand.head(title, description, canonical=canonical, noindex=noindex, site="Frontage"),
        brand.shell(children, brand=BRAND, links=LINKS),
    ]


CARD = (
    "group flex flex-col gap-2 rounded-2xl border border-slate-200 bg-white p-5 no-underline transition "
    "hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md dark:border-slate-800 dark:bg-slate-900 "
    "dark:hover:border-blue-500/50"
)


def card(href, title, blurb, foot=None):
    """A card that is a link: a title, a blurb, an optional footer row."""
    return h.a(
        h.h2(
            title,
            cls=(
                "text-base font-semibold text-slate-900 group-hover:text-blue-600 dark:text-white "
                "dark:group-hover:text-blue-400"
            ),
        ),
        h.p(blurb, cls="blurb flex-1 text-sm text-slate-600 dark:text-slate-300"),
        foot,
        href=href,
        cls=CARD,
    )
