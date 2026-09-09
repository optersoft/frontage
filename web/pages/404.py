"""`404.html` — Cloudflare Pages serves it, with a 404 status, for any unmatched path
(`public/_redirects` is what makes that a real 404 and not the front page with a 200).

`PATH` is what says the file rather than the directory: a page at `/404/` would never be
found by a host looking for `404.html`.
"""

PATH = "/404.html"

import optersoft_brand as brand  # noqa: E402
from layouts.site import layout  # noqa: E402


def page():
    return layout(
        brand.not_found(
            "Not here",
            "This page does not exist on frontage.optersoft.com. The documentation moved to the academy, "
            "and the old /examples/ pages became the gallery.",
            home={"href": "/", "label": "Home"},
            other={"href": "/gallery/", "label": "The gallery"},
        ),
        title="Not here — Frontage",
        description="No such page on frontage.optersoft.com.",
        noindex=True,
    )
