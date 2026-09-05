"""SPEC §4, C1–C15. No browser."""

import pytest

from frontage.reactive import (
    Context,
    Effect,
    Memo,
    Owner,
    RenderEffect,
    Signal,
    batch,
    get_owner,
    on,
    on_cleanup,
    on_mount,
    provide,
    run_with_owner,
    selector,
    untrack,
    use,
)


def runs_of(fn):
    """Wrap `fn` so the returned list records every call's result."""
    log = []

    def wrapped():
        v = fn()
        log.append(v)
        return v

    return wrapped, log


# C1 ------------------------------------------------------------------------------------------
def test_signal_read_write_update_and_value_alias():
    s = Signal(1)
    assert s() == 1 and s.value == 1 and s.peek() == 1
    assert s.set(2) is True
    assert s() == 2
    s.update(lambda n: n * 10)
    assert s.value == 20


# C2 ------------------------------------------------------------------------------------------
def test_equal_write_notifies_nobody():
    s = Signal([1])
    compute, log = runs_of(lambda: s())
    Effect(compute)
    assert len(log) == 1
    assert s.set([1]) is False  # == but not identical
    assert len(log) == 1
    s.set([2])
    assert len(log) == 2


def test_custom_equality_function():
    s = Signal(1.0, equal=lambda a, b: abs(a - b) < 0.5)
    compute, log = runs_of(lambda: s())
    Effect(compute)
    s.set(1.2)
    assert len(log) == 1
    s.set(2.0)
    assert len(log) == 2


# C3 ------------------------------------------------------------------------------------------
def test_dependencies_are_dynamic():
    flag, a, b = Signal(True), Signal("a"), Signal("b")
    compute, log = runs_of(lambda: a() if flag() else b())
    Effect(compute)
    assert log == ["a"]
    b.set("B")  # not read while flag is true
    assert log == ["a"]
    flag.set(False)
    assert log == ["a", "B"]
    a.set("A")  # no longer read
    assert log == ["a", "B"]
    b.set("BB")
    assert log == ["a", "B", "BB"]


# C4 ------------------------------------------------------------------------------------------
def test_memo_caches_and_recomputes_lazily():
    s = Signal(1)
    compute, log = runs_of(lambda: s() * 2)
    m = Memo(compute)
    assert log == []  # nothing computed until read
    assert m() == 2 and m() == 2
    assert len(log) == 1
    s.set(5)
    assert len(log) == 1  # marked, not recomputed
    assert m() == 10
    assert len(log) == 2


def test_memo_notifies_only_when_its_value_changed():
    s = Signal(1)
    parity = Memo(lambda: s() % 2)
    compute, log = runs_of(lambda: parity())
    Effect(compute)
    assert log == [1]
    s.set(3)  # parity unchanged
    assert log == [1]
    s.set(4)
    assert log == [1, 0]


# C5 ------------------------------------------------------------------------------------------
def test_propagation_is_synchronous():
    s = Signal(1)
    m = Memo(lambda: s() + 1)
    seen = []
    Effect(lambda: seen.append(m()))
    s.set(10)
    assert m() == 11
    assert seen == [2, 11]


# C6 ------------------------------------------------------------------------------------------
def test_batch_runs_an_effect_once():
    a, b = Signal(1), Signal(2)
    compute, log = runs_of(lambda: a() + b())
    Effect(compute)
    with batch():
        a.set(10)
        b.set(20)
        assert log == [3]  # deferred
    assert log == [3, 30]


def test_plain_write_is_an_implicit_batch_and_effects_can_write():
    a = Signal(0)
    b = Signal(0)
    Effect(lambda: b.set(a() * 2))
    compute, log = runs_of(lambda: b())
    Effect(compute)
    a.set(3)
    assert b() == 6 and log == [0, 6]


def test_batch_callable_form():
    a = Signal(1)
    compute, log = runs_of(lambda: a())
    Effect(compute)
    batch()(lambda: (a.set(2), a.set(3)))
    assert log == [1, 3]


# C7 ------------------------------------------------------------------------------------------
def test_two_phase_effect_with_cleanup():
    s = Signal("x")
    events = []

    def effect(value, prev):
        events.append(("run", value, prev))
        return lambda: events.append(("cleanup", value))

    e = Effect(lambda: s(), effect)
    assert events == [("run", "x", None)]
    s.set("y")
    assert events == [("run", "x", None), ("cleanup", "x"), ("run", "y", "x")]
    e.dispose()
    assert events[-1] == ("cleanup", "y")


def test_effect_phase_is_untracked():
    a, b = Signal(1), Signal(1)
    runs = []
    Effect(lambda: a(), lambda v, p: runs.append(b()))
    b.set(2)  # read only in the effect phase: not a dependency
    assert runs == [1]
    a.set(2)
    assert runs == [1, 2]


# C8 ------------------------------------------------------------------------------------------
def test_render_effects_run_before_user_effects():
    s = Signal(0)
    order = []
    Effect(lambda: s(), lambda v, p: order.append("user"))
    RenderEffect(lambda: s(), lambda v, p: order.append("render"))
    order.clear()
    s.set(1)
    assert order == ["render", "user"]


# C9 ------------------------------------------------------------------------------------------
def test_diamond_is_glitch_free():
    a = Signal(1)
    b = Memo(lambda: a() + 1)
    c = Memo(lambda: a() * 10)
    compute, log = runs_of(lambda: (b(), c()))
    Effect(compute)
    a.set(2)
    assert log == [(2, 10), (3, 20)]  # once per change, never (3, 10) or (2, 20)


def test_deep_chain_recomputes_each_memo_once():
    a = Signal(1)
    counts = {"b": 0, "c": 0}

    def fb():
        counts["b"] += 1
        return a() + 1

    def fc():
        counts["c"] += 1
        return b() + 1

    b = Memo(fb)
    c = Memo(fc)
    Effect(lambda: c())
    a.set(2)
    a.set(3)
    assert counts == {"b": 3, "c": 3}


# C10 -----------------------------------------------------------------------------------------
def test_untrack_reads_without_subscribing():
    a, b = Signal(1), Signal(1)
    compute, log = runs_of(lambda: a() + untrack(b))
    Effect(compute)
    b.set(5)
    assert log == [2]
    a.set(2)
    assert log == [2, 7]


def test_on_depends_on_exactly_its_deps():
    trigger, other = Signal(0), Signal("a")
    seen = []
    Effect(on(trigger, lambda t: seen.append((t, other()))))
    other.set("b")
    assert seen == [(0, "a")]
    trigger.set(1)
    assert seen == [(0, "a"), (1, "b")]


def test_on_with_several_deps():
    a, b = Signal(1), Signal(2)
    seen = []
    Effect(on([a, b], lambda x, y: seen.append(x + y)))
    b.set(3)
    assert seen == [3, 4]


# C11 -----------------------------------------------------------------------------------------
def test_memo_and_effect_as_decorators():
    s = Signal(2)
    log = []

    @Memo
    def double():
        return s() * 2

    @Effect
    def _():
        log.append(double())

    assert double() == 4 and log == [4]
    s.set(3)
    assert log == [4, 6]


# C12 -----------------------------------------------------------------------------------------
def test_owner_dispose_order_and_effect_cancellation():
    s = Signal(0)
    events = []
    with Owner() as root:
        with Owner():
            on_cleanup(lambda: events.append("inner-1"))
            on_cleanup(lambda: events.append("inner-2"))
            Effect(lambda: s(), lambda v, p: events.append(("effect", v)))
        on_cleanup(lambda: events.append("outer"))
    assert events == [("effect", 0)]
    root.dispose()
    assert events[1:] == ["inner-2", "inner-1", "outer"]  # children first, cleanups reversed
    s.set(1)
    assert len(events) == 4  # the effect is gone


def test_disposing_a_computation_unsubscribes_it():
    s = Signal(0)
    e = Effect(lambda: s())
    assert s._observers == [e]
    e.dispose()
    assert s._observers == []


# C13 -----------------------------------------------------------------------------------------
def test_rerun_disposes_the_previous_runs_work():
    s = Signal(0)
    events = []

    def compute():
        v = s()
        on_cleanup(lambda: events.append(("cleanup", v)))
        Effect(lambda: events.append(("child", v)))
        return v

    Effect(compute)
    assert events == [("child", 0)]
    s.set(1)
    assert events == [("child", 0), ("cleanup", 0), ("child", 1)]


def test_nested_effect_created_in_a_run_is_disposed_with_it():
    outer, inner = Signal(0), Signal(0)
    log = []
    e = Effect(lambda: (outer(), Effect(lambda: log.append(inner())))[0])
    inner.set(1)
    assert log == [0, 1]
    e.dispose()
    inner.set(2)
    assert log == [0, 1]


# C14 -----------------------------------------------------------------------------------------
def test_context_resolves_through_the_owner_tree():
    Theme = Context("light")
    seen = {}
    with Owner():
        provide(Theme, "dark")
        with Owner():
            seen["inner"] = use(Theme)
    seen["outside"] = use(Theme)
    assert seen == {"inner": "dark", "outside": "light"}


def test_context_is_visible_inside_computations_created_under_the_provider():
    Theme = Context("light")
    seen = []
    with Owner():
        provide(Theme, "dark")
        Effect(lambda: seen.append(use(Theme)))
    assert seen == ["dark"]


def test_provide_outside_an_owner_is_an_error():
    with pytest.raises(RuntimeError):
        provide(Context(), 1)


# C15 -----------------------------------------------------------------------------------------
def test_selector_notifies_only_the_two_rows_that_changed():
    selected = Signal(1)
    is_selected = selector(selected)
    runs = {k: 0 for k in range(4)}

    def watch(k):
        def compute():
            runs[k] += 1
            return is_selected(k)

        return compute

    for k in range(4):
        Effect(watch(k))
    assert all(runs[k] == 1 for k in runs)
    selected.set(3)
    assert runs == {0: 1, 1: 2, 2: 1, 3: 2}
    assert is_selected(3) is True and is_selected(1) is False


# owners and helpers ---------------------------------------------------------------------------
def test_run_with_owner_and_get_owner():
    root = Owner(parent=None)
    assert get_owner() is None
    assert run_with_owner(root, get_owner) is root
    assert get_owner() is None


def test_on_mount_runs_once_and_tracks_nothing():
    s = Signal(0)
    log = []
    on_mount(lambda: log.append(s()))
    s.set(1)
    assert log == [0]


def test_exceptions_in_a_compute_propagate_and_leave_the_system_usable():
    s = Signal(0)

    def bad():
        if s() == 1:
            raise ValueError("boom")
        return s()

    Effect(bad)
    with pytest.raises(ValueError):
        s.set(1)
    # the system is not stuck: a later write still runs effects
    log = []
    Effect(lambda: log.append(s()))
    s.set(2)
    assert log[-1] == 2
