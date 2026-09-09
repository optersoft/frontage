"""The collection every page reads: one schema, one directory."""

from frontage.content import collection
from frontage.schema import iso_date, record, text

Post = record(
    ("title", text(min=1)),
    ("date", iso_date()),
    ("summary", text(), None),
)

posts = collection("posts", Post)
