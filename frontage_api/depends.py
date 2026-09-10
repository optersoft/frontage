"""`Depends`: a value a route needs, resolved once per request.

    async def current_user(headers):
        token = headers.get("authorization")
        if token is None:
            raise HTTPError(401, "sign in")
        return await lookup(token)

    @app.get("/me", needs={"user": Depends(current_user)})
    async def me(user):
        return user

The one FastAPI feature whose absence is felt immediately, and thirty lines rather than a
framework: a dependency is a function, it may itself declare `needs`, it is resolved once per
request however many routes ask for it, and a generator dependency's second half runs after
the response is built.

A dependency's own parameters come from the same places a handler's do — `headers`, `query`,
`path`, `body`, `scope` by name — so nothing new has to be learned to write one.
"""

__all__ = ["Depends", "resolve"]


class Depends:
    """A callable to resolve, and whether to cache it for the request."""

    def __init__(self, call, cache=True):
        self.call = call
        self.cache = cache
        self.name = getattr(call, "__name__", "dependency")

    def __repr__(self):
        return "<Depends %s>" % self.name


async def resolve(needs, context, cache, finalizers):
    """`{name: Depends}` to `{name: value}`, resolving each one once."""
    out = {}
    for name, dep in needs.items():
        out[name] = await _one(dep, context, cache, finalizers)
    return out


def _awaitable(value):
    from . import _awaitable as test

    return test(value)


async def _one(dep, context, cache, finalizers):
    if dep.cache and dep.call in cache:
        return cache[dep.call]
    inner = getattr(dep.call, "_frontage_api_needs", None)
    arguments = dict(context)
    if inner:
        arguments.update(await resolve(inner, context, cache, finalizers))
    value = dep.call(**_wanted(dep.call, arguments))
    if _awaitable(value):
        value = await value
    if hasattr(value, "__next__"):
        # A generator dependency: everything before its `yield` has run, and the rest runs
        # once the response exists. That is where a handle gets closed and a lock released.
        generator = value
        value = next(generator)
        finalizers.append(generator)
    if dep.cache:
        cache[dep.call] = value
    return value


def _wanted(call, arguments):
    from . import _params_of

    return {name: arguments[name] for name in _params_of(call) if name in arguments}


def finish(finalizers):
    """Run the second half of every generator dependency, in reverse.

    A failure here is reported and does not replace the response: the answer is already
    correct, and a close that raises must not turn a 200 into a 500.
    """
    problems = []
    for generator in reversed(finalizers):
        try:
            next(generator)
        except StopIteration:
            pass
        except Exception as exc:
            problems.append(exc)
    return problems
