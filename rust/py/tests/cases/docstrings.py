"""Docstrings, and the dedent CPython 3.13 does at compile time.

The indentation belongs to the source, not to the text, so `__doc__` comes back without it —
and the *relative* indentation inside the text has to survive, which is what makes this more
than a strip.
"""


def one_line():
    """Just this."""


def multi():
    """First.

    Second, at four.
        Third, at eight.
    """


def tabs():
    """First.
	Tab-indented.
	Also tab.
	"""


def ragged():
    """First.
  Two spaces.
      Six spaces.
    """


def blank_lines_do_not_count():
    """First.

    Four.
    """


def only_the_first_line_is_left_alone():
    """   leading spaces on the first line survive
    but not on this one
    """


def not_a_docstring():
    x = "a string, but not the first statement"
    return x


def literal_returned():
    return "not a docstring either"


def empty():
    """"""


def nothing():
    pass


class Klass:
    """A class body has one too."""

    def method(self):
        """And a method.

        With a second paragraph.
        """

    def bare(self):
        pass


async def coro():
    """An async def is a def."""


for f in (one_line, multi, tabs, ragged, blank_lines_do_not_count,
          only_the_first_line_is_left_alone, not_a_docstring, literal_returned,
          empty, nothing, Klass.method, Klass.bare, coro):
    print(f.__name__, repr(f.__doc__))

print(repr(__doc__))

# A lambda has no body to hold one, and a docstring is not an attribute you can set here.
print(repr((lambda: "x").__doc__))


# The awkward shapes, asserted against CPython's own compile-time dedent rather than
# against a reading of it.
def probe(doc):
    ns = {}
    exec('def f():\n    """' + doc + '"""\n', ns)
    return ns["f"].__doc__


# ⚠ The tab cases are the point: indentation is measured in COLUMNS with tab stops of
# eight, so `"\tb"` under an indent of two comes back as six spaces and a `b`. Counting
# characters instead agrees with CPython on everything above and fails here.
for doc in ["  a\n    b\n    ", "\n    a\n      b\n    ", "   ", "  a", "a\n\n\n  b",
            "  \n  a", "\ta\n\tb", "", "a", "\n", "  \n\t\n  x",
            "a\n\tb\n  x", "a\n \tb\n  x", "a\n\t\tb\n    x",
            "a\n        b\n\tc", "a\n\tb\n        c", "a\n\t\n  x"]:
    print(repr(doc), "->", repr(probe(doc)))
