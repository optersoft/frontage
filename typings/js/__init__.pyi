# The JavaScript global scope, as PyScript exposes it. Every attribute is a JS proxy.
from typing import Any

def __getattr__(name: str) -> Any: ...
