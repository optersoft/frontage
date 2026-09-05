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

__all__ = [
    "Context",
    "Effect",
    "Memo",
    "Owner",
    "RenderEffect",
    "Signal",
    "batch",
    "get_owner",
    "on",
    "on_cleanup",
    "on_mount",
    "provide",
    "run_with_owner",
    "selector",
    "untrack",
    "use",
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


def _current_owner() -> "Owner | None":
    # The typed way to read the module global; string annotations are never evaluated,
    # so MicroPython does not mind them.
    return _owner


def _same(equal, a, b):
    if equal is None:
        return a == b
    return equal(a, b)


# --- ownership -----------------------------------------------------------------------------


class Owner:
    """A node of the ownership tree. Owns computations and cleanups; carries context."""

    def __init__(self, parent: "Owner | None | _Unset" = _UNSET):
        if isinstance(parent, _Unset):
            parent = _current_owner()
        self._parent = parent
        self._owned = []
        self._cleanups = []
        self._context = None
        self._disposed = False
        if parent is not None:
            parent._owned.append(self)

    def on_cleanup(self, fn):
        """Run `fn` when this owner is disposed or, for a computation, before it re-runs."""
        self._cleanups.append(fn)
        return fn

    def _dispose_owned(self):
        owned, self._owned = self._owned, []
        for child in reversed(owned):
            child._parent = None  # already being removed; skip the parent-list bookkeeping
            child.dispose()
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
    saved = (_owner, _listener)
    _set_scope(owner, None)
    try:
        return fn(*args, **kwargs)
    finally:
        _set_scope(*saved)


def on_cleanup(fn):
    """Register `fn` on the current owner. Outside any owner it is not registered."""
    if _owner is not None:
        _owner.on_cleanup(fn)
    return fn


class Context:
    """A key for `provide` / `use`, with the value `use` returns when nothing provided it."""

    def __init__(self, default=None):
        self.default = default


def provide(ctx, value):
    if _owner is None:
        raise RuntimeError("provide() needs an owner; call it inside a component or an Owner block")
    if _owner._context is None:
        _owner._context = {}
    _owner._context[ctx] = value
    return value


def use(ctx):
    owner = _current_owner()
    while owner is not None:
        if owner._context is not None and ctx in owner._context:
            return owner._context[ctx]
        owner = owner._parent
    return ctx.default


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
    try:
        while _render_queue or _effect_queue:
            queue = _render_queue if _render_queue else _effect_queue
            effect = queue.pop(0)
            effect._queued = False
            if not effect._disposed:
                effect._update_if_necessary()
    finally:
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
        self._equal = equal

    def __call__(self):
        if _listener is not None:
            _listener._track(self)
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

    def __init__(self, fn):
        Owner.__init__(self)
        self._fn = fn
        self._sources = []
        self._state = DIRTY
        self._queued = False

    def _track(self, source):
        if source not in self._sources:
            self._sources.append(source)
            source._observers.append(self)

    def _clear_sources(self):
        for source in self._sources:
            if self in source._observers:
                source._observers.remove(self)
        self._sources = []

    def _compute(self):
        """Run `fn` tracked, as owner and listener, after disposing the previous run's work."""
        self._dispose_owned()
        self._clear_sources()
        saved = (_owner, _listener)
        _set_scope(self, self)
        try:
            return self._fn()
        finally:
            _set_scope(*saved)

    def _run(self):
        raise NotImplementedError

    def _update_if_necessary(self):
        if self._disposed:
            return
        if self._state == CHECK:
            for source in list(self._sources):
                if isinstance(source, Memo):
                    source._update_if_necessary()
                if self._state == DIRTY:
                    break
            if self._state == CHECK:
                self._state = CLEAN
        if self._state == DIRTY:
            self._run()

    def dispose(self):
        if self._disposed:
            return
        self._clear_sources()
        Owner.dispose(self)


class Memo(_Computation):
    """A cached derived value. Read by calling it; recomputes lazily when a dependency changed.

    Works as a decorator: `@Memo` on a zero-argument function yields the accessor.
    """

    _pure = True

    def __init__(self, fn, equal=None):
        _Computation.__init__(self, fn)
        self._observers = []
        self._equal = equal
        self._value = _UNSET

    def __call__(self):
        if _listener is not None:
            _listener._track(self)
        if self._state != CLEAN:
            self._update_if_necessary()
        return self._value

    @property
    def value(self):
        return self()

    def peek(self):
        if self._state != CLEAN:
            self._update_if_necessary()
        return self._value

    def _run(self):
        old = self._value
        new = self._compute()
        self._state = CLEAN
        if old is _UNSET or not _same(self._equal, old, new):
            self._value = new
            if old is not _UNSET:
                for observer in list(self._observers):
                    _mark(observer, DIRTY)

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

    def __init__(self, compute, effect=None):
        _Computation.__init__(self, compute)
        self._effect = effect
        self._value = _UNSET
        self._cleanup = None
        self._state = CLEAN  # so the mark below is a transition and enqueues the first run
        _begin_batch()
        try:
            _mark(self, DIRTY)
        finally:
            _end_batch()

    def _run(self):
        value = self._compute()
        self._state = CLEAN
        if self._effect is not None:
            self._run_cleanup()
            prev = None if self._value is _UNSET else self._value
            result = untrack(self._effect, value, prev)
            if callable(result):
                self._cleanup = result
        self._value = value

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


# --- utilities ------------------------------------------------------------------------------


def untrack(fn, *args):
    """Run `fn` without recording dependencies."""
    saved = (_owner, _listener)
    _set_scope(_owner, None)
    try:
        return fn(*args)
    finally:
        _set_scope(*saved)


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
            if _owner is not None:
                _owner.on_cleanup(lambda: subscribers.pop(key, None))
        return node()

    return is_selected
