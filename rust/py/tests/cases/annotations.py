"""`__annotations__`: which parameters carry one, and in what order.

⚠ **The keys are what this case asserts, not the values.** CPython evaluates an annotation to
an object; this runtime stores its **source text** and never evaluates it, which is why
`def g(x: Undefined)` has always been legal here. That difference is deliberate and is
documented in `rust/README.md`; the keys and their order are the same on both, and that is
what a reader of `__annotations__` navigates by.
"""


def none(a, b):
    pass


def some(a: int, b: "Trip", *rest: str, kw: bool = False, **extra: dict) -> "Response":
    pass


class C:
    def m(self, x: float) -> None:
        pass


def spaced(x:   int  ) ->   str:
    pass


print("unannotated:", none.__annotations__)
print("every kind, in declaration order:", list(some.__annotations__))
print("a method:", list(C.m.__annotations__))
print("only the annotated ones:", list(spaced.__annotations__))
print("a default does not make an annotation:", list(none.__annotations__))
