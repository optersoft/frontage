# MicroPython's own browser FFI (ports/webassembly, modjsffi.c). PyScript wrapped these and
# added nothing the package used, so frontage talks to them directly. Every name is Any: the
# real objects are JavaScript proxies with no Python type.
from typing import Any

def create_proxy(obj: Any, /) -> Any: ...
def to_js(obj: Any, /, **kwargs: Any) -> Any: ...
