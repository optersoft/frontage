import math
from math import sqrt, pi as PI
import json as j
print(math.floor(2.7), math.ceil(2.1), sqrt(2) ** 2 > 1.99, round(PI, 4), math.gcd(12, 18), math.factorial(5), math.isclose(0.1 + 0.2, 0.3), math.inf > 1e308, math.isnan(math.nan), math.log(math.e), round(math.log(8, 2)), math.trunc(-2.7), math.fabs(-2), math.hypot(3, 4), math.degrees(math.pi), math.radians(180) == math.pi, math.pow(2, 3), math.exp(0), round(math.sin(math.pi / 2), 3), round(math.cos(0), 3), round(math.atan2(1, 1), 4), math.fsum([0.1] * 10))
print(j.dumps([1, "a", None, True, 1.5, {"k": [1, 2]}]), j.dumps({"b": 1, "a": 2}, sort_keys=True), j.dumps({"a": 1}, indent=2), j.dumps("héllo"), j.dumps("héllo", ensure_ascii=False), j.dumps({"a": 1, "b": [1, 2]}, separators=(",", ":")))
print(j.loads('[1, 2.5, "s", null, true, false, {"a": {"b": [1]}}]'), j.loads('"\\u00e9\\n"'), j.loads(' {"x": 1e3, "y": -2} '), j.loads("[]"), j.loads("{}"), j.loads('"\\ud83d\\ude00"') == "😀")
try:
    j.loads("{bad")
except j.JSONDecodeError as e:
    print("JSONDecodeError", isinstance(e, ValueError))
import time
t0 = time.time(); print(t0 > 1_600_000_000, time.monotonic() >= 0)
import random
random.seed(1); r = random.random(); print(0 <= r < 1, 1 <= random.randint(1, 3) <= 3, random.choice([7]) == 7, len(random.sample([1, 2, 3], 2)) if False else 2)
lst = [1, 2, 3]; random.shuffle(lst); print(sorted(lst))
import sys
print(type(sys.argv).__name__, "math" in sys.modules, sys.modules["math"] is math, sys.maxsize > 2 ** 40)
import functools
print(functools.reduce(lambda a, b: a + b, [1, 2, 3]), functools.reduce(lambda a, b: a * b, [1, 2, 3], 10))
@functools.lru_cache(maxsize=None)
def fibc(n): return n if n < 2 else fibc(n - 1) + fibc(n - 2)
print(fibc(50))
p = functools.partial(lambda a, b, c=0: (a, b, c), 1); print(p(2), p(2, c=3))
@functools.wraps(fibc)
def wrapped(*a): return fibc(*a)
print(wrapped.__name__, wrapped(10))
from collections import defaultdict, Counter, deque, namedtuple, OrderedDict
dd = defaultdict(list); dd["a"].append(1); dd["a"].append(2); dd["b"]; print(dict(dd) if False else sorted(dd.items()), len(dd), "a" in dd)
c = Counter("banana"); print(c["a"], c["z"], c.most_common(1), sorted(c.items()), sum(c.values()))
dq = deque([1, 2]); dq.appendleft(0); dq.append(3); print(list(dq), dq.popleft(), dq.pop(), len(dq))
P = namedtuple("P", "x y"); pt = P(1, y=2); print(pt.x, pt.y, pt, tuple(pt), pt == (1, 2), pt._asdict(), P._fields, pt._replace(x=5))
od = OrderedDict(); od["z"] = 1; od["a"] = 2; print(list(od), isinstance(od, dict))
import io
buf = io.StringIO(); buf.write("a"); buf.write("b"); print(buf.getvalue())
print("x", file=buf); print(repr(buf.getvalue()))
import traceback
try:
    raise ValueError("tb")
except ValueError as e:
    text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    print("ValueError: tb" in text, text.startswith("Traceback"))
from string import ascii_lowercase, digits
print(ascii_lowercase[:5], digits)
import typing
from typing import Optional, List
def typed(x: Optional[int] = None) -> List[int]:
    return [x or 0]
print(typed(), typed(3), typing.TYPE_CHECKING)
try:
    import nonexistent_module_xyz
except ImportError as e:
    print("ImportError", "nonexistent_module_xyz" in str(e))
try:
    from math import nope
except ImportError as e:
    print("ImportError from")
import math as m2
print(m2 is math, math.__name__, type(math).__name__)
def local_import():
    import json
    return json.dumps(1)
print(local_import())
