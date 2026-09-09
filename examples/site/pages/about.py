from layouts.site import layout

from frontage import h


def page(site):
    return layout(
        h.main(
            h.h1("About"),
            h.p("This page takes an argument called ", h.code("site"), ", so the build hands it one."),
            h.p(f"It has {len(site.pages)} pages, and it lives at {site.base}."),
        ),
        title="About — Notes",
    )
