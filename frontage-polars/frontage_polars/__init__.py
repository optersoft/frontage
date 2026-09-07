"""frontage-polars: polars on the server, the answers in the page.

The browser half is `client` (`remote`, `Frame`, `RowSource`); the server half is `server`
(`Sources`), which imports polars and FastAPI and is never imported in a page.
"""

from .client import Frame, Remote, RemoteError, RowSource, remote

__all__ = ["Frame", "Remote", "RemoteError", "RowSource", "remote"]
