---
title: An endpoint is a module
date: 2026-09-05
summary: sitemap.xml.py has a get(), and that is the whole of the integration story.
---

Astro has an integrations ecosystem, and a large part of what it is for is sitemaps and RSS.
Here a sitemap is a file called `sitemap.xml.py` with a `get()` in it:

```py
def get(site):
    urls = "".join(f"<url><loc>{site.url(p)}</loc></url>" for p in site.pages)
    return f'<?xml version="1.0"?><urlset …>{urls}</urlset>'
```

`site.pages` is every URL the build made, because the build made them before it ran this.
