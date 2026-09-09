def get(site):
    return f"User-agent: *\nAllow: /\nSitemap: {site.url('/sitemap.xml')}\n"
