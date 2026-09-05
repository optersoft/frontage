# The `pyscript` module as PyScript exposes it on both interpreters. Browser globals are
# JS proxies with no Python type, so Any is the honest annotation.
from typing import Any

document: Any
window: Any
