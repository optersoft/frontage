"""Nested reactivity over plain dicts and lists.

A `Store` wraps a dict or a list. Reading `store["k"]` (or `store.k`) inside a computation
subscribes to that key alone; a key nobody has read costs nothing. Nested containers come
back wrapped, so `store["user"]["name"]` subscribes to exactly that path. Structure (length,
iteration, membership) has its own node, so a loop over the store re-runs on insertions and
not on a change to one value.

Writes go through `store.set(fn)`: `fn` receives the store with writing enabled, mutates it
with ordinary Python (`d["k"] = v`, `d["items"].append(x)`, `del d["k"]`), and every key
touched is notified once, inside one batch. Outside `set()` the store is read-only.

Python has no `Proxy`; dunder methods do the same job here.
"""

from .reactive import Signal, batch

__all__ = ["Store", "reconcile", "snapshot"]

_MISSING = object()
_writing = []  # a stack, so nested set() calls are fine


def _is_container(value):
    return isinstance(value, (dict, list))


class Store:
    def __init__(self, data):
        if not _is_container(data):
            raise TypeError("Store wraps a dict or a list")
        object.__setattr__(self, "_raw", data)
        object.__setattr__(self, "_nodes", {})  # key -> Signal of the value
        # Bumps on any structural change and, for lists, on any write: iteration, len, and
        # membership subscribe to this one node instead of to a node per key. A `For` over a
        # list of 1,000 rows therefore tracks one node, and a swap notifies it once.
        object.__setattr__(self, "_shape", Signal(0, equal=lambda a, b: False))
        object.__setattr__(self, "_wrapped", {})  # key -> Store for a nested container

    # -- reads ------------------------------------------------------------------------------

    def _read(self, key):
        raw = self._raw
        value = raw[key]
        node = self._nodes.get(key)
        if node is None:
            from . import reactive

            if reactive._listener is not None:
                node = Signal(value, equal=lambda a, b: a is b)
                self._nodes[key] = node
        if node is not None:
            node()  # subscribe
        return self._wrap(key, value)

    def __getitem__(self, key):
        return self._read(key)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raw = self._raw
        if isinstance(raw, dict) and name in raw:
            return self._read(name)
        raise AttributeError(name)

    def __len__(self):
        self._shape()
        return len(self._raw)

    def __iter__(self):
        self._shape()
        raw = self._raw
        if isinstance(raw, dict):
            return iter(list(raw))
        return iter([self._wrap(i, raw[i]) for i in range(len(raw))])

    def _wrap_row(self, row):
        """The Store wrapper for a raw row already in this list (by identity)."""
        raw = self._raw
        for i in range(len(raw)):
            if raw[i] is row:
                return self._wrap(i, row)
        raise KeyError("row is not in this store")

    def _wrap(self, key, value):
        """A nested container comes back as a Store (cached per key); anything else as is."""
        if _is_container(value):
            wrapped = self._wrapped.get(key)
            if wrapped is None or wrapped._raw is not value:
                wrapped = Store(value)
                self._wrapped[key] = wrapped
            return wrapped
        return value

    def __contains__(self, key):
        self._shape()
        return key in self._raw

    def __bool__(self):
        self._shape()
        return bool(self._raw)

    def get(self, key, default=None):
        self._shape()
        if key in self._raw:
            return self._read(key)
        return default

    def keys(self):
        self._shape()
        return list(self._raw.keys())

    def items(self):
        return [(k, self._read(k)) for k in self.keys()]

    def values(self):
        return [self._read(k) for k in self.keys()]

    def __eq__(self, other):
        if isinstance(other, Store):
            other = other._raw
        return self._raw == other

    def __repr__(self):
        return f"Store({self._raw!r})"

    # -- writes (inside set() only) ---------------------------------------------------------

    def set(self, fn):
        """Apply `fn(store)` with writing enabled, notifying each key touched once."""
        _writing.append(self)
        try:
            with batch():
                fn(self)
        finally:
            _writing.pop()

    def set_path(self, *path_and_value):
        """`set_path("user", "name", value)`: the path form of `set`."""
        if len(path_and_value) < 2:
            raise TypeError("set_path needs at least one key and a value")
        *path, value = path_and_value

        def apply(store):
            target = store
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value

        self.set(apply)

    def _check_writing(self):
        if not _writing:
            raise TypeError("a Store is read-only outside store.set(...)")

    def _notify_key(self, key):
        node = self._nodes.get(key)
        if node is not None:
            node.set(self._raw[key] if key in _keys(self._raw) else _MISSING)

    def _notify_shape(self):
        self._shape.set(self._shape.peek() + 1)

    def __setitem__(self, key, value):
        self._check_writing()
        raw = self._raw
        existed = key in _keys(raw)
        if existed and raw[key] == value and type(raw[key]) is type(value):
            return
        raw[key] = value
        self._wrapped.pop(key, None)
        self._notify_key(key)
        if not existed or isinstance(raw, list):
            self._notify_shape()

    def __setattr__(self, name, value):
        self[name] = value

    def __delitem__(self, key):
        self._check_writing()
        raw = self._raw
        if isinstance(raw, list):
            del raw[key]
            self._wrapped.clear()
            self._notify_from(key)
        else:
            del raw[key]
            self._wrapped.pop(key, None)
            self._notify_key(key)
        self._notify_shape()

    # list mutators: every index at or after the change is notified, plus the shape
    def _notify_from(self, index):
        for key in list(self._nodes):
            if isinstance(key, int) and key >= index:
                node = self._nodes[key]
                node.set(self._raw[key] if key < len(self._raw) else _MISSING)

    def append(self, value):
        self._check_writing()
        self._raw.append(value)
        self._notify_shape()

    def extend(self, values):
        self._check_writing()
        self._raw.extend(values)
        self._notify_shape()

    def insert(self, index, value):
        self._check_writing()
        self._raw.insert(index, value)
        self._wrapped.clear()
        self._notify_from(index)
        self._notify_shape()

    def pop(self, index=-1):
        self._check_writing()
        raw = self._raw
        if index < 0:
            index += len(raw)
        value = raw.pop(index)
        self._wrapped.clear()
        self._notify_from(index)
        self._notify_shape()
        return value

    def remove(self, value):
        self.pop(self._raw.index(value))

    def clear(self):
        self._check_writing()
        self._raw.clear()
        self._wrapped.clear()
        self._notify_from(0)
        self._notify_shape()

    def update(self, other):
        self._check_writing()
        for key, value in other.items():
            self[key] = value


def _keys(raw):
    if isinstance(raw, dict):
        return raw
    return range(len(raw))


def snapshot(store):
    """The plain data behind a store (the live object, not a copy)."""
    return store._raw if isinstance(store, Store) else store


def reconcile(store, data, key="id"):
    """Update a list `Store` from fresh `data` so rows whose key survives keep their identity.

    The list ends up equal to `data` (same order), but a row already present is mutated in
    place rather than replaced, so a `For` over the store moves its node instead of rebuilding
    it, and holes reading the row's other keys update only if those keys changed. Rows whose
    key is gone are removed; new keys are appended in place. `key` is a dict key or a function.
    """
    getter = key if callable(key) else (lambda row: row[key])

    def apply(draft):
        raw = draft._raw
        existing = {}
        for row in raw:
            existing[getter(row)] = row
        new_list = []
        for incoming in data:
            k = getter(incoming)
            row = existing.get(k)
            if row is not None and isinstance(row, dict) and isinstance(incoming, dict):
                wrapped = draft._wrap_row(row)
                for field, value in incoming.items():
                    if field not in row or row[field] != value:
                        wrapped[field] = value
                for field in list(row):
                    if field not in incoming:
                        del wrapped[field]
                new_list.append(row)
            else:
                new_list.append(incoming)
        if [id(r) for r in raw] != [id(r) for r in new_list]:
            raw[:] = new_list
            draft._wrapped.clear()
            draft._notify_from(0)
            draft._notify_shape()

    store.set(apply)
