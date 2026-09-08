# runtime: web
# `re` runs over the browser's RegExp, so this case runs on the wasm under node, not on fpy.
import re

print(re.search(r"\d+", "abc 123 def").group())
print(re.match(r"\d+", "abc 123") is None)
print(re.match(r"[a-z]+", "abc 123").span())
print(re.fullmatch(r"[a-z]+", "abc") is not None, re.fullmatch(r"[a-z]+", "abc1") is None)
print(re.findall(r"\w+", "the quick  brown fox"))
print(re.findall(r"(\w)(\d)", "a1 b2 c3"))
print(re.findall(r"(\w)\d", "a1 b2 c3"))
print(re.split(r"\s*,\s*", "a , b,c ,d"))
print(re.split(r"(\s*),", "a ,b", maxsplit=1))
print(re.split("x*", "axbc"))
print(re.sub(r"(\w+) (\w+)", r"\2 \1", "hello world"))
print(re.sub("x*", "-", "abxd"))
print(re.sub(r"\d", lambda m: str(int(m.group()) * 2), "a1b2c3"))
print(re.subn(r"a", "A", "banana", count=2))
print(re.findall("a*", "baaa"))

m = re.match(r"(?P<year>\d{4})-(?P<month>\d{2})(?:-(?P<day>\d{2}))?", "2026-09")
print(m.group("year"), m["month"], m.group("day"), m.groups(), m.groupdict("?"))
print(m.start("month"), m.end("month"), m.span(0), m.lastindex, m.lastgroup)
print(m.expand(r"\g<month>/\g<year>"))
print(repr(m))
print(m.re.groupindex, m.re.groups, m.re.pattern)

p = re.compile(r"""
    (\d+)   # the number
    \s*
    ([a-z]+)  # the unit
""", re.X | re.I)
print(p.findall("3 KG, 12mm and 7  s"))
print(re.search(r"^b", "a\nb", re.M).span(), re.search(r"^b", "a\nb") is None)
print(re.search(r"a.b", "a\nb") is None, re.search(r"a.b", "a\nb", re.S) is not None)
print(re.search(r"abc$", "abc\n") is not None, re.search(r"abc\Z", "abc\n") is None)
print(re.search(r"\Aabc", "abc").span())
print(re.match(r"(?i)hello", "HeLLo World").group())
print(re.search(r"(?P<w>\w+) (?P=w)", "the the cat").group())
print([m.span() for m in re.finditer(r"é+", "café é ééé")])
print(re.sub(r"é", "e", "café été"))
print(re.findall(r".", "a😀b"), re.search(r"b", "a😀b").span())
print(re.escape("a.b*c?d[e]{2} f#g"))
print(re.compile("a") is re.compile("a"))
print(re.search(r"a{,2}", "aaaa").group(), re.search(r"a{", "a{b").group(), re.search(r"x{2}", "xxx").span(), re.search(r"a}b]", "a}b]").group())
print(re.escape("a.b*c?d[e]{2} f#g-h"), re.search(re.escape("a-b# c"), "xa-b# cy").span(), re.findall(r"[\-\w]+", "a-b c"))
print(re.match(r"x", "yx") is None, re.match(r"x", "yx", 1) is not None if False else re.compile("x").match("yx", 1).span())
print(re.compile(r"\d").search("ab12", 3).span())
try:
    re.compile("(")
except re.error as e:
    print("error", type(e).__name__)
try:
    re.sub(r"(a)", r"\2", "a")
except re.error as e:
    print("error", e.msg)
