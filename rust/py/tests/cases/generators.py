def count(n):
    i = 0
    while i < n:
        yield i
        i += 1
print(list(count(3)), sum(count(100)), [x * x for x in count(4)])
def echo():
    received = []
    while True:
        v = yield len(received)
        if v is None:
            return received
        received.append(v)
e = echo(); print(next(e), e.send("a"), e.send("b"))
try:
    e.send(None)
except StopIteration as s:
    print("returned", s.value)
def delegating():
    r = yield from count(2)
    yield "after"
    return r
print(list(delegating()))
def inner():
    x = yield 1
    y = yield x * 2
    return x + y
def outer():
    res = yield from inner()
    yield res
o = outer(); print(next(o), o.send(5), o.send(7))
gen = (i * 2 for i in range(3)); print(type(gen).__name__, list(gen), list(gen))
print(sum(i for i in range(10) if i % 2), max(len(w) for w in ["a", "bbb", "cc"]), any(x > 2 for x in range(3)), tuple(x for x in "ab"))
def infinite():
    n = 0
    while True:
        yield n
        n += 1
it = infinite(); print([next(it) for _ in range(5)], next(it))
def nested_gen():
    for i in range(2):
        for j in range(2):
            yield (i, j)
print(list(nested_gen()), dict(nested_gen()) if False else sorted(nested_gen()))
def early_close():
    try:
        yield 1
        yield 2
    finally:
        print("cleanup")
g = early_close()
for v in g:
    print("got", v)
    break
g.close()
print("after loop")
g = early_close(); next(g); g.close()
print("deleted")
def throwing():
    try:
        yield 1
    except ValueError as e:
        yield f"caught {e}"
    yield "last"
t = throwing(); print(next(t), t.throw(ValueError("boom")), next(t))
def genexp_scope():
    x = 10
    return list(x + i for i in range(3))
print(genexp_scope())
data = {"a": 1, "b": 2}
print({k: v * 2 for k, v in data.items()}, sorted(k for k in data), [k for k in data if data[k] > 1])
print(list(zip(count(3), "abc")), list(enumerate(count(2))), list(map(lambda x: x + 1, count(3))), list(filter(lambda x: x % 2, count(5))))
def fib():
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b
f = fib(); print([next(f) for _ in range(10)])
def two_level():
    yield 1
    yield from [2, 3]
    yield from (x for x in [4])
    yield 5
print(list(two_level()))
gg = count(2); print(next(gg), next(gg))
try:
    next(gg)
except StopIteration:
    print("exhausted")
print(list(gg), next(gg, "default"))
print(list(x for x in range(3) for y in range(2)), [(x, y) for x in range(2) for y in range(2) if x != y], [[y for y in range(x)] for x in range(3)])
