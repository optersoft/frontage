# Whatever the page's pyscript config lists under "js_modules".
from typing import Any

def __getattr__(name: str) -> Any: ...
