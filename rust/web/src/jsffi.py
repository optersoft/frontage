"""The browser bridge's Python half: proxies for callbacks, `to_js`, awaiting a promise.

`create_proxy(f)` returns a JavaScript function that calls `f`; keep it to remove the
listener later, and call `destroy()` on it when done. `to_js` is the identity: a dict, list
or tuple crosses as a plain object or array at the boundary. `await promise` works on any
JavaScript object with a `then`.
"""

import _jsffi


class JsException(Exception):
    """A JavaScript value thrown into Python; `.value` is the JavaScript object."""

    def __init__(self, value):
        super().__init__(_message(value))
        self.value = value


def _message(value):
    try:
        m = value.message
        if m is not None:
            return str(m)
    except Exception:
        pass
    try:
        return str(value)
    except Exception:
        return "JavaScript error"


class JsProxy:
    """A JavaScript function wrapping a Python callable."""

    __slots__ = ("_pin", "_js")

    def __init__(self, fn):
        self._pin = _jsffi.pin(fn)
        self._js = _jsffi.make_proxy(self._pin)

    def destroy(self):
        if self._pin is not None:
            _jsffi.unpin(self._pin)
            self._pin = None

    def __call__(self, *args):
        return self._js(*args)


def create_proxy(fn):
    return JsProxy(fn)._js


def to_js(obj):
    return obj


def _await(promise):
    """What the VM runs for `await <JavaScript object>`: an asyncio Future the promise settles."""
    import asyncio

    loop = asyncio.get_event_loop()
    fut = loop.create_future()

    def ok(value):
        if not fut.done():
            fut.set_result(value)

    def err(error):
        if not fut.done():
            fut.set_exception(JsException(error))

    promise.then(create_proxy(ok), create_proxy(err))
    return fut.__await__()
