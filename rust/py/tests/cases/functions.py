def f(a, b=2, *args, c=3, d, **kwargs):
    return (a, b, args, c, d, sorted(kwargs.items()))
print(f(1, d=4), f(1, 2, 3, 4, d=5, c=6, e=7), f(*[1, 2, 3], **{"d": 9, "z": 0}))
def g(x, /, y, *, z): return x + y + z
print(g(1, 2, z=3), g(1, y=2, z=3))
def h(*a, **k): return a, sorted(k)
print(h(), h(1), h(1, x=2), h(*(1, 2), **dict(y=3)), h(*[], **{}))
def defaults(a, b=[]):
    b.append(a); return b
print(defaults(1), defaults(2), defaults(3, []))
lam = lambda x, y=1: x * y
print(lam(3), lam(3, 2), (lambda: 42)(), (lambda *a: a)(1, 2), (lambda **k: k)(z=1))
def outer():
    x = 1
    def middle():
        def inner():
            nonlocal x
            x += 10
            return x
        return inner
    return middle()
inner = outer(); print(inner(), inner())
def make_adders():
    return [lambda v, i=i: v + i for i in range(3)]
print([f(10) for f in make_adders()])
def late():
    return [lambda: i for i in range(3)]
print([f() for f in late()])
counter = 0
def bump():
    global counter
    counter += 1
    return counter
bump(); bump(); print(counter)
def rec(n): return 1 if n <= 1 else n * rec(n - 1)
print(rec(10), rec(20))
def fib(n): return n if n < 2 else fib(n - 1) + fib(n - 2)
print(fib(20))
def deco(fn):
    def wrapper(*a, **k):
        return ("wrapped", fn(*a, **k))
    wrapper.__name__ = fn.__name__
    return wrapper
@deco
def hello(name): return f"hi {name}"
print(hello("x"), hello.__name__)
def deco_args(tag):
    def deco(fn):
        def w(*a): return (tag, fn(*a))
        return w
    return deco
@deco_args("t")
@deco
def two(x): return x * 2
print(two(4))
print(f.__name__, (lambda: 0).__name__, f.__qualname__, outer.__qualname__, hello.__name__)
def doc():
    """A docstring."""
    return 1
print(doc(), doc.__doc__ if False else "doc")
def kw_only(*, a, b=2): return a, b
print(kw_only(a=1), kw_only(b=3, a=1))
def many(a, b, c, d, e, f, g, h): return a + b + c + d + e + f + g + h
print(many(1, 2, 3, 4, 5, 6, 7, 8), many(*range(8)))
def gen_default(x=None):
    return [] if x is None else x
print(gen_default(), gen_default([1]))
def apply(fn, *args): return fn(*args)
print(apply(max, 1, 5, 3), apply(len, "abc"), apply(lambda: "none"))
def varargs_forward(*args, **kwargs): return h(*args, **kwargs)
print(varargs_forward(1, 2, k=3))
x = 10
def shadow():
    x = 20
    return x
print(shadow(), x)
def uses_global_before_assign():
    return x + 1
print(uses_global_before_assign())
try:
    def bad():
        print(y)
        y = 1
    bad()
except UnboundLocalError as e:
    print("UnboundLocalError")
print(callable(f), type(f).__name__, type(lambda: 0).__name__, f.__defaults__, kw_only.__defaults__)
def walrus_test(data):
    if (n := len(data)) > 2:
        return n
    return -n
print(walrus_test([1, 2, 3]), walrus_test([1]), [y for x in [1, 2] if (y := x * 2) > 2])
