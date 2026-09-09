"""An endpoint: a module with `get()`, written at its own name."""

from posts import posts  # noqa: F401  (imported so a change to the posts rebuilds this too)


def get(site):
    urls = "".join(f"<url><loc>{site.url(path)}</loc></url>" for path in site.pages)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'
