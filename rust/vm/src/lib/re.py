"""`re` over the browser's `RegExp`: a backtracking engine for zero bytes (RUNTIME.md §3.6).

A pattern is translated once at compile time — Python's spellings to JavaScript's — and every
match runs `exec` with the `d` flag, so group spans come back as indices. Indices are UTF-16
code units in JavaScript and code points in Python; an ASCII string needs no conversion and a
non-ASCII one is walked once per match.

Known differences, all documented ones: `\\d` and `\\w` are ASCII (Python's are Unicode for
`str` patterns); lookbehind needs Safari 16.4; conditional groups `(?(1)…)`, possessive
quantifiers and atomic groups are not supported; inline flags are honoured only at the start
of a pattern. Only in the browser: importing this module without `js` raises.
"""

try:
    import js as _js
except ImportError:
    raise ImportError("re runs on the browser's RegExp; there is no js module here")

_RegExp = _js.RegExp

NOFLAG = 0
I = IGNORECASE = 2
L = LOCALE = 4
M = MULTILINE = 8
S = DOTALL = 16
U = UNICODE = 32
X = VERBOSE = 64
A = ASCII = 256
DEBUG = 128


class PatternError(Exception):
    def __init__(self, msg, pattern=None, pos=None):
        super().__init__(msg)
        self.msg = msg
        self.pattern = pattern
        self.pos = pos


error = PatternError

# What `u` mode lets an escape precede: the syntax characters; `-` inside a class too.
_SYNTAX = "^$\\.*+?()[]{}|/"


# -- translation -------------------------------------------------------------------------------

_INLINE = {"i": IGNORECASE, "m": MULTILINE, "s": DOTALL, "x": VERBOSE, "a": ASCII, "u": UNICODE, "L": LOCALE}


def _translate(pattern, flags):
    """Python pattern → (JavaScript source, flags, group count, {name: index})."""
    # Leading inline flags: (?imsx)
    while pattern.startswith("(?") and len(pattern) > 2 and pattern[2] in _INLINE:
        j = 2
        while j < len(pattern) and pattern[j] in _INLINE:
            flags |= _INLINE[pattern[j]]
            j += 1
        if j < len(pattern) and pattern[j] == ")":
            pattern = pattern[j + 1 :]
        else:
            break
    verbose = bool(flags & VERBOSE)
    multiline = bool(flags & MULTILINE)
    out = []
    groups = 0
    names = {}
    i = 0
    n = len(pattern)
    in_class = False
    while i < n:
        c = pattern[i]
        if c == "\\":
            if i + 1 >= n:
                raise error("bad escape (end of pattern)", pattern, i)
            d = pattern[i + 1]
            if not in_class and d == "A":
                out.append("(?<![\\s\\S])" if multiline else "^")
            elif not in_class and d == "Z":
                out.append("(?![\\s\\S])" if multiline else "$")
            elif d == "a":
                out.append("\\x07")
            elif d == "N":
                raise error("\\N{name} escapes are not supported by the browser's RegExp", pattern, i)
            elif d.isalnum() or d in _SYNTAX or (in_class and d == "-"):
                out.append(c + d)
            else:
                # `\#`, `\ `, `\-` outside a class: a literal in Python, an error in `u` mode.
                out.append(d)
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
            out.append(c)
            i += 1
            continue
        if c == "[":
            in_class = True
            out.append(c)
            i += 1
            # a leading ] or ^] is literal in both
            if i < n and pattern[i] == "^":
                out.append("^")
                i += 1
            if i < n and pattern[i] == "]":
                out.append("\\]")
                i += 1
            continue
        if verbose and c in " \t\n\r\f\v":
            i += 1
            continue
        if verbose and c == "#":
            while i < n and pattern[i] != "\n":
                i += 1
            continue
        if c == "(":
            if pattern.startswith("(?P<", i):
                j = pattern.index(">", i)
                name = pattern[i + 4 : j]
                groups += 1
                names[name] = groups
                out.append("(?<" + name + ">")
                i = j + 1
                continue
            if pattern.startswith("(?P=", i):
                j = pattern.index(")", i)
                out.append("\\k<" + pattern[i + 4 : j] + ">")
                i = j + 1
                continue
            if pattern.startswith("(?#", i):
                j = pattern.index(")", i)
                i = j + 1
                continue
            if pattern.startswith("(?(", i):
                raise error("conditional groups are not supported by the browser's RegExp", pattern, i)
            if pattern.startswith("(?", i):
                if pattern.startswith("(?<", i) and not (pattern.startswith("(?<=", i) or pattern.startswith("(?<!", i)):
                    j = pattern.index(">", i)
                    groups += 1
                    names[pattern[i + 3 : j]] = groups
                out.append(c)
                i += 1
                continue
            groups += 1
            out.append(c)
            i += 1
            continue
        if c == "$" and not multiline:
            out.append("(?=\\n?$)")
            i += 1
            continue
        if c == "{":
            # A quantifier only when it reads as one; a lone brace is a literal in Python.
            j = i + 1
            while j < n and pattern[j].isdigit():
                j += 1
            k = j
            if k < n and pattern[k] == ",":
                k += 1
                while k < n and pattern[k].isdigit():
                    k += 1
            if k < n and pattern[k] == "}" and k > i + 1 and (j > i + 1 or k > j + 1):
                out.append("{0," + pattern[j + 1 : k] + "}" if j == i + 1 else pattern[i : k + 1])
                i = k + 1
            else:
                out.append("\\{")
                i += 1
            continue
        if c == "}" or c == "]":
            out.append("\\" + c)
            i += 1
            continue
        out.append(c)
        i += 1
    js_flags = "gdu"
    if flags & IGNORECASE:
        js_flags += "i"
    if multiline:
        js_flags += "m"
    if flags & DOTALL:
        js_flags += "s"
    return "".join(out), flags, groups, names, js_flags


def _u16(s, cp):
    """Code-point index → UTF-16 index."""
    k = 0
    for ch in s[:cp]:
        k += 2 if ord(ch) > 0xFFFF else 1
    return k


class _Spans:
    """UTF-16 → code-point index conversion for one string, computed once when needed."""

    __slots__ = ("string", "ascii", "table")

    def __init__(self, string):
        self.string = string
        self.ascii = string.isascii()
        self.table = None

    def cp(self, u16):
        if self.ascii:
            return u16
        if self.table is None:
            table = {}
            k = 0
            for i, ch in enumerate(self.string):
                table[k] = i
                k += 2 if ord(ch) > 0xFFFF else 1
            table[k] = len(self.string)
            self.table = table
        return self.table[u16]


# -- Pattern and Match -------------------------------------------------------------------------


class Pattern:
    def __init__(self, pattern, flags):
        source, flags, groups, names, js_flags = _translate(pattern, flags)
        try:
            self._re = _RegExp.new(source, js_flags)
        except Exception as e:
            raise error(str(e), pattern) from None
        self.pattern = pattern
        self.flags = flags | UNICODE
        self.groups = groups
        self.groupindex = names
        self._source = source
        self._js_flags = js_flags
        self._full = None

    def __repr__(self):
        return "re.compile(%r)" % (self.pattern,)

    def _exec(self, regex, string, spans, start_u16):
        regex.lastIndex = start_u16
        m = regex.exec(string)
        if m is None:
            return None
        return Match(self, string, spans, m, self.groups)

    def _search(self, string, spans, start_u16):
        return self._exec(self._re, string, spans, start_u16)

    def _bounds(self, string, pos, endpos):
        if endpos is not None and endpos < len(string):
            string = string[:endpos]
        if pos < 0:
            pos = 0
        return string, pos

    def search(self, string, pos=0, endpos=None):
        string, pos = self._bounds(string, pos, endpos)
        spans = _Spans(string)
        return self._search(string, spans, pos if spans.ascii else _u16(string, pos))

    def match(self, string, pos=0, endpos=None):
        string, pos = self._bounds(string, pos, endpos)
        spans = _Spans(string)
        start = pos if spans.ascii else _u16(string, pos)
        m = self._search(string, spans, start)
        if m is not None and m._u16start == start:
            return m
        # The leftmost match starts later; a sticky attempt at `pos` settles it.
        sticky = _RegExp.new(self._source, self._js_flags.replace("g", "y"))
        return self._exec(sticky, string, spans, start)

    def fullmatch(self, string, pos=0, endpos=None):
        string, pos = self._bounds(string, pos, endpos)
        if self._full is None:
            self._full = _RegExp.new("(?:" + self._source + ")(?![\\s\\S])", self._js_flags.replace("g", "y"))
        spans = _Spans(string)
        return self._exec(self._full, string, spans, pos if spans.ascii else _u16(string, pos))

    def finditer(self, string, pos=0, endpos=None):
        string, pos = self._bounds(string, pos, endpos)
        spans = _Spans(string)
        start = pos if spans.ascii else _u16(string, pos)
        return self._iter(string, spans, start)

    def _iter(self, string, spans, start):
        while True:
            m = self._search(string, spans, start)
            if m is None:
                return
            yield m
            end = m._u16end
            if end == m._u16start:
                # An empty match: search on from the next code point.
                cp = m._spans[0][1]
                if cp >= len(string):
                    return
                end = cp + 1 if spans.ascii else _u16(string, cp + 1)
            start = end

    def findall(self, string, pos=0, endpos=None):
        out = []
        for m in self.finditer(string, pos, endpos):
            if self.groups == 0:
                out.append(m.group(0))
            elif self.groups == 1:
                out.append(m.group(1) or "")
            else:
                out.append(tuple(g or "" for g in m.groups()))
        return out

    def split(self, string, maxsplit=0):
        out = []
        last = 0
        n = 0
        for m in self.finditer(string):
            if maxsplit and n >= maxsplit:
                break
            out.append(string[last : m.start()])
            out.extend(m.groups())
            last = m.end()
            n += 1
        out.append(string[last:])
        return out

    def sub(self, repl, string, count=0):
        return self.subn(repl, string, count)[0]

    def subn(self, repl, string, count=0):
        if not callable(repl):
            template = _parse_template(repl, self)
            repl_fn = None
        else:
            template = None
            repl_fn = repl
        out = []
        last = 0
        n = 0
        for m in self.finditer(string):
            if count and n >= count:
                break
            out.append(string[last : m.start()])
            out.append(repl_fn(m) if repl_fn is not None else _expand(template, m))
            last = m.end()
            n += 1
        out.append(string[last:])
        return "".join(out), n

    def scanner(self, string, pos=0, endpos=None):
        raise NotImplementedError("Pattern.scanner")


class Match:
    def __init__(self, pattern, string, spans, m, ngroups):
        self.re = pattern
        self.string = string
        self.pos = 0
        self.endpos = len(string)
        indices = m.indices
        values = []
        span = []
        for i in range(ngroups + 1):
            v = m[i]
            if v is None:
                values.append(None)
                span.append((-1, -1))
            else:
                values.append(v)
                pair = indices[i]
                a, b = pair[0], pair[1]
                if i == 0:
                    self._u16start, self._u16end = a, b
                span.append((spans.cp(a), spans.cp(b)))
        self._values = values
        self._spans = span
        self.lastindex = None
        for i in range(ngroups, 0, -1):
            if values[i] is not None:
                self.lastindex = i
                break
        self.lastgroup = None
        if self.lastindex is not None:
            for name, idx in pattern.groupindex.items():
                if idx == self.lastindex:
                    self.lastgroup = name

    def _index(self, g):
        if isinstance(g, str):
            try:
                return self.re.groupindex[g]
            except KeyError:
                raise IndexError("no such group") from None
        if not isinstance(g, int) or g < 0 or g > self.re.groups:
            raise IndexError("no such group")
        return g

    def group(self, *groups):
        if not groups:
            return self._values[0]
        if len(groups) == 1:
            return self._values[self._index(groups[0])]
        return tuple(self._values[self._index(g)] for g in groups)

    def __getitem__(self, g):
        return self._values[self._index(g)]

    def groups(self, default=None):
        return tuple(default if v is None else v for v in self._values[1:])

    def groupdict(self, default=None):
        out = {}
        for name, idx in self.re.groupindex.items():
            v = self._values[idx]
            out[name] = default if v is None else v
        return out

    def start(self, g=0):
        return self._spans[self._index(g)][0]

    def end(self, g=0):
        return self._spans[self._index(g)][1]

    def span(self, g=0):
        return self._spans[self._index(g)]

    def expand(self, template):
        return _expand(_parse_template(template, self.re), self)

    def __bool__(self):
        return True

    def __repr__(self):
        return "<re.Match object; span=%r, match=%r>" % (self._spans[0], self._values[0])


# -- templates ---------------------------------------------------------------------------------

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "a": "\a", "f": "\f", "v": "\v", "b": "\b"}


def _parse_template(template, pattern):
    """`\\1`, `\\g<1>`, `\\g<name>` and the escapes → a list of str | int (group index)."""
    parts = []
    lit = []
    i = 0
    n = len(template)
    while i < n:
        c = template[i]
        if c != "\\":
            lit.append(c)
            i += 1
            continue
        if i + 1 >= n:
            raise error("bad escape (end of pattern)", template, i)
        d = template[i + 1]
        if d == "g":
            if i + 2 >= n or template[i + 2] != "<":
                raise error("missing <", template, i)
            j = template.index(">", i)
            ref = template[i + 3 : j]
            if ref.isdigit():
                idx = int(ref)
            else:
                try:
                    idx = pattern.groupindex[ref]
                except KeyError:
                    raise error("unknown group name %r" % (ref,), template, i) from None
            if idx > pattern.groups:
                raise error("invalid group reference %d" % idx, template, i)
            if lit:
                parts.append("".join(lit))
                lit = []
            parts.append(idx)
            i = j + 1
        elif d.isdigit():
            j = i + 1
            while j < n and j < i + 3 and template[j].isdigit():
                j += 1
            idx = int(template[i + 1 : j])
            if idx > pattern.groups:
                raise error("invalid group reference %d" % idx, template, i)
            if lit:
                parts.append("".join(lit))
                lit = []
            parts.append(idx)
            i = j
        elif d in _ESCAPES:
            lit.append(_ESCAPES[d])
            i += 2
        elif d.isalpha():
            raise error("bad escape \\%s" % d, template, i)
        else:
            lit.append(d)
            i += 2
    if lit:
        parts.append("".join(lit))
    return parts


def _expand(parts, m):
    out = []
    for p in parts:
        if isinstance(p, int):
            v = m._values[p]
            out.append("" if v is None else v)
        else:
            out.append(p)
    return "".join(out)


# -- module functions ------------------------------------------------------------------------------

_cache = {}
_SPECIAL = "()[]{}?*+-|^$\\.&~# \t\n\r\v\f"


def compile(pattern, flags=0):
    if isinstance(pattern, Pattern):
        if flags:
            raise ValueError("cannot process flags argument with a compiled pattern")
        return pattern
    if not isinstance(pattern, str):
        raise TypeError("first argument must be string or compiled pattern")
    key = (pattern, flags)
    p = _cache.get(key)
    if p is None:
        p = Pattern(pattern, flags)
        if len(_cache) >= 256:
            _cache.clear()
        _cache[key] = p
    return p


def purge():
    _cache.clear()


def search(pattern, string, flags=0):
    return compile(pattern, flags).search(string)


def match(pattern, string, flags=0):
    return compile(pattern, flags).match(string)


def fullmatch(pattern, string, flags=0):
    return compile(pattern, flags).fullmatch(string)


def findall(pattern, string, flags=0):
    return compile(pattern, flags).findall(string)


def finditer(pattern, string, flags=0):
    return compile(pattern, flags).finditer(string)


def split(pattern, string, maxsplit=0, flags=0):
    return compile(pattern, flags).split(string, maxsplit)


def sub(pattern, repl, string, count=0, flags=0):
    return compile(pattern, flags).sub(repl, string, count)


def subn(pattern, repl, string, count=0, flags=0):
    return compile(pattern, flags).subn(repl, string, count)


def escape(pattern):
    out = []
    for c in pattern:
        if c in _SPECIAL:
            out.append("\\")
        out.append(c)
    return "".join(out)
