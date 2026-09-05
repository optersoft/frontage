"""`State`: signals and memos with the ergonomics of a class.

    class Counter(State):
        count = field(0)
        step = field(1)

        @computed
        def double(self):
            return self.count * 2

        def inc(self, ev=None):
            self.count += self.step

    c = Counter()
    c.count        # reads the signal (tracked)
    c.count = 5    # writes it
    c.double       # reads the memo
    c.signal("count")  # the Signal itself, for a template hole

Fields are declared with `field(default)` rather than by annotation, because MicroPython does
not populate `__annotations__`. Each instance gets its own signals and memos. Methods are plain methods, which makes them handlers.
"""

from .reactive import Memo, Signal

__all__ = ["State", "computed", "field"]


class field:
    """A reactive attribute with a default (or a `default_factory` for mutable values)."""

    def __init__(self, default=None, default_factory=None, equal=None):
        self.default = default
        self.default_factory = default_factory
        self.equal = equal
        self.name = None

    def initial(self):
        return self.default_factory() if self.default_factory is not None else self.default


class computed:
    """A memo over the instance; decorate a method that takes only `self`."""

    def __init__(self, fn):
        self.fn = fn
        self.name = getattr(fn, "__name__", None)


class State:
    def __init__(self, **values):
        # Storage goes through object.__setattr__: MicroPython has no __getattribute__ hook
        # and no writable instance __dict__, but it does call a user __getattr__ (for names
        # that are not real attributes) and a user __setattr__.
        signals = {}
        memos = {}
        object.__setattr__(self, "_signals", signals)
        object.__setattr__(self, "_memos", memos)
        declared = _declared(type(self))
        for name, spec in declared.items():
            if isinstance(spec, field):
                signals[name] = Signal(values.pop(name) if name in values else spec.initial(), equal=spec.equal)
        if values:
            raise TypeError(f"{type(self).__name__} has no field {sorted(values)[0]!r}")
        # Memos are created here, under the owner that builds the State, and not on first
        # read: a first read inside a hole would make the hole own the memo and dispose it
        # on its next run. Memos are lazy, so nothing is computed until something reads it.
        for name, spec in declared.items():
            if isinstance(spec, computed):
                memos[name] = Memo(lambda spec=spec: spec.fn(self))

    def __getattr__(self, name):
        # Only reached for names that are not real attributes: fields and computeds are
        # class-level markers, shadowed here by the instance's signals and memos.
        if name.startswith("_"):
            raise AttributeError(name)
        signals = self._signals
        if name in signals:
            return signals[name]()
        memos = self._memos
        if name in memos:
            return memos[name]()
        raise AttributeError(name)

    def __setattr__(self, name, value):
        signals = self._signals
        if name in signals:
            signals[name].set(value)
            return
        raise AttributeError(f"{type(self).__name__} has no field {name!r}; declare it with field()")

    def signal(self, name):
        """The `Signal` behind a field, to bind or to put in a hole."""
        return self._signals[name]

    def memo(self, name):
        """The `Memo` behind a computed."""
        return self._memos[name]

    def snapshot(self):
        """The fields as a plain dict, untracked."""
        return {name: signal.peek() for name, signal in self._signals.items()}


_cache = {}


def _declared(cls):
    """The fields and computeds of a class and its bases (bases first, so a subclass wins).
    Walks `__bases__` rather than `__mro__`, which MicroPython does not provide."""
    found = _cache.get(cls)
    if found is None:
        found = {}
        for base in cls.__bases__:
            if base is not object and base is not State:
                found.update(_declared(base))
        own = [(name, value) for name, value in cls.__dict__.items() if isinstance(value, (field, computed))]
        for name, value in own:
            found[name] = value
            # The marker must leave the class: a class attribute would win the lookup and
            # __getattr__ (which serves the instance's signal) would never be reached.
            delattr(cls, name)
        _cache[cls] = found
    return found
