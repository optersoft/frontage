---
title: A switcher is links
date: 2026-09-03
summary: The build knows every URL, so changing language is an anchor and not a runtime.
---

The language switcher on this page is three elements: two `<a>` and a `<span>` for the one
you are reading. No runtime, no island, no hydration.

That is possible because the build made every page and knows their URLs, so
`site.translate(path, "es")` is an answer rather than a guess. An island here would download
a quarter of a megabyte to do what an anchor does.
