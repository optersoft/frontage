---
title: A site of files
date: 2026-09-08
summary: The directory is the site map, and every URL exists before anyone asks for it.
---

`pages/index.py` is `/`, `pages/about.py` is `/about/`, and `pages/blog/[slug].py` is one
page per post. Nothing configures that; the tree *is* the routing table, which is the one
part of Astro worth copying exactly.

> A build that knows every URL up front can write a sitemap, and a host that has every file
> never needs a rewrite rule.
