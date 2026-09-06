"""Async as reactive values: `Resource` loads data, `Action` runs a mutation.

A `Resource` wraps an `async def`. It runs once, and again whenever the `source` it was given
changes; it is an accessor of the latest value, and `.loading`, `.error` and `.state` are
accessors too. Reading a resource whose first load is pending raises `NotReady`, which ends the reading
computation quietly and shows the nearest `Loading` boundary's fallback; while a reload is
pending the previous value is returned; reading a failed one raises its error into the
nearest `Errored`. Create resources in component bodies, not inside holes: a hole re-runs
when the resource changes, and a resource created there would be created again each time.

One rule: read every reactive input before the first `await`. After an `await` the tracking
context is gone, so a signal read there is not a dependency.
"""

from . import reactive
from .errors import NotReady
from .reactive import LOADING, Effect, Signal, batch, get_owner, on_cleanup, spawn, untrack, use

__all__ = ["Action", "Resource", "interval", "poll"]

UNRESOLVED = "unresolved"
PENDING = "pending"
READY = "ready"
REFRESHING = "refreshing"
ERRORED = "errored"


# Hydration: the values `python -m frontage prerender` settled, in creation order, while a
# hydrating mount runs; a Resource created then takes the next one and skips its first load.
_hydration = None
# Prerendering: every Resource created, so the prerenderer can wait for them and write their
# values into the page.
_registry = None
# A navigation in progress (the Router): every Resource created while the new route renders
# counts toward `is_routing` until its first load settles.
_navigation = None


def _set_hydration_values(values):
    global _hydration
    _hydration = list(values) if values else None


def _begin_prerender():
    """Start recording every Resource created (the prerenderer waits for them); returns the list."""
    global _registry
    _registry = []
    return _registry


def _end_prerender():
    global _registry
    _registry = None


class Resource:
    def __init__(self, fetcher, source=None, initial=None):
        global _hydration
        self._fetcher = fetcher
        self._source = source
        hydrated = False
        if _hydration:
            initial = _hydration.pop(0)
            hydrated = True
        self._value = Signal(initial, equal=lambda a, b: a is b)
        self._error = Signal(None, equal=lambda a, b: a is b)
        self._state = Signal(READY if hydrated or initial is not None else UNRESOLVED)
        self._generation = 0
        self._task = None
        self._scopes = []
        self._skip_load = hydrated
        self._owner = get_owner()
        self._transition = None
        self._navigation = None
        if _registry is not None:
            _registry.append(self)
        if _navigation is not None and not hydrated and initial is None:
            self._navigation = _navigation
            _navigation._track_resource(self)
        on_cleanup(self._cancel)

        def start(value, prev):
            if self._skip_load:  # the page already shows this value; no refetch on boot
                self._skip_load = False
                return
            self._load(value)

        # Track the source in the compute phase; start the load in the effect phase.
        Effect(lambda: source() if source is not None else None, start)

    # -- reading --------------------------------------------------------------------------------

    def __call__(self):
        """The latest value. While the first load is pending this raises `NotReady`, which
        ends the reading computation quietly and shows the nearest `Loading` fallback; while
        a reload is pending the previous value is returned. A failed load raises its error
        into the nearest `Errored`."""
        state = self._state()
        scope = use(LOADING)
        if scope is not None and state in (PENDING, REFRESHING):
            if scope not in self._scopes:
                self._scopes.append(scope)
                untrack(scope.add, self, state == REFRESHING)
        error = self._error()
        if state == ERRORED and error is not None:
            raise error
        value = self._value()
        if state in (UNRESOLVED, PENDING) and value is None:
            raise NotReady
        return value

    @property
    def value(self):
        return self()

    def peek(self):
        return self._value.peek()

    def loading(self):
        return self._state() in (PENDING, REFRESHING)

    def error(self):
        return self._error()

    def state(self):
        return self._state()

    # -- control --------------------------------------------------------------------------------

    def refetch(self):
        self._load(untrack(self._source) if self._source is not None else None)

    def mutate(self, value):
        with batch():
            self._value.set(value)
            self._error.set(None)
            self._state.set(READY)

    def _cancel(self):
        """Disposal: stop the load in flight and let whoever waits for it stop waiting."""
        self._cancel_task()
        self._release()

    def _cancel_task(self):
        self._generation += 1
        task, self._task = self._task, None
        if task is not None:
            task.cancel()

    def _release(self):
        """The transition and the navigation waiting on this load, if any, stop waiting."""
        transition, self._transition = self._transition, None
        if transition is not None:
            transition._done()
        navigation, self._navigation = self._navigation, None
        if navigation is not None:
            navigation._resource_done(self)

    def _load(self, argument):
        self._cancel_task()  # a superseded load never settles; the new one will, for both waiters
        generation = self._generation
        with batch():
            self._state.set(REFRESHING if self._state.peek() == READY else PENDING)
            self._error.set(None)
        if reactive._transition is not None and self._transition is None:
            self._transition = reactive._transition
            reactive._transition._track()

        async def run():
            try:
                if self._source is not None:
                    value = await self._fetcher(argument)
                else:
                    value = await self._fetcher()
            except Exception as exc:
                if generation == self._generation:
                    self._settle(None, exc)
                return
            if generation == self._generation:
                self._settle(value, None)

        self._task = spawn(run(), self._owner, name=f"Resource({getattr(self._fetcher, '__name__', 'fetcher')})")

    def _settle(self, value, error):
        with batch():
            if error is None:
                self._value.set(value)
                self._state.set(READY)
            else:
                self._state.set(ERRORED)
            self._error.set(error)
            scopes, self._scopes = self._scopes, []
            for scope in scopes:
                scope.remove(self)
            self._release()


class Action:
    """An `async def` run on demand: `dispatch(x)` runs `fn(x)`; `.pending`, `.value`,
    `.input` and `.error` are accessors. What a form submits to."""

    def __init__(self, fn):
        self._fn = fn
        self._pending = Signal(False)
        self._value = Signal(None, equal=lambda a, b: a is b)
        self._input = Signal(None, equal=lambda a, b: a is b)
        self._error = Signal(None, equal=lambda a, b: a is b)
        self._owner = get_owner()
        self._task = None

    def dispatch(self, *args):
        with batch():
            self._pending.set(True)
            self._input.set(args[0] if len(args) == 1 else args)
            self._error.set(None)

        async def run():
            try:
                result = await self._fn(*args)
            except Exception as exc:
                with batch():
                    self._error.set(exc)
                    self._pending.set(False)
                return
            with batch():
                self._value.set(result)
                self._pending.set(False)

        self._task = spawn(run(), self._owner)
        return self._task

    def pending(self):
        return self._pending()

    def value(self):
        return self._value()

    def input(self):
        return self._input()

    def error(self):
        return self._error()


def interval(seconds, start=0):
    """An accessor that counts up every `seconds` seconds, as a task owned here; a hole that
    reads it re-runs on each tick. Stops when the owner is disposed."""
    import asyncio

    tick = Signal(start)

    async def run():
        while True:
            await asyncio.sleep(seconds)
            tick.update(lambda n: n + 1)

    spawn(run(), get_owner())
    return tick


def poll(fetcher, seconds, initial=None):
    """A `Resource` re-run every `seconds` seconds (and on `refetch()`)."""
    return Resource(lambda _tick: fetcher(), source=interval(seconds), initial=initial)
