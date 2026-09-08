"""asyncio for frontage's runtime: tasks over coroutines, a ready queue and timers.

Natively the loop blocks in `_frontage.sleep_ms` between timers; in the browser the loop is
driven by JavaScript (`setTimeout` for timers, a microtask for the ready queue), so nothing
here blocks and `run` returns after the first turn. The surface is what the framework and
its tests use: run, create_task, current_task, sleep, gather, wait_for, Event, Future, Task,
Lock, Queue, CancelledError, TimeoutError, get_event_loop, get_running_loop, iscoroutine.
"""

import _frontage

CancelledError = CancelledError  # the builtin
TimeoutError = TimeoutError

_PENDING = "PENDING"
_DONE = "DONE"
_CANCELLED = "CANCELLED"


class InvalidStateError(Exception):
    pass


class Future:
    def __init__(self, loop=None):
        self._loop = loop or get_event_loop()
        self._state = _PENDING
        self._result = None
        self._exception = None
        self._callbacks = []

    def done(self):
        return self._state != _PENDING

    def cancelled(self):
        return self._state == _CANCELLED

    def result(self):
        if self._state == _CANCELLED:
            raise CancelledError()
        if self._state != _DONE:
            raise InvalidStateError("Result is not ready.")
        if self._exception is not None:
            raise self._exception
        return self._result

    def exception(self):
        if self._state == _CANCELLED:
            raise CancelledError()
        if self._state != _DONE:
            raise InvalidStateError("Exception is not set.")
        return self._exception

    def set_result(self, value):
        if self._state != _PENDING:
            raise InvalidStateError("invalid state")
        self._result = value
        self._state = _DONE
        self._wake()

    def set_exception(self, exc):
        if self._state != _PENDING:
            raise InvalidStateError("invalid state")
        if isinstance(exc, type):
            exc = exc()
        self._exception = exc
        self._state = _DONE
        self._wake()

    def cancel(self, msg=None):
        if self._state != _PENDING:
            return False
        self._state = _CANCELLED
        self._wake()
        return True

    def add_done_callback(self, fn):
        if self._state != _PENDING:
            self._loop.call_soon(fn, self)
        else:
            self._callbacks.append(fn)

    def remove_done_callback(self, fn):
        before = len(self._callbacks)
        self._callbacks = [c for c in self._callbacks if c is not fn]
        return before - len(self._callbacks)

    def _wake(self):
        callbacks = self._callbacks
        self._callbacks = []
        for fn in callbacks:
            self._loop.call_soon(fn, self)

    def __await__(self):
        if not self.done():
            yield self
        return self.result()

    __iter__ = __await__

    def get_loop(self):
        return self._loop


class Task(Future):
    def __init__(self, coro, loop=None, name=None):
        super().__init__(loop)
        self._coro = coro
        self._name = name or "Task"
        self._waiting = None
        self._cancel_requested = False
        self._loop.call_soon(self._step)

    def get_name(self):
        return self._name

    def get_coro(self):
        return self._coro

    def cancel(self, msg=None):
        if self.done():
            return False
        self._cancel_requested = True
        if self._waiting is not None:
            self._waiting.cancel()
        else:
            self._loop.call_soon(self._step)
        return True

    def _step(self, _fut=None):
        if self.done():
            return
        self._waiting = None
        previous = self._loop._current
        self._loop._current = self
        try:
            if self._cancel_requested:
                self._cancel_requested = False
                result = self._coro.throw(CancelledError())
            else:
                result = self._coro.send(None)
        except StopIteration as e:
            self._loop._current = previous
            Future.set_result(self, e.value)
            return
        except CancelledError:
            self._loop._current = previous
            Future.cancel(self)
            return
        except BaseException as e:
            self._loop._current = previous
            Future.set_exception(self, e)
            if not self._callbacks:
                # Nobody awaits this task: say so now, the way CPython's loop logs it, rather
                # than let a failing task vanish.
                import sys

                sys.stderr.write("Task exception was never retrieved: %s\n" % (self._name,))
                sys.print_exception(e)
            return
        self._loop._current = previous
        if isinstance(result, Future):
            self._waiting = result
            result.add_done_callback(self._step)
        elif result is None:
            self._loop.call_soon(self._step)
        else:
            self._loop.call_soon(self._step)

    def __repr__(self):
        return "<Task %s %s>" % (self._name, self._state)


class Handle:
    def __init__(self, fn, args, when=None):
        self.fn = fn
        self.args = args
        self.when = when
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def cancelled(self):
        return self._cancelled


class EventLoop:
    def __init__(self):
        self._ready = []
        self._timers = []  # (when, seq, handle)
        self._seq = 0
        self._current = None
        self._running = False
        self._stopped = False

    def time(self):
        return _frontage.monotonic()

    def call_soon(self, fn, *args):
        h = Handle(fn, args)
        self._ready.append(h)
        return h

    def call_later(self, delay, fn, *args):
        return self.call_at(self.time() + delay, fn, *args)

    def call_at(self, when, fn, *args):
        h = Handle(fn, args, when)
        self._seq += 1
        self._timers.append((when, self._seq, h))
        self._timers.sort(key=lambda t: (t[0], t[1]))
        return h

    def create_task(self, coro, name=None):
        return Task(coro, self, name)

    def create_future(self):
        return Future(self)

    def _run_ready(self):
        ready = self._ready
        self._ready = []
        for h in ready:
            if not h._cancelled:
                h.fn(*h.args)

    def _move_due(self):
        now = self.time()
        while self._timers and self._timers[0][0] <= now:
            _, _, h = self._timers.pop(0)
            if not h._cancelled:
                self._ready.append(h)

    def run_once(self):
        """One turn: due timers, then everything ready. Returns the seconds until the next
        timer, or None when nothing is pending."""
        self._move_due()
        self._run_ready()
        if self._ready:
            return 0.0
        while self._timers and self._timers[0][2]._cancelled:
            self._timers.pop(0)
        if self._timers:
            return max(0.0, self._timers[0][0] - self.time())
        return None

    def run_until_complete(self, fut):
        fut = ensure_future(fut, loop=self)
        self._running = True
        try:
            while not fut.done():
                wait = self.run_once()
                if wait is None:
                    if fut.done():
                        break
                    raise RuntimeError("Event loop stopped before Future completed.")
                if wait > 0:
                    _frontage.sleep_ms(wait * 1000)
        finally:
            self._running = False
        return fut.result()

    def run_forever(self):
        self._running = True
        self._stopped = False
        try:
            while not self._stopped:
                wait = self.run_once()
                if wait is None:
                    break
                if wait > 0:
                    _frontage.sleep_ms(wait * 1000)
        finally:
            self._running = False

    def stop(self):
        self._stopped = True

    def is_running(self):
        return self._running

    def close(self):
        pass


_loop = None


def get_event_loop():
    global _loop
    if _loop is None:
        _loop = EventLoop()
    return _loop


def get_running_loop():
    loop = get_event_loop()
    return loop


def new_event_loop():
    return EventLoop()


def set_event_loop(loop):
    global _loop
    _loop = loop


def iscoroutine(obj):
    return type(obj).__name__ == "coroutine"


def iscoroutinefunction(fn):
    return getattr(getattr(fn, "__code__", None), "co_flags", 0) & 0x80 != 0


def ensure_future(obj, loop=None):
    if isinstance(obj, Future):
        return obj
    if iscoroutine(obj):
        return Task(obj, loop)
    if hasattr(obj, "__await__"):
        return Task(_wrap_awaitable(obj), loop)
    raise TypeError("An asyncio.Future, a coroutine or an awaitable is required")


async def _wrap_awaitable(obj):
    return await obj


def create_task(coro, name=None):
    return Task(coro, get_event_loop(), name)


def current_task(loop=None):
    return get_event_loop()._current


def all_tasks(loop=None):
    return set()


def run(main, debug=None):
    loop = get_event_loop()
    if _frontage.browser:
        # The page's glue pumps the loop from timers; nothing here may block.
        return ensure_future(main, loop)
    return loop.run_until_complete(main)


async def sleep(delay, result=None):
    if delay <= 0:
        await _yield()
        return result
    loop = get_event_loop()
    fut = Future(loop)
    loop.call_later(delay, _set_result_unless_cancelled, fut, result)
    return await fut


def _set_result_unless_cancelled(fut, value):
    if not fut.done():
        fut.set_result(value)


class _Yield:
    def __await__(self):
        yield None
        return None


def _yield():
    return _Yield()


def gather(*aws, return_exceptions=False):
    loop = get_event_loop()
    outer = Future(loop)
    children = [ensure_future(a, loop) for a in aws]
    if not children:
        outer.set_result([])
        return outer
    remaining = [len(children)]
    results = [None] * len(children)

    def done(i):
        def cb(fut):
            if outer.done():
                return
            if fut.cancelled():
                exc = CancelledError()
            else:
                exc = fut.exception()
            if exc is not None and not return_exceptions:
                outer.set_exception(exc)
                return
            results[i] = exc if exc is not None else fut.result()
            remaining[0] -= 1
            if remaining[0] == 0:
                outer.set_result(results)
        return cb

    for i, c in enumerate(children):
        c.add_done_callback(done(i))
    return outer


async def wait_for(aw, timeout):
    loop = get_event_loop()
    fut = ensure_future(aw, loop)
    if timeout is None:
        return await fut
    waiter = Future(loop)
    handle = loop.call_later(timeout, _set_result_unless_cancelled, waiter, None)

    def on_done(f):
        if not waiter.done():
            waiter.set_result(None)

    fut.add_done_callback(on_done)
    await waiter
    handle.cancel()
    if fut.done():
        return fut.result()
    fut.cancel()
    raise TimeoutError()


def shield(aw):
    return ensure_future(aw)


class Event:
    def __init__(self):
        self._set = False
        self._waiters = []

    def is_set(self):
        return self._set

    def set(self):
        if not self._set:
            self._set = True
            waiters = self._waiters
            self._waiters = []
            for w in waiters:
                if not w.done():
                    w.set_result(True)

    def clear(self):
        self._set = False

    async def wait(self):
        if self._set:
            return True
        fut = Future(get_event_loop())
        self._waiters.append(fut)
        return await fut


class Lock:
    def __init__(self):
        self._locked = False
        self._waiters = []

    def locked(self):
        return self._locked

    async def acquire(self):
        if not self._locked:
            self._locked = True
            return True
        fut = Future(get_event_loop())
        self._waiters.append(fut)
        await fut
        self._locked = True
        return True

    def release(self):
        if not self._locked:
            raise RuntimeError("Lock is not acquired.")
        self._locked = False
        while self._waiters:
            w = self._waiters.pop(0)
            if not w.done():
                w.set_result(True)
                break

    async def __aenter__(self):
        await self.acquire()
        return None

    async def __aexit__(self, t, v, tb):
        self.release()
        return False


class Queue:
    def __init__(self, maxsize=0):
        self._items = []
        self._getters = []

    def qsize(self):
        return len(self._items)

    def empty(self):
        return not self._items

    def put_nowait(self, item):
        self._items.append(item)
        while self._getters:
            g = self._getters.pop(0)
            if not g.done():
                g.set_result(None)
                break

    async def put(self, item):
        self.put_nowait(item)

    def get_nowait(self):
        if not self._items:
            raise QueueEmpty()
        return self._items.pop(0)

    async def get(self):
        while not self._items:
            fut = Future(get_event_loop())
            self._getters.append(fut)
            await fut
        return self._items.pop(0)


class QueueEmpty(Exception):
    pass
