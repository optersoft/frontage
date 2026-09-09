"""One sitemap for every locale, with the alternates each page has."""


def get(site):
    entries = []
    for path in site.pages:
        links = "".join(
            f'<xhtml:link rel="alternate" hreflang="{locale}" href="{site.url(other)}"/>'
            for locale, other in site.alternates(path)
        )
        entries.append(f"<url><loc>{site.url(path)}</loc>{links}</url>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">' + "".join(entries) + "</urlset>\n"
    )
