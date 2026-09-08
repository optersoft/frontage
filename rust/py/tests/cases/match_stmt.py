# match statements: literals, captures, sequences with a star, mappings with a rest, classes
# by __match_args__ and by keyword, guards, or-patterns, nesting.
class Point:
    __match_args__ = ("x", "y")

    def __init__(self, x, y):
        self.x = x
        self.y = y


def describe(v):
    match v:
        case 0 | 1 | 2:
            return "small"
        case int(n) if n < 0:
            return "negative %d" % n
        case int():
            return "int"
        case str() as s:
            return "str " + s
        case [x, y]:
            return "pair %r %r" % (x, y)
        case [first, *rest]:
            return "first %r rest %r" % (first, rest)
        case {"kind": "circle", "r": r}:
            return "circle %r" % r
        case {"kind": k, **others}:
            return "kind %r others %r" % (k, sorted(others))
        case Point(x=0, y=0):
            return "origin"
        case Point(0, y):
            return "on y at %r" % y
        case Point(x, y):
            return "point %r %r" % (x, y)
        case None:
            return "none"
        case True:
            return "true"
        case _:
            return "other"


for value in (1, -5, 7, "hi", [1, 2], [1, 2, 3], (9,), {"kind": "circle", "r": 2}, {"kind": "square", "w": 1, "h": 2}, Point(0, 0), Point(0, 3), Point(4, 5), None, True, 2.5, [], "x"):
    print(repr(value)[:24], "->", describe(value))


def nested(v):
    match v:
        case [Point(x, y), *tail] if x == y:
            return ("diag", x, tail)
        case [[a, b], [c, d]]:
            return ("grid", a, b, c, d)
        case {"items": [first, *_]}:
            return ("items", first)
        case (1 | 2) as small, second:
            return ("small-pair", small, second)
    return "nothing"


print(nested([Point(2, 2), 3, 4]))
print(nested([[1, 2], [3, 4]]))
print(nested({"items": [10, 20, 30]}))
print(nested((2, "b")))
print(nested((3, "b")))
print(nested("ab"))  # a str never matches a sequence pattern


match {"a": 1}:
    case {"a": 1, "b": 2}:
        print("both")
    case {"a": 1}:
        print("just a")

match range(3):
    case [0, 1, 2]:
        print("range matched")
