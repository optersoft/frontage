"""One collection, a directory per language: `content/posts/<lang>/`."""

from frontage.content import collection
from frontage.schema import iso_date, record, text

Post = record(("title", text(min=1)), ("date", iso_date()), ("summary", text(), None))

posts = collection("posts")


def of(lang):
    return collection("posts", Post, root=posts.root / lang)
