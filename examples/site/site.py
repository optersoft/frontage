"""What the whole site knows about itself: where it lives, and what moved."""

BASE = "https://notes.example"


def redirects():
    """`_redirects`, the shape every static host reads."""
    return [
        ("/posts/*", "/blog/:splat", 301),
        ("/rss", "/rss.xml", 301),
    ]
