"""The runtime's native template path (rust/vm/src/view.rs); `frontage.view` tries it first."""

from typing import Any

available: bool

def setup(**hooks: Any) -> None: ...
def build_template(element: Any, renderer: Any, cache: Any) -> int | None: ...
