def risky(kind):
    if kind == "key": {}["k"]
    if kind == "idx": [][0]
    if kind == "type": 1 + "a"
    if kind == "val": int("x")
    if kind == "zero": 1 / 0
    if kind == "attr": None.x
    if kind == "name": undefined_name
    if kind == "custom": raise MyError("custom", 42)
    return "ok"
class MyError(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code
class SubError(MyError): pass
for k in ["key", "idx", "type", "val", "zero", "attr", "name", "custom", "none"]:
    try:
        print(risky(k))
    except (KeyError, IndexError) as e:
        print("lookup", type(e).__name__, repr(e), str(e), e.args)
    except MyError as e:
        print("mine", e, e.code, e.args, isinstance(e, Exception))
    except Exception as e:
        print("other", type(e).__name__, str(e)[:30])
def nested():
    try:
        try:
            raise ValueError("inner")
        except ValueError as e:
            raise TypeError("outer") from e
    except TypeError as e:
        print("caught", e, type(e.__cause__).__name__, e.__cause__, e.__context__ is e.__cause__)
nested()
def implicit_chain():
    try:
        try:
            1 / 0
        except ZeroDivisionError:
            raise KeyError("during")
    except KeyError as e:
        print("chain", type(e.__context__).__name__, e.__cause__)
implicit_chain()
def fin():
    out = []
    try:
        out.append("try")
        return out
    finally:
        out.append("finally")
print(fin())
def fin2():
    for i in range(3):
        try:
            if i == 1: continue
            if i == 2: break
            print("body", i)
        finally:
            print("fin", i)
    print("done")
fin2()
def reraise():
    try:
        raise ValueError("v")
    except ValueError:
        try:
            raise
        except ValueError as e2:
            print("reraised", e2)
reraise()
def else_clause():
    for x in [1, 2]:
        try:
            pass
        except Exception:
            print("no")
        else:
            print("else", x)
        finally:
            print("fin", x)
else_clause()
try:
    try:
        raise SubError("sub", 1)
    except MyError as e:
        print("MyError catches SubError", type(e).__name__)
        raise
except SubError as e:
    print("outer", e.code)
try:
    raise ValueError
except ValueError as e:
    print(repr(e), str(e) == "", e.args)
try:
    raise ValueError("a", "b")
except ValueError as e:
    print(str(e), e.args)
try:
    assert 1 == 2, "math is broken"
except AssertionError as e:
    print("AssertionError", e)
try:
    assert False
except AssertionError as e:
    print("AssertionError", repr(e))
def gen():
    try:
        yield 1
        yield 2
    finally:
        print("gen finally")
g = gen(); print(next(g)); g.close(); print("closed")
def gen2():
    try:
        yield 1
    except KeyError:
        print("caught in gen")
        yield 3
    finally:
        print("gen2 finally")
g = gen2(); print(next(g), g.throw(KeyError()))
try:
    next(g)
except StopIteration:
    print("stop")
import sys
try:
    raise RuntimeError("info")
except RuntimeError:
    print(sys.exc_info()[0].__name__, sys.exc_info()[1])
print(sys.exc_info()[1])
try:
    raise KeyError("k")
except LookupError as e:
    print("LookupError", e)
try:
    [].pop()
except IndexError as e:
    print(e)
try:
    {}.pop("x")
except KeyError as e:
    print(repr(e))
try:
    x = 1
    x.foo = 2
except AttributeError as e:
    print("AttributeError", e)
try:
    raise StopIteration(5)
except StopIteration as e:
    print(e.value, e.args)
def f_raises():
    raise NotImplementedError("todo")
try:
    f_raises()
except NotImplementedError as e:
    print(type(e).__name__, e, isinstance(e, RuntimeError))
try:
    int(None)
except TypeError as e:
    print("TypeError")
try:
    (1, 2)[5]
except IndexError as e:
    print(e)
try:
    "abc"[10]
except IndexError as e:
    print(e)
try:
    None()
except TypeError as e:
    print(e)
try:
    len(5)
except TypeError as e:
    print(e)
try:
    {[]: 1}
except TypeError as e:
    print(e)
try:
    1 < "a"
except TypeError as e:
    print(e)
class Bad:
    pass
try:
    Bad(1)
except TypeError as e:
    print(e)
try:
    raise
except RuntimeError as e:
    print(e)
try:
    raise 5
except TypeError as e:
    print(e)
print("end")
