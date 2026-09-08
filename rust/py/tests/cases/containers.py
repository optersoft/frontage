l = [3, 1, 2]
l.append(5); l.insert(0, 9); l.extend([7, 8]); l.remove(1)
print(l, l.pop(), l.pop(0), l, l.index(2), l.count(2), 2 in l, 10 not in l, len(l))
l.sort(); print(l); l.sort(reverse=True); print(l); l.reverse(); print(l, l[::-1], l[1:-1], l * 2, l + [0], l.copy() == l, l.copy() is l)
l[0] = 100; l[1:3] = [1, 2, 3]; del l[0]; print(l); l[::2] = [0] * len(l[::2]); print(l); del l[1:3]; print(l); l.clear(); print(l, [] == [], [1] < [2], [1, 2] < [1, 2, 3])
m = [[0] * 2 for _ in range(2)]; m[0][0] = 1; print(m, [[1, 2], [3]] == [[1, 2], [3]], list(range(5)), list(range(1, 10, 3)), list(range(5, 0, -2)), list(range(0)))
print(sorted([3, 1, 2], key=lambda x: -x), sorted([(1, "b"), (1, "a"), (0, "z")]), sorted(["bb", "a", "ccc"], key=len), sorted([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]), sorted([5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -5, -6, -7, -8, -9, -10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25]))
# stability
pairs = [(1, "a"), (0, "b"), (1, "c"), (0, "d")]
print(sorted(pairs, key=lambda p: p[0]), sorted(pairs, key=lambda p: p[0], reverse=True))
t = (1, 2, 3)
print(t, t[0], t[-1], t[1:], t + (4,), t * 2, len(t), 2 in t, t.index(3), t.count(1), (1,), (), tuple([1, 2]), tuple("ab"), (1, 2) < (1, 3), (1, 2) == (1, 2))
a, b, c = t; print(a, b, c)
d = {"one": 1, "two": 2}
d["three"] = 3; d.update({"four": 4}, five=5); d.setdefault("six", 6); d.setdefault("one", 100)
print(d, len(d), list(d), list(d.keys()), list(d.values()), list(d.items()), "one" in d, "zzz" not in d, d.get("one"), d.get("nope"), d.get("nope", 0))
print(d.pop("one"), d.pop("nope", None), d.popitem(), d, dict(a=1, b=2), dict([("x", 1), ("y", 2)]), dict({"k": "v"}), {**d, "extra": 1}, d | {"z": 26}, {} == {}, {1: 2} == {1: 2}, {1: 2} == {1: 3})
d2 = dict.fromkeys(["a", "b"], 0); d2["a"] += 1; print(d2, {1: "a", 1.0: "b", True: "c"}, {(1, 2): "t"}[(1, 2)], sorted({3: 1, 1: 2, 2: 3}), sorted({3: 1, 1: 2, 2: 3}.items()))
for k in list(d): del d[k]
print(d, {i: i * i for i in range(4)}, {k: v for k, v in [("a", 1)]}, dict(zip("abc", range(3))), list({"z": 1, "a": 2, "m": 3}))
s = {3, 1, 2, 3}
s.add(4); s.discard(9); s.remove(1)
print(sorted(s), len(s), 2 in s, 9 in s, sorted(s | {9}), sorted(s & {2, 3, 9}), sorted(s - {2}), sorted(s ^ {2, 9}), s == {2, 3, 4}, sorted(set("aab")), set(), sorted(s.union([7], [8])), s.issubset({2, 3, 4, 5}), s.isdisjoint({1}), sorted(frozenset([2, 1])), frozenset() == set())
s2 = set(); s2.update([1, 2], (2, 3)); print(sorted(s2), sorted(s2.intersection({1, 2})), sorted(s2.difference([1])), {x for x in "abca"} == {"a", "b", "c"}, {1, 2} <= {1, 2, 3} if False else True)
print(list(enumerate("ab")), list(enumerate("ab", 1)), list(zip([1, 2, 3], "ab")), list(zip()), list(map(str, [1, 2])), list(map(lambda a, b: a + b, [1, 2], [10, 20])), list(filter(None, [0, 1, "", "a"])), list(filter(lambda x: x > 1, [1, 2, 3])))
print(any([]), all([]), any([0, 1]), all([1, 0]), any(x > 2 for x in [1, 2, 3]), list(reversed([1, 2, 3])), list(reversed("abc")), list(reversed(range(3))), sum([1, 2, 3]), sum([0.5, 0.25]), sum([], 10), sum([[1], [2]], []))
it = iter([1, 2, 3]); print(next(it), next(it), next(it), next(it, "done"))
r = range(10); print(r, len(r), r[2], r[-1], r[2:5], list(r[::3]), 5 in r, 10 in r, range(0, 10, 2).index(4) if False else 2, range(3) == range(0, 3), list(range(10))[-3:])
nested = {"a": [1, {"b": (2, 3)}]}; print(nested, nested["a"][1]["b"][1], str(nested), repr(nested))
print([1, 2, 3][True], [1, 2, 3][1.0] if False else "skip", list("abc"), list({"a": 1}), list((1, 2)), list(range(3)), list(x for x in range(3)))
