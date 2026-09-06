"""Development diagnostics, switched on by importing this module in the app.

    import frontage.debug

With it imported, a hydration that had to rebuild nodes reports each mismatch in the
console (`expected <li>, found text 'x'`, `dropped <b>: nothing in the view adopted it`)
instead of a count, and `last_hydration` keeps the `Hydration` cursor of the last mount for
inspection. It costs nothing until something goes wrong, but a shipped app should not
import it: the messages are for the person writing the app.
"""

from .dom import Hydration

__all__ = ["hydration_report", "last_hydration"]

last_hydration: "Hydration | None" = None  # the `Hydration` of the last `mount(hydrate=True)`


def hydration_report():
    """The mismatch lines of the last hydration, in order (empty when it was clean)."""
    return list(last_hydration.details) if last_hydration is not None else []
