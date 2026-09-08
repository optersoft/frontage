# class keywords and metaclasses, __init_subclass__ with keywords, __slots__, and a generator's
# finally on collection.
class Meta(type):
    def __new__(mcls, name, bases, ns, **kw):
        ns["tag"] = kw.get("tag", "none")
        cls = super().__new__(mcls, name, bases, ns)
        return cls

    def __init__(cls, name, bases, ns, **kw):
        super().__init__(name, bases, ns)
        cls.registered = name


class Base(metaclass=Meta, tag="base"):
    pass


class Child(Base, tag="child"):
    pass


print(Base.tag, Child.tag, Base.registered, Child.registered, type(Base).__name__)


class Plugin:
    plugins = []

    def __init_subclass__(cls, name=None, **kw):
        super().__init_subclass__(**kw)
        Plugin.plugins.append((cls.__name__, name))


class A(Plugin, name="a"):
    pass


class B(Plugin):
    pass


print(Plugin.plugins)


class Slotted:
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x = x
        self.y = y


s = Slotted(1, 2)
print(s.x + s.y, Slotted.__slots__)


def gen():
    try:
        yield 1
        yield 2
    finally:
        print("generator closed")


g = gen()
print(next(g))
del g
import gc
gc.collect()
print("after")
