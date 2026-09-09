"""The layout: an ordinary component taking `children`. There is no new concept here."""

from frontage import h
from frontage.head import Meta, Title


def layout(children, title="Notes", description=None):
    return h.div(
        Title(title),
        Meta(description or "Notes: a site built by frontage from a directory of files.", name="description"),
        h.nav(
            h.a("Notes", href="/"),
            h.a("Blog", href="/blog/"),
            h.a("About", href="/about/"),
        ),
        children,
        h.footer("Built by ", h.code("frontage site"), " — every page is a file."),
    )
