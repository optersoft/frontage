name = "World"
n = 42
t = t"Hello {name}!"
print(type(t).__name__, t.strings, len(t.interpolations), t.interpolations[0].value, t.interpolations[0].expression, t.interpolations[0].conversion, t.interpolations[0].format_spec)
t2 = t"{n:>5} and {name!r} and {n + 1 = }"
for i in t2.interpolations:
    print(repr(i.value), repr(i.expression), repr(i.conversion), repr(i.format_spec))
print(t2.strings)
def render(tpl):
    out = []
    for s, i in zip(tpl.strings, list(tpl.interpolations) + [None]):
        out.append(s)
        if i is not None:
            v = i.value
            if i.conversion == "r":
                v = repr(v)
            elif i.conversion == "s":
                v = str(v)
            out.append(format(v, i.format_spec))
    return "".join(out)
print(render(t), render(t2))
empty = t""
print(empty.strings, empty.interpolations)
adj = t"{1}{2}"
print(adj.strings, [i.value for i in adj.interpolations])
multi = t"a{n}b"
print(multi.strings)
nested = t"outer {t'inner {n}'.strings}"
print(nested.interpolations[0].value)
from string.templatelib import Template, Interpolation
print(isinstance(t, Template), isinstance(t.interpolations[0], Interpolation), Template.__name__, Interpolation.__name__)
print(t"{n:{n}}".interpolations[0].format_spec, t"x{'y'}z".strings)
items = [t"{i}" for i in range(3)]
print([x.interpolations[0].value for x in items])
def uses_lambda():
    return t"{(lambda: 7)()}"
print(uses_lambda().interpolations[0].value)
print(t"{name.upper()} {len(name)}".strings, [i.value for i in t"{name.upper()} {len(name)}".interpolations])
print(t2 == t2, t == t"Hello {name}!")
