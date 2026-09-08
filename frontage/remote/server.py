"""`from frontage.remote.server import Sources` — the server half, which lives in `_server`.

The implementation moved behind an underscore because `frontage build` packs every module of a
component that does not start with one, and it was shipping fifteen kilobytes of FastAPI and
polars imports into every page — larger than the browser half itself, and never imported there.

This file stays because that import path is the published API: it is in this package's README,
in `pyproject.toml`'s own comment, in the trips example, and in 0.2.0 on PyPI. Renaming it
outright would break every caller to save a hundred bytes, having already saved the fifteen
thousand that mattered.
"""

from ._server import *  # noqa: F403
from ._server import Sources

__all__ = ["Sources"]
