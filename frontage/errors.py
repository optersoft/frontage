"""Frontage's exception types. Nothing here imports anything of ours."""


class FrontageError(Exception):
    """Base class for every error Frontage raises on purpose."""


class RenderError(FrontageError):
    """A view could not be built or updated."""


class NotReady(FrontageError):
    """Raised inside a reactive computation to end it quietly: the value it needs is not
    there yet. A `Loading` boundary above it shows its fallback until the value arrives.
    Not an error to the user, so it never reaches an `Errored` boundary."""


__all__ = ["FrontageError", "NotReady", "RenderError"]
