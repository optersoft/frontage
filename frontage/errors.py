"""Frontage's exception types. Nothing here imports anything of ours."""


class FrontageError(Exception):
    """Base class for every error Frontage raises on purpose."""


class RenderError(FrontageError):
    """A view could not be built or updated."""


class NotReady(FrontageError):
    """Raised inside a reactive computation to end it quietly: the value it needs is not
    there yet. A `Loading` boundary above it shows its fallback until the value arrives.
    Not an error to the user, so it never reaches an `Errored` boundary."""


def format_exception(exc):
    """The traceback of `exc` as text. CPython and Pyodide have `traceback`; MicroPython has
    `sys.print_exception`."""
    try:
        import traceback

        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except ImportError:
        import io
        import sys

        buf = io.StringIO()
        printer = getattr(sys, "print_exception", None)  # MicroPython only; typeshed has no idea
        if printer is None:
            return f"{type(exc).__name__}: {exc}"
        printer(exc, buf)
        return buf.getvalue()


__all__ = ["FrontageError", "NotReady", "RenderError", "format_exception"]
