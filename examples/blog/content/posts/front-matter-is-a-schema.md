---
title: Front matter is a schema
date: 2026-08-24
summary: The same record type that checks a form checks a post.
---

`frontage.schema` was written for forms and for what a server sends back. A collection points
it at a directory instead:

```py
Post = record(("title", text(min=1)), ("date", iso_date()), ("summary", text(), None))
posts = collection("posts", Post)
```

A file whose front matter does not match does not become a bad page — it fails the build,
naming the file and every field that is wrong.
