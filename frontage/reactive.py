"""Signals, memos, effects and owners: the reactive graph everything else stands on.

Three kinds of node. A `Signal` holds a value and can be written. A `Memo` derives a value
from other nodes, caches it, and recomputes lazily when something it read has changed. An
`Effect` runs code for the outside world whenever something it read has changed. Reading a
node inside a running memo or effect records a dependency; every run re-records them from
scratch, so a branch that stops reading a signal stops depending on it.

Propagation is synchronous. Writing a signal marks its dependents and, unless a `batch()` is
open, runs the affected effects before `set()` returns; reads always see the new value.
Memos are pulled, not pushed: a marked memo recomputes on its next read (or when an effect
that depends on it runs), and only tells its own dependents if its value actually changed.

Every memo and effect belongs to an `Owner`. Disposing an owner disposes what it owns, runs
its cleanups, and unsubscribes its computations. A computation is itself an owner of what it
created during its last run, which is disposed before the next run.

The module is written in the MicroPython subset: no typing, no dataclasses, no contextlib.
"""

from .errors import NotReady
from .runtime import warn

try:  # the runtime's native graph (rust/vm/src/core.rs); CPython has none
    import _core
except ImportError:
    _core = None

__all__ = [
    "ERRORS",
    "LOADING",
    "Context",
    "Effect",
    "Memo",
    "Optimistic",
    "Owner",
    "RenderEffect",
    "Signal",
    "Transition",
    "batch",
    "get_owner",
    "is_pending",
    "on",
    "on_cleanup",
    "on_mount",
    "provide",
    "run_with_owner",
    "selector",
    "spawn",
    "transition",
    "untrack",
    "use",
    "use_transition",
]


class _Unset:
    """The type of `_UNSET`, so a checker can tell "not passed" from `None`."""


_UNSET = _Unset()

CLEAN = 0  # nothing this node read has changed
CHECK = 1  # something upstream changed; whether it reaches this node is not known yet
DIRTY = 2  # a direct dependency changed; this node must recompute

# Module state. One reactive system per interpreter, which is what a browser page is.
_owner = None  # the Owner new computations are created under
_listener = None  # the computation whose reads are being tracked
_batch_depth = 0
_render_queue = []  # effects to run at the end of the outermost batch, render first
_effect_queue = []
_flushing = False
FLUSH_LIMIT = int(100_000)  # effect runs per batch before the flush is declared a loop

# Development mode: the warnings for the three mistakes the design cannot prevent (a signal
# read inside an async function after tracking ended, a write inside a tracked computation, a
# `For` whose rows never survive an update). `mount(debug=False)` turns them off.
DEBUG: bool = True
_untracking = 0  # depth of `untrack()`: reads there are deliberate, never warned about
_async_tasks = {}  # id(task) -> name, for the tasks whose reads should have been tracked
_warned = set()

# Transitions: while one is open, render effects it dirtied wait in it instead of running,
# and the page keeps showing the previous state until the async work it started settles.
_transition = None  # the Transition whose synchronous part (or whose settle) is running
# The Router's navigation in progress: an async memo created while the new route renders
# counts toward `is_routing` until its first run settles (`aio.Resource` does the same).
_navigation = None
# Prerendering: every Memo created while the prerenderer renders a mount, in creation order,
# so it can wait for the async ones and write their values into the page by ordinal.
_memo_registry = None
# Prerendering too: every async memo whose run starts while a mount renders, wherever it was
# created (a module-level memo the page reads counts), so the prerenderer waits for it.
_memo_started = None
# Hydration: a `_MemoHydration` while a hydrating mount runs; a Memo created then takes its
# ordinal, and an async one settles with the page's value instead of running.
_memo_hydration = None


class _MemoHydration:
    def __init__(self, pairs):
        self.values = {int(k): v for k, v in pairs}
        self.next = 0

    def take(self):
        """The page's value for the next memo created, or `_UNSET`."""
        ordinal = self.next
        self.next = ordinal + 1
        return self.values.pop(ordinal, _UNSET)


def _on_memo_created(memo):
    if _memo_registry is not None:
        _memo_registry.append(memo)
    elif _memo_hydration is not None:
        memo._hydrated = _memo_hydration.take()


def _sync_memo_hook():
    if _core is not None:
        active = _memo_registry is not None or _memo_hydration is not None
        _core.setup(memo_created=_on_memo_created if active else None)


def _begin_prerender():
    global _memo_registry, _memo_started
    _memo_registry = []
    _memo_started = []
    _sync_memo_hook()
    return _memo_registry


def _end_prerender():
    global _memo_registry, _memo_started
    _memo_registry = None
    _memo_started = None
    _sync_memo_hook()


def _set_memo_hydration(pairs):
    """`pairs`: `[[ordinal, value], …]` from the prerendered page, or None when the mount ends."""
    global _memo_hydration
    _memo_hydration = _MemoHydration(pairs) if pairs else None
    _sync_memo_hook()


_open_transitions = []


def _current_owner() -> "Owner | None":
    # The typed way to read the module global; string annotations are never evaluated,
    # so MicroPython does not mind them.
    return _owner


def _current_listener():
    return _core.listener() if _core is not None else _listener


def _current_transition():
    return _core.transition() if _core is not None else _transition


def _set_transition(t):
    global _transition
    if _core is not None:
        _core.set_transition(t)
    else:
        _transition = t


def set_debug(flag):
    """Switch the development warnings; `mount(debug=…)` calls it."""
    global DEBUG
    DEBUG = bool(flag)
    if _core is not None:
        _core.set_debug(DEBUG)


def _same(equal, a, b):
    if equal is None:
        return a == b
    return equal(a, b)


def _warn_once(key, message):
    if key in _warned:
        return
    _warned.add(key)
    warn(message)


def _name_of(fn):
    return getattr(fn, "__name__", None) or type(fn).__name__


def _current_task():
    try:
        import asyncio

        return asyncio.current_task()
    except Exception:
        return None


def _check_untracked_read(signal):
    """Debug: a read with no listener inside a task whose function should have read its inputs
    before its first `await` (a Resource's fetcher, an async Memo's coroutine)."""
    task = _current_task()
    if task is None:
        return
    name = _async_tasks.get(id(task))
    if name is None:
        return
    _warn_once(
        ("async-read", id(task)),
        f"{name}: a signal was read after the first await, so it is not a dependency and nothing "
        "re-runs when it changes. Read it before the first await, pass it in as the source, or "
        "peek() it on purpose.",
    )


def _check_tracked_write(listener):
    _warn_once(
        ("write", id(listener)),
        # One f-string, not two: mpy-cross rejects adjacent f-strings (`f"a" f"b"`), though
        # `f"a" "b"` is fine, so the framework would not cross-compile if this were split.
        f"a signal was written inside a tracked computation ({type(listener).__name__} {_name_of(listener._fn)}), "
        "which then depends on its own write. Write in a handler or in an effect's second function, "
        "or wrap the write in untrack().",
    )


# --- ownership -----------------------------------------------------------------------------


class Owner:
    """A node of the ownership tree. Owns computations and cleanups; carries context.

    ⚠ **Every field is set in `__init__`, even the ones that start at a default.** Moving
    them to class attributes looks like a saving (fewer stores per owner) and measured
    **twice as slow** on MicroPython: an attribute that is not in the instance is looked up
    by walking the class chain, and `_state`, `_queued` and `_disposed` are read on every
    mark, flush and dispose. `_HoleState` does the opposite because it is a flat class whose
    fields are written once and read rarely (2026-09-06, tools/profile_rows.py)."""

    def __init__(self, parent: "Owner | None | _Unset" = _UNSET):
        if isinstance(parent, _Unset):  # one class: cheap on MicroPython, and ty narrows it
            parent = _owner
        self._parent = parent
        self._owned = []
        self._cleanups = []
        self._context = None
        self._disposed = False
        self.name = None  # set by `component` (the function's name); shown by `tree`
        if parent is not None:
            parent._owned.append(self)

    def on_cleanup(self, fn):
        """Run `fn` when this owner is disposed or, for a computation, before it re-runs."""
        self._cleanups.append(fn)
        return fn

    def _dispose_owned(self):
        # Guarded: a computation's first run has nothing to dispose, and the two list
        # allocations per run were measurable on MicroPython (2,000 holes per 1,000 rows).
        if self._owned:
            owned, self._owned = self._owned, []
            for child in reversed(owned):
                child._parent = None  # already being removed; skip the parent-list bookkeeping
                child.dispose()
        if self._cleanups:
            cleanups, self._cleanups = self._cleanups, []
            for fn in reversed(cleanups):
                fn()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._dispose_owned()
        parent = self._parent
        if parent is not None and self in parent._owned:
            parent._owned.remove(self)
        self._parent = None

    def run(self, fn, *args, **kwargs):
        """Run `fn` with this as the current owner and no tracking."""
        return run_with_owner(self, fn, *args, **kwargs)

    def __enter__(self):
        self._saved = (_owner, _listener)
        _set_scope(self, None)
        return self

    def __exit__(self, exc_type, exc, tb):
        _set_scope(*self._saved)
        return False


def _set_scope(owner, listener):
    global _owner, _listener
    _owner = owner
    _listener = listener


def get_owner():
    return _owner


def run_with_owner(owner, fn, *args, **kwargs):
    global _owner, _listener
    saved_owner, saved_listener = _owner, _listener
    _owner, _listener = owner, None
    try:
        return fn(*args, **kwargs)
    finally:
        _owner, _listener = saved_owner, saved_listener


def on_cleanup(fn):
    """Register `fn` on the current owner. Outside any owner it is not registered."""
    if _owner is not None:
        _owner._cleanups.append(fn)  # `Owner.on_cleanup` inlined: a For row registers five
    return fn


class Context:
    """A key for `provide` / `use`, with the value `use` returns when nothing provided it.
    `internal` contexts are the package's own bookkeeping; `tree` does not list them."""

    def __init__(self, default=None, internal=False):
        self.default = default
        self.internal = internal


def provide(ctx, value):
    owner = _current_owner()
    if owner is None:
        raise RuntimeError("provide() needs an owner; call it inside a component or an Owner block")
    if owner._context is None:
        owner._context = {}
    owner._context[ctx] = value
    return value


def use(ctx):
    return lookup(_current_owner(), ctx)


def lookup(owner, ctx):
    """`use(ctx)` starting from a given owner rather than the current one."""
    while owner is not None:
        if owner._context is not None and ctx in owner._context:
            return owner._context[ctx]
        owner = owner._parent
    return ctx.default


# The two boundary contexts. A `Loading` provides a scope with `add(resource)` /
# `remove(resource)`; an `Errored` provides one with `handle(exc)`. They are defined here so
# computations can find them without importing the flow module.
LOADING = Context(None)
ERRORS = Context(None)

_SKIPPED = object()  # what a computation returns when NotReady or an error ended it


def route_error(owner, exc):
    """Hand `exc` to the nearest `Errored` scope above `owner`, or re-raise it."""
    scope = lookup(owner, ERRORS)
    if scope is None:
        raise exc
    scope.handle(exc)


def spawn(coro, owner=None, name=None):
    """Run a coroutine as a task owned by `owner` (the current owner by default): the task is
    cancelled when the owner is disposed, and an exception in it reaches the nearest
    `Errored` above the owner (or is raised on the loop when there is none). With `name`, a
    signal read inside the task (after tracking ended) warns in debug mode."""
    import asyncio

    if owner is None:
        owner = _current_owner()

    async def run():
        task = _current_task() if name is not None else None
        if task is not None:
            _async_tasks[id(task)] = name
            if _core is not None:
                _core.async_task(1)
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            route_error(owner, exc)
        finally:
            if task is not None:
                _async_tasks.pop(id(task), None)
                if _core is not None:
                    _core.async_task(-1)

    task = asyncio.create_task(run())
    if owner is not None:

        def cancel():
            # Not from inside the task itself: a handler that disposes its own owner (an
            # action that navigates away) keeps running to its end. CPython would deliver
            # the cancellation at the next await; MicroPython raises "can't cancel self".
            if task is not _current_task():
                task.cancel()

        owner.on_cleanup(cancel)
    return task


# --- batching and scheduling -----------------------------------------------------------------


def _begin_batch():
    global _batch_depth
    _batch_depth += 1


def _end_batch():
    global _batch_depth
    _batch_depth -= 1
    if _batch_depth == 0:
        _flush()


def _flush():
    global _flushing
    if _flushing:
        return
    _flushing = True
    runs = 0
    render, effects = _render_queue, _effect_queue
    ri = ei = 0  # cursors: `pop(0)` on a list of 2,000 queued holes was quadratic
    try:
        while True:
            if ri < len(render):
                effect = render[ri]
                ri += 1
            elif ei < len(effects):
                effect = effects[ei]
                ei += 1
            else:
                break
            effect._queued = False
            if not effect._disposed:
                # DIRTY is what a freshly queued effect is; `_update_if_necessary` would only
                # re-test that. CHECK (something upstream may have changed) needs the walk.
                effect._run() if effect._state == DIRTY else effect._update_if_necessary()
            runs += 1
            if runs > FLUSH_LIMIT:
                raise RuntimeError(
                    f"reactive update loop: more than {FLUSH_LIMIT} effect runs in one batch. An effect is "
                    "writing a signal it also reads, or a Resource is being created inside a hole."
                )
    finally:
        del render[:]
        del effects[:]
        _flushing = False


class _Batch:
    def __enter__(self):
        _begin_batch()
        return self

    def __exit__(self, exc_type, exc, tb):
        _end_batch()
        return False

    def __call__(self, fn, *args):
        _begin_batch()
        try:
            return fn(*args)
        finally:
            _end_batch()


def batch():
    """`with batch():` defers effects to the end of the block; `batch()(fn)` runs `fn` so."""
    return _Batch()


def _mark(node, state):
    """Mark `node` and everything downstream of it after a change upstream."""
    if node._state >= state:
        return
    node._state = state
    if node._pure:
        for observer in node._observers:
            _mark(observer, CHECK)
    elif not node._queued:
        node._queued = True
        (_render_queue if node._render else _effect_queue).append(node)


def _notify(source):
    """A source changed: mark its observers and run effects if no batch is open."""
    _begin_batch()
    try:
        for observer in list(source._observers):
            _mark(observer, DIRTY)
    finally:
        _end_batch()


# --- sources --------------------------------------------------------------------------------


class Signal:
    """A value that notifies what read it when it changes. Read by calling it."""

    def __init__(self, value, equal=None):
        self._value = value
        self._observers = []
        # Parallel to `_observers`: where this source sits in that observer's `_sources`.
        # It is what makes unsubscribing O(1) — see `_Computation._clear_sources`.
        self._observer_slots = []
        self._equal = equal

    def __call__(self):
        if _listener is not None:
            _listener._track(self)
        elif DEBUG and _async_tasks and _untracking == 0:
            _check_untracked_read(self)
        return self._value

    @property
    def value(self):
        return self()

    def peek(self):
        """Read without recording a dependency."""
        return self._value

    def set(self, value):
        """Write; returns True if the value changed. An equal value notifies nobody."""
        if _same(self._equal, self._value, value):
            return False
        if DEBUG and _listener is not None:
            _check_tracked_write(_listener)
        self._value = value
        _notify(self)
        return True

    def _write(self, value):
        """`set` for the package's own bookkeeping signals, which may legitimately change
        during a tracked read (a Loading scope's count, a For row's index)."""
        if _same(self._equal, self._value, value):
            return False
        self._value = value
        _notify(self)
        return True

    def update(self, fn):
        return self.set(fn(self._value))

    def __repr__(self):
        return f"Signal({self._value!r})"


# --- computations ---------------------------------------------------------------------------


class _Computation(Owner):
    _pure = False
    _render = False
    _urgent = False  # a render effect downstream of an Optimistic write: runs during a transition
    _target = None  # a render effect's "is my output on screen?"; None means assume it is

    def __init__(self, fn):
        Owner.__init__(self)
        self._fn = fn
        self._not_ready = False  # the last run ended in NotReady: a Memo re-raises it to readers
        self._sources = []
        self._slots = []  # parallel to `_sources`: where we sit in that source's `_observers`
        self._source_ids = None  # a set once tracking starts: O(1) membership (a For tracks 1,000+)
        self._state = DIRTY
        self._queued = False

    def _track(self, source):
        key = id(source)
        ids = self._source_ids
        if ids is None:
            ids = self._source_ids = set()
        if key not in ids:
            ids.add(key)
            observers = source._observers
            self._slots.append(len(observers))
            self._sources.append(source)
            observers.append(self)
            source._observer_slots.append(len(self._sources) - 1)

    def _clear_sources(self):
        """Unsubscribe from every source in O(1) each.

        Each side remembers where the other keeps it, so a removal is a swap with the last
        entry rather than a search: scanning was quadratic wherever many computations read
        one node, which is every list (disposing 1,000 rows that share a store's shape node
        was 78 ms of the 88 it took to create and dispose them — tools/profile_rows.py)."""
        sources = self._sources
        if not sources:
            return
        slots = self._slots
        for i in range(len(sources)):
            source = sources[i]
            index = slots[i]
            observers = source._observers
            source_slots = source._observer_slots
            last = observers.pop()
            last_slot = source_slots.pop()
            if index < len(observers):  # something else was last: move it into the hole
                observers[index] = last
                source_slots[index] = last_slot
                last._slots[last_slot] = index
        self._sources = []
        self._slots = []
        self._source_ids = None

    def _compute(self):
        """Run `fn` tracked, as owner and listener, after disposing the previous run's work.

        `NotReady` ends the run quietly (the dependencies read so far stay, so the run repeats
        when they change); any other exception goes to the nearest `Errored`. Both return
        `_SKIPPED`, which the callers treat as "leave things as they are"."""
        global _owner, _listener
        if self._owned or self._cleanups:
            self._dispose_owned()
        if self._sources:
            self._clear_sources()
        saved_owner, saved_listener = _owner, _listener
        _owner = _listener = self
        self._not_ready = False
        try:
            return self._fn()
        except NotReady:
            self._not_ready = True
            return _SKIPPED
        except Exception as exc:
            _owner, _listener = saved_owner, saved_listener
            route_error(self._parent, exc)
            return _SKIPPED
        finally:
            _owner, _listener = saved_owner, saved_listener

    def _run(self):
        raise NotImplementedError

    def _update_if_necessary(self):
        if self._disposed:
            return
        if self._state == CHECK:
            # Pull every memo we read up to date first, so that none of them recomputes in
            # the middle of our own run and marks us again (the diamond would run us twice).
            for source in list(self._sources):
                if isinstance(source, Memo):
                    source._update_if_necessary()
            if self._state == CHECK:
                self._state = CLEAN
        if self._state == DIRTY:
            self._run()

    def dispose(self):
        if self._disposed:
            return
        self._clear_sources()
        Owner.dispose(self)


# The async half of a Memo: plain functions, so the native Memo (rust/vm/src/core.rs) shares
# them with the Python one below. A native memo has no Python __init__, hence the defaults.


def _memo_read_async(self):
    loading, failed = self._loading, self._error
    assert loading is not None and failed is not None
    if loading():
        scope = lookup(_current_owner(), LOADING)
        if scope is not None and scope not in self._scopes:
            self._scopes.append(scope)
            scope.add(self, self._value is not _UNSET)
        if self._value is _UNSET:
            raise NotReady
        return self._value
    error = failed._value
    if error is not None:
        raise error
    return None if self._value is _UNSET else self._value


def _memo_start(self, coro):
    loading, failed = self._loading, self._error
    if loading is None or failed is None:
        loading = self._loading = Signal(False)
        failed = self._error = Signal(None, equal=lambda a, b: a is b)
    self._generation = getattr(self, "_generation", 0) + 1
    generation = self._generation
    failed._write(None)
    if self._value is _UNSET and getattr(self, "_hydrated", _UNSET) is not _UNSET:
        # The page already shows this value: settle with it, no run on boot.
        self._value, self._hydrated = self._hydrated, _UNSET
        loading._write(False)
        coro.close()
        return
    loading._write(True)
    if _memo_started is not None and self not in _memo_started:
        _memo_started.append(self)
    t = _current_transition()
    if t is not None and getattr(self, "_transition", None) is None:
        self._transition = t
        t._track()
    if _navigation is not None and getattr(self, "_navigation", None) is None and self._value is _UNSET:
        self._navigation = _navigation
        _navigation._track_load(self)
    memo = self

    async def run():
        try:
            value = await coro
        except Exception as exc:
            if generation == memo._generation:
                memo._settle(_UNSET, exc)
            return
        if generation == memo._generation:
            memo._settle(value, None)

    spawn(run(), self, name=f"Memo({_name_of(self._fn)})")  # cancelled before a re-run, and on dispose


def _memo_settle(self, value, error):
    loading, failed = self._loading, self._error
    assert loading is not None and failed is not None
    _begin_batch()
    try:
        if error is None:
            self._value = value
        else:
            failed._write(error)
        loading._write(False)
        for observer in list(self._observers):
            _mark(observer, DIRTY)
        scopes, self._scopes = self._scopes, []
        for scope in scopes:
            scope.remove(self)
        self._release()
    finally:
        _end_batch()


def _memo_release(self):
    """The transition and the navigation waiting on this run, if any, stop waiting."""
    transition, self._transition = getattr(self, "_transition", None), None
    if transition is not None:
        transition._done()
    navigation, self._navigation = getattr(self, "_navigation", None), None
    if navigation is not None:
        navigation._load_done(self)


class Memo(_Computation):
    """A cached derived value. Read by calling it; recomputes lazily when a dependency changed.

    Works as a decorator: `@Memo` on a zero-argument function yields the accessor.

    An async memo is a memo whose function returns a coroutine: `Memo(lambda:
    load(user_id()))` with `load` an `async def`. The reads made while *calling* it (before
    any await: `user_id()` here) are its dependencies; the coroutine then runs as a task owned
    by the memo, and the value arrives when it finishes. Meanwhile reading the memo raises
    `NotReady` on the first run (the nearest `Loading` shows its fallback) and returns the
    previous value on later runs; `loading()` says which; an exception in the coroutine is
    raised to readers, into the nearest `Errored`. A re-run cancels the coroutine in flight.
    """

    _pure = True

    def __init__(self, fn, equal=None):
        _Computation.__init__(self, fn)
        self._observers = []
        self._observer_slots = []  # see `Signal`
        self._equal = equal
        self._value = _UNSET
        self._loading = None  # a Signal once the memo has turned out to be async
        self._error = None
        self._generation = 0
        self._scopes = []
        self._transition = None
        self._navigation = None
        self._hydrated = _UNSET  # the prerendered page's value, taken by the first async run
        if _memo_registry is not None:
            _memo_registry.append(self)
        elif _memo_hydration is not None:
            self._hydrated = _memo_hydration.take()

    def __call__(self):
        if _listener is not None:
            _listener._track(self)
        if self._state != CLEAN:
            self._update_if_necessary()
        if self._not_ready:
            # The compute read something not ready (a Resource, an async memo): the reader
            # waits too, under *its* Loading boundary (the memo may live above it), instead
            # of seeing a stale value or None. The run repeats when the source settles.
            scope = lookup(_current_owner(), LOADING)
            if scope is not None and scope not in self._scopes:
                self._scopes.append(scope)
                scope.add(self, self._value is not _UNSET)
            raise NotReady
        if self._loading is not None:
            return self._read_async()
        return self._value

    _read_async = _memo_read_async

    def loading(self):
        """True while the coroutine of an async memo is running (False for a plain memo)."""
        return bool(self._loading()) if self._loading is not None else False

    def error(self):
        return self._error() if self._error is not None else None

    @property
    def value(self):
        return self()

    def peek(self):
        if self._state != CLEAN:
            self._update_if_necessary()
        return None if self._value is _UNSET else self._value

    def _run(self):
        old = self._value
        self._state = CLEAN  # before the run: a write during it must be able to mark us again
        new = self._compute()
        if new is _SKIPPED:
            return  # NotReady: readers get it too (see __call__); an error went to Errored
        if self._scopes and self._loading is None:
            scopes, self._scopes = self._scopes, []  # the boundaries that waited for this run
            for scope in scopes:
                scope.remove(self)
        if hasattr(new, "send") and hasattr(new, "throw"):
            self._start(new)
            return
        if old is _UNSET or not _same(self._equal, old, new):
            self._value = new
            reader = _listener  # whoever's read triggered this first run already has the value
            for observer in list(self._observers):
                if old is _UNSET and observer is reader:
                    continue
                _mark(observer, DIRTY)  # includes the readers that waited through NotReady

    # -- async ------------------------------------------------------------------------------

    _start = _memo_start

    _settle = _memo_settle

    _release = _memo_release

    def is_async(self):
        """True once the memo's function has returned a coroutine."""
        return self._loading is not None

    def dispose(self):
        if self._disposed:
            return
        self._release()
        _Computation.dispose(self)

    def __repr__(self):
        return f"Memo({self._value!r})" if self._value is not _UNSET else "Memo(<unread>)"


class Effect(_Computation):
    """Code for the outside world, re-run when what it read changes.

    Two phases: `compute` runs tracked and returns a value; `effect(value, prev)` runs
    untracked afterwards and may return a cleanup, called before the next `effect` and on
    disposal. `Effect(fn)` alone runs `fn` tracked, which is the rough tool: side effects in
    tracked code subscribe to whatever they happen to read.

    Effects run once at the end of the outermost batch; a plain write is an implicit batch.
    Creating one outside a batch runs it before the constructor returns.
    """

    def __init__(self, compute, effect=None, target=None):
        # `Owner.__init__` and `_Computation.__init__` inlined: an effect is created for every
        # hole and every bound attribute, and the three nested calls cost more on MicroPython
        # than the assignments do (tools/profile_rows.py).
        parent = _owner
        self._parent = parent
        self._owned = []
        self._cleanups = []
        self._context = None
        self._disposed = False
        self.name = None
        if parent is not None:
            parent._owned.append(self)
        self._fn = compute
        self._not_ready = False
        self._sources = []
        self._slots = []
        self._source_ids = None
        self._effect = effect
        self._value = _UNSET
        self._cleanup = None
        self._parked = _UNSET
        self._target = target
        # A fresh effect is DIRTY and queued: `_mark` would only work that out again.
        self._state = DIRTY
        self._queued = True
        (_render_queue if self._render else _effect_queue).append(self)
        if not (_batch_depth or _flushing):
            _begin_batch()  # no batch open: run it before the constructor returns
            _end_batch()

    def _run(self):
        self._state = CLEAN  # before the run, so a write during it re-marks and re-queues us
        value = self._compute()
        if value is _SKIPPED:
            return
        transition = _current_transition()
        if transition is not None and self._render and not self._urgent and self._on_screen():
            # A transition: the compute has built the new state (off screen, under its own
            # owners); what waits for the commit is the effect phase, which would put it on
            # the page. `_queued` stays set so a later mark does not queue us a second time;
            # the mark still makes us DIRTY, and the commit recomputes us in that case.
            self._parked = value
            self._queued = True
            transition._deferred.append(self)
            return
        self._apply(value)

    def _on_screen(self):
        target = self._target
        return True if target is None else bool(target())

    def _apply(self, value):
        global _listener, _untracking
        effect = self._effect
        if effect is not None:
            if self._cleanup is not None:
                self._run_cleanup()
            prev = None if self._value is _UNSET else self._value
            # `untrack(effect, value, prev)`, inlined: this runs once per hole per update.
            saved = _listener
            _listener = None
            _untracking += 1
            try:
                result = effect(value, prev)
            finally:
                _untracking -= 1
                _listener = saved
            if callable(result):
                self._cleanup = result
        self._value = value

    def _commit_parked(self):
        """At a transition's commit: apply what the compute built, or recompute if something
        changed meanwhile (a refetch that settled marks its readers)."""
        parked, self._parked = self._parked, _UNSET
        self._queued = False
        if self._disposed:
            return
        if self._state != CLEAN or parked is _UNSET:
            _mark(self, DIRTY) if self._state == CLEAN else None
            if not self._queued:
                self._queued = True
                _render_queue.append(self)
            return
        self._apply(parked)

    def _run_cleanup(self):
        cleanup, self._cleanup = self._cleanup, None
        if cleanup is not None:
            cleanup()

    def dispose(self):
        if self._disposed:
            return
        self._run_cleanup()
        _Computation.dispose(self)


class RenderEffect(Effect):
    """An `Effect` whose effect phase runs before user effects in the same batch. The view
    layer binds DOM nodes with these, so the DOM is current before user code observes it."""

    _render = True


# --- the native core -------------------------------------------------------------------------

if _core is not None:
    # The runtime holds the graph (rust/vm/src/core.rs): the classes above are the
    # specification and CPython's implementation; here they are the native ones, with the
    # async half of Memo attached and the module state reached through accessors.
    _UNSET = _core.UNSET
    Owner = _core.Owner  # ty: ignore[invalid-assignment]
    Signal = _core.Signal  # ty: ignore[invalid-assignment]
    Memo = _core.Memo  # ty: ignore[invalid-assignment]
    Effect = _core.Effect  # ty: ignore[invalid-assignment]
    RenderEffect = _core.RenderEffect  # ty: ignore[invalid-assignment]
    Memo._start = _memo_start
    Memo._settle = _memo_settle
    Memo._release = _memo_release
    Memo._read_async = _memo_read_async
    _current_owner = _core.get_owner  # ty: ignore[invalid-assignment]
    get_owner = _core.get_owner  # ty: ignore[invalid-assignment]
    run_with_owner = _core.run_with_owner  # ty: ignore[invalid-assignment]
    on_cleanup = _core.on_cleanup  # ty: ignore[invalid-assignment]
    lookup = _core.lookup  # ty: ignore[invalid-assignment]
    route_error = _core.route_error  # ty: ignore[invalid-assignment]
    _begin_batch = _core.begin_batch  # ty: ignore[invalid-assignment]
    _end_batch = _core.end_batch  # ty: ignore[invalid-assignment]
    _mark = _core.mark  # ty: ignore[invalid-assignment]
    _set_scope = _core.set_scope  # ty: ignore[invalid-assignment]
    _core.setup(
        not_ready=NotReady,
        errors=ERRORS,
        loading=LOADING,
        untracked_read=_check_untracked_read,
        tracked_write=_check_tracked_write,
    )


# --- utilities ------------------------------------------------------------------------------


def untrack(fn, *args):
    """Run `fn` without recording dependencies."""
    global _untracking, _listener
    saved = _listener
    _listener = None
    _untracking += 1
    try:
        return fn(*args)
    finally:
        _untracking -= 1
        _listener = saved


if _core is not None:
    untrack = _core.untrack  # ty: ignore[invalid-assignment]


def on(deps, fn):
    """A compute function that depends on exactly `deps` and calls `fn(*values)` untracked.

    `deps` is an accessor or a list of accessors. Use it where an effect must react to some
    signals but read others freely: `Effect(on(trigger, lambda t: do(other())))`.
    """
    single = callable(deps)
    accessors = [deps] if single else list(deps)

    def compute():
        values = [read() for read in accessors]
        return untrack(fn, *values)

    return compute


def on_mount(fn):
    """Run `fn` once, after the current batch, tracking nothing."""
    return Effect(lambda: None, lambda value, prev: fn())


def selector(source, equal=None):
    """`is_selected(key)`: true when `source()` equals `key`, updating only the two rows
    whose answer changed. O(1) per change instead of one notification per row."""
    subscribers = {}

    def apply(value, prev):
        for key in (prev, value):
            node = subscribers.get(key)
            if node is not None:
                node.set(_same(equal, key, value))

    RenderEffect(source, apply)

    def is_selected(key):
        node = subscribers.get(key)
        if node is None:
            node = Signal(_same(equal, key, source.peek() if hasattr(source, "peek") else untrack(source)))
            subscribers[key] = node
            on_cleanup(lambda: subscribers.pop(key, None))
        return node()

    return is_selected


# --- transitions ----------------------------------------------------------------------------


_is_pending = Signal(False)


class Transition:
    """One `transition()`: the render effects it deferred, the async work it waits for, and
    `pending`, an accessor that is True until it commits. `await t.wait()` for the commit."""

    def __init__(self):
        self._deferred = []
        self._inflight = 0
        self._open = True
        self._committed = False
        self._callbacks = []
        self._reverts = []
        self.pending = Signal(True)
        # A function that runs the commit: `document.startViewTransition` when the caller asked
        # for one and the browser has it. The commit is where every parked effect reaches the
        # page at once, which is exactly the snapshot boundary that API wants.
        self.wrapper = None
        self._wrapping = False

    def _track(self):
        self._inflight += 1

    def _done(self):
        self._inflight -= 1
        self._maybe_commit()

    def _maybe_commit(self):
        if self._open or self._committed or self._inflight > 0:
            return
        self._commit()

    def _commit(self):
        if self.wrapper is not None and not self._wrapping:
            self._wrapping = True
            self.wrapper(self._commit)  # calls back into here with the wrapper spent
            return
        self._committed = True
        _open_transitions.remove(self)
        saved = _current_transition()
        _set_transition(None)  # the deferred effects run now, whatever transition is nested around us
        _begin_batch()
        try:
            for revert in self._reverts:
                revert()
            self._reverts = []
            deferred, self._deferred = self._deferred, []
            for effect in deferred:
                effect._commit_parked()
            self.pending._write(False)
            if not _open_transitions:
                _is_pending._write(False)
        finally:
            _end_batch()
            _set_transition(saved)
        callbacks, self._callbacks = self._callbacks, []
        for fn in callbacks:
            fn()

    def on_commit(self, fn):
        """Call `fn()` when the transition has committed (at once, if it already has)."""
        if self._committed:
            fn()
        else:
            self._callbacks.append(fn)
        return fn

    async def wait(self):
        """Await the commit."""
        import asyncio

        while not self._committed:
            await asyncio.sleep(0)

    def __repr__(self):
        return f"Transition({'pending' if not self._committed else 'committed'})"


def view_transition():
    """`document.startViewTransition` as a commit wrapper, or None where there is no such thing.

    Every browser without it — and every server — simply commits, which is what a progressive
    enhancement means: the page changes, it does not animate.
    """
    from .runtime import in_browser

    if not in_browser:
        return None
    from .runtime import create_proxy, document

    start = getattr(document, "startViewTransition", None)
    if start is None:
        return None

    def run(commit):
        try:
            start(create_proxy(commit))
        except Exception:
            commit()  # the browser refused the transition; the page still has to change

    return run


def transition(fn, *args, view=False):
    """Run `fn(*args)` (writes, typically) as a transition: the page keeps showing its
    previous state while the async work those writes started, Resources refetching and async
    memos recomputing, is in flight, and shows the new state all at once when it has settled.
    No `Loading` fallback appears for data that is merely refreshing. `is_pending()` is True
    meanwhile. Returns the `Transition` (its `pending` accessor, `wait()`, `on_commit`).

    The new state is built off screen while the transition is open: a branch or a component
    the writes create is computed at once, under its own owners, so its resources start
    loading immediately and count toward the commit; only the step that would put it on the
    page waits. What is on screen keeps its previous nodes until then.

    `view=True` commits inside `document.startViewTransition`, so the browser cross-fades the
    old page into the new one (and animates whatever carries a `view-transition-name`). Where
    the API does not exist the commit is the ordinary one.
    """
    t = Transition()
    if view:
        t.wrapper = view_transition()
    _open_transitions.append(t)
    _is_pending._write(True)
    saved = _current_transition()
    _set_transition(t)
    _begin_batch()
    try:
        fn(*args)
    finally:
        try:
            _end_batch()
        finally:
            # Closed even when `fn` raised: a transition left open would keep every effect
            # it parked from ever reaching the page.
            _set_transition(saved)
            t._open = False
            t._maybe_commit()
    return t


def use_transition():
    """`(pending, start)`: `start(fn)` runs `fn` as a transition and `pending()` is True while
    any transition started here is in flight."""
    count = Signal(0)

    def start(fn, *args):
        count._write(count._value + 1)
        t = transition(fn, *args)
        t.on_commit(lambda: count._write(count._value - 1))
        return t

    return (lambda: count() > 0), start


def is_pending(target=None):
    """With no argument: True while any transition is in flight. With a Resource, an async
    Memo, an Action or a Transition: whether that one is loading or pending. A reactive read."""
    if target is None:
        return _is_pending()
    loading = getattr(target, "loading", None)
    if loading is not None:
        return bool(loading())
    pending = getattr(target, "pending", None)
    if pending is not None:
        return bool(pending())
    return False


class Optimistic(Signal):
    """A signal whose writes inside a transition show at once and are undone when it commits.

    Outside a transition it is a plain signal. Inside one, `set(v)` renders `v` immediately
    (the effects that read it run despite the transition), and when the transition commits
    the value returns to what it was before, so the committed state is what the page shows:
    the real data, or the previous value if the work failed."""

    def set(self, value):
        t = _current_transition()
        if t is None or t._committed:
            return Signal.set(self, value)
        if self not in [r.__self__ for r in t._reverts if hasattr(r, "__self__")]:
            base = self._value
            t._reverts.append(_Revert(self, base))
        for observer in list(self._observers):
            _flag_urgent(observer)
        return Signal.set(self, value)


class _Revert:
    def __init__(self, signal, value):
        self.__self__ = signal
        self.value = value

    def __call__(self):
        signal = self.__self__
        for observer in list(signal._observers):
            _unflag_urgent(observer)
        Signal.set(signal, self.value)


def _flag_urgent(node):
    if node._pure:
        for observer in node._observers:
            _flag_urgent(observer)
    else:
        node._urgent = True


def _unflag_urgent(node):
    if node._pure:
        for observer in node._observers:
            _unflag_urgent(observer)
    else:
        node._urgent = False


def tree(owner, depth=None):
    """The ownership tree under `owner` as text, one line per owner, for the console.

    A `mount` handle is accepted too. Components show their function's name, computations
    their kind; a context provider shows the keys it provides."""
    root = getattr(owner, "owner", owner)
    lines = []
    _tree_lines(root, 0, lines, depth)
    return "\n".join(lines)


def _tree_lines(owner, level, lines, depth):
    label = owner.name or type(owner).__name__
    fn = getattr(owner, "_fn", None) or getattr(owner, "_compute", None)
    if owner.name is None and fn is not None:
        label += f" {getattr(fn, '__name__', '')}".rstrip()
    context = [k for k in (owner._context or {}) if not getattr(k, "internal", False)]
    if context:
        label += " [" + ", ".join(sorted(str(getattr(k, "name", None) or type(k).__name__) for k in context)) + "]"
    if owner._disposed:
        label += " (disposed)"
    lines.append("  " * level + label)
    if depth is None or level < depth:
        for child in owner._owned:
            _tree_lines(child, level + 1, lines, depth)
