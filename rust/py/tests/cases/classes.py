class Point:
    dims = 2
    def __init__(self, x, y=0):
        self.x = x
        self.y = y
    def __repr__(self):
        return f"Point({self.x}, {self.y})"
    def __str__(self):
        return f"({self.x}, {self.y})"
    def __eq__(self, other):
        return isinstance(other, Point) and (self.x, self.y) == (other.x, other.y)
    def __hash__(self):
        return hash((self.x, self.y))
    def __add__(self, other):
        return Point(self.x + other.x, self.y + other.y)
    def __mul__(self, k):
        return Point(self.x * k, self.y * k)
    def __rmul__(self, k):
        return self * k
    def __neg__(self):
        return Point(-self.x, -self.y)
    def __lt__(self, other):
        return (self.x, self.y) < (other.x, other.y)
    def __len__(self):
        return 2
    def __getitem__(self, i):
        return (self.x, self.y)[i]
    def __contains__(self, v):
        return v in (self.x, self.y)
    def __bool__(self):
        return bool(self.x or self.y)
    def __call__(self, k):
        return self * k
    def __iter__(self):
        return iter((self.x, self.y))
    @property
    def norm2(self):
        return self.x * self.x + self.y * self.y
    @staticmethod
    def origin():
        return Point(0, 0)
    @classmethod
    def unit(cls):
        return cls(1, 1)
    def move(self, dx, dy=0):
        self.x += dx; self.y += dy
        return self
p = Point(1, 2); q = Point(3, 4)
print(p, repr(p), str(p), [p], p + q, p * 3, 2 * p, -p, p == Point(1, 2), p != q, p < q, len(p), p[0], p[-1], 2 in p, bool(p), bool(Point(0, 0)), p(2), list(p), p.norm2, Point.origin(), Point.unit(), p.dims, Point.dims, p.move(1).x)
print(sorted([q, p]), {p: "v"}[Point(2, 2)], p in {p}, max(p, q), tuple(p), x + y if False else sum(p))
class Base:
    def __init__(self, name):
        self.name = name
    def greet(self):
        return "Base " + self.name
    def who(self):
        return self.greet()
class Child(Base):
    def __init__(self, name, extra):
        super().__init__(name)
        self.extra = extra
    def greet(self):
        return "Child " + super().greet() + " " + self.extra
class GrandChild(Child):
    pass
g = GrandChild("n", "e")
print(g.greet(), g.who(), g.name, isinstance(g, Base), isinstance(g, Child), issubclass(GrandChild, Base), type(g).__name__, GrandChild.__mro__ == (GrandChild, Child, Base, object), [c.__name__ for c in GrandChild.__mro__], GrandChild.__bases__[0].__name__)
class A:
    def m(self): return "A"
class B(A):
    def m(self): return "B" + super().m()
class C(A):
    def m(self): return "C" + super().m()
class D(B, C):
    def m(self): return "D" + super().m()
print(D().m(), [k.__name__ for k in D.__mro__])
class Counter:
    count = 0
    def __init__(self):
        Counter.count += 1
        self.id = Counter.count
Counter(); Counter(); print(Counter.count, Counter().id)
class Temp:
    def __init__(self): self._c = 0
    @property
    def c(self): return self._c
    @c.setter
    def c(self, v):
        if v < -273: raise ValueError("too cold")
        self._c = v
    @c.deleter
    def c(self): self._c = 0
t = Temp(); t.c = 25; print(t.c); del t.c; print(t.c)
try:
    t.c = -300
except ValueError as e:
    print("ValueError", e)
class Dyn:
    def __getattr__(self, name):
        if name.startswith("get_"):
            return lambda: name[4:]
        raise AttributeError(name)
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value * 2)
d = Dyn(); d.v = 5; print(d.v, d.get_thing(), hasattr(d, "get_x"), hasattr(d, "other"), getattr(d, "missing", "dflt"))
try:
    d.other
except AttributeError as e:
    print("AttributeError", e)
class Slots:
    __slots__ = ("a", "b")
    def __init__(self): self.a = 1; self.b = 2
s = Slots(); print(s.a + s.b)
class Meta:
    registry = []
    def __init_subclass__(cls, **kw):
        Meta.registry.append(cls.__name__)
class R1(Meta): pass
class R2(Meta): pass
print(Meta.registry)
class Ctx:
    def __enter__(self): print("enter"); return self
    def __exit__(self, t, v, tb): print("exit", t.__name__ if t else None); return t is ValueError
with Ctx() as c:
    print("body", c is not None)
with Ctx():
    raise ValueError("suppressed")
print("after")
try:
    with Ctx():
        raise KeyError("k")
except KeyError:
    print("KeyError escaped")
class Seq:
    def __init__(self, n): self.n = n
    def __getitem__(self, i):
        if i >= self.n: raise IndexError
        return i * i
print(list(Seq(4)), 4 in Seq(4), 5 in Seq(4))
class It:
    def __init__(self): self.i = 0
    def __iter__(self): return self
    def __next__(self):
        self.i += 1
        if self.i > 3: raise StopIteration
        return self.i
print(list(It()), sum(It()), [x for x in It()], max(It()))
print(Point.__name__, Point.__qualname__, Point.__module__, type(Point).__name__, Point.__dict__["dims"], "move" in Point.__dict__, p.__dict__ == {"x": 2, "y": 2}, p.__class__ is Point, object.__name__)
class WithClassAttr:
    items = []
    def add(self, x): self.items.append(x)
w1, w2 = WithClassAttr(), WithClassAttr(); w1.add(1); w2.add(2); print(w1.items, w2.items is w1.items)
print(getattr(p, "x"), setattr(p, "z", 9) or p.z, delattr(p, "z") or hasattr(p, "z"), vars(p) == p.__dict__, isinstance(p, object), type(p)(5, 6))
class Fmt:
    def __format__(self, spec): return f"<{spec}>"
print(f"{Fmt():abc}", format(Fmt(), "x"), "{:y}".format(Fmt()))
class Cmp:
    def __init__(self, v): self.v = v
    def __eq__(self, o): return self.v == o.v
print(Cmp(1) == Cmp(1), Cmp(1) != Cmp(2), Cmp(1) != Cmp(1), [Cmp(1)] == [Cmp(1)], Cmp(1) in [Cmp(1)])
