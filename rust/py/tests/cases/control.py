for i in range(3):
    if i == 1:
        continue
    print("i", i)
else:
    print("for-else")
for i in range(3):
    if i == 1:
        break
else:
    print("not printed")
n = 0
while n < 5:
    n += 1
    if n == 2: continue
    if n == 4: break
    print("n", n)
else:
    print("not printed")
while False:
    pass
else:
    print("while-else")
x = 5
if x > 10:
    print("big")
elif x > 3:
    print("medium")
else:
    print("small")
print("a" if x else "b", [i for i in range(10) if i % 3 == 0 if i > 0])
for a, (b, c) in [(1, (2, 3)), (4, (5, 6))]:
    print(a, b, c)
for i, ch in enumerate("ab"):
    print(i, ch)
for k, v in {"x": 1}.items():
    print(k, v)
total = 0
for i in range(1, 101):
    total += i
print(total)
matrix = [[1, 2], [3, 4]]
print([[row[i] for row in matrix] for i in range(2)], sum(sum(r) for r in matrix))
i = 0
while True:
    i += 1
    if i > 3:
        break
print(i)
def find(items, target):
    for idx, it in enumerate(items):
        if it == target:
            return idx
    return -1
print(find([5, 6, 7], 7), find([], 1))
def early(x):
    if x < 0:
        return "neg"
    if x == 0:
        return "zero"
    return "pos"
print(early(-1), early(0), early(1))
print(1 if 0 else 2 if 0 else 3, (1, 2) if True else None, [1] * 3, "ab" * 2)
pass
del x
try:
    print(x)
except NameError as e:
    print("NameError", e)
a = b = c = 7
print(a, b, c)
a, b = b + 1, a - 1
print(a, b)
lst = [1, 2, 3]
lst[0], lst[2] = lst[2], lst[0]
print(lst)
d = {}
d["a"] = d["b"] = 1
print(d)
obj = type("O", (), {})()
obj.x = obj.y = 3
print(obj.x, obj.y)
print(*[1, 2, 3], sep="-", end="!\n")
print("no newline", end="")
print()
print("a", "b", sep="")
print(1, 2, 3, sep=", ", end=".\n")
import sys
print("to stderr", file=sys.stderr)
print(f"{sys.platform=}" if False else "platform", sys.version_info[0] >= 3, type(sys.modules).__name__)
result = []
for i in range(3):
    for j in range(3):
        if j == 2:
            break
        result.append((i, j))
print(result)
def loops():
    out = []
    for i in range(3):
        try:
            for j in range(3):
                if j == 1:
                    break
                out.append((i, j))
        finally:
            out.append("f")
    return out
print(loops())
print(list(range(3)) == [0, 1, 2], type(range(3)) is range, isinstance(range(3), range))
def match_free(v):
    if isinstance(v, int) and v > 0: return "pos int"
    if isinstance(v, str): return "str"
    return "other"
print(match_free(1), match_free("s"), match_free(-1))
