---
title: One tree, three languages
date: 2026-09-08
summary: The directory says which language a page is in, and the default says nothing at all.
---

`pages/[lang]/blog/[slug].py` has two parameters: the locale, from a directory, and the slug,
from the file. `static_paths()` returns both, and the build makes one page per pair.

The first locale in `LOCALES` is the default and contributes **no segment**, so English is at
`/blog/one-tree/` and Spanish at `/es/blog/one-tree/`. That is the shape a site with a main
language wants, and it is a list in `site.py` rather than a configuration object.
