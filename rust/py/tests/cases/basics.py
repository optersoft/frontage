# arithmetic, comparison, truth
print(1 + 2, 7 - 10, 3 * 4, 7 / 2, 7 // 2, -7 // 2, 7 % 3, -7 % 3, 7 % -3, 2 ** 10, 2 ** -1, 5 ** 0)
print(1.5 + 1, 3.0 // 2, -3.5 // 2, 3.5 % 2, -3.5 % 2, 2.0 ** 0.5, 10 / 4, 1e3, 1.5e-3)
print(7 & 3, 7 | 8, 7 ^ 2, ~5, 1 << 10, 1024 >> 3, -16 >> 2)
print(1 < 2, 2 <= 2, 3 > 4, 1 == 1.0, 1 != 2, 1 < 2 < 3, 1 < 3 < 2, "a" < "b", [1, 2] < [1, 3], (1, 2) == (1, 2))
print(True + True, True * 3, not 0, not [], bool(""), bool("x"), bool(0.0), bool([0]), None is None, 1 is not None)
print(3 and 4, 0 and 4, 0 or 5, "" or "d", None or 0, 1 if True else 2, 1 if False else 2)
print(divmod(17, 5), divmod(-17, 5), abs(-3), abs(-2.5), min(3, 1, 2), max([4, 9, 2]), min("b", "a"), max(1, 2, key=lambda x: -x))
print(round(2.5), round(3.5), round(-2.5), round(2.675, 2), round(1234, -2), round(0.5), round(1.5))
print(int(3.9), int(-3.9), int("  42 "), int("-7"), int("ff", 16), int("0x1f", 16), int("101", 2), float("2.5"), float("1e-3"), float(" -0.5 "))
print(str(42), str(2.0), str(True), str(None), repr("a'b"), repr('a"b'), repr("a'b\"c"), repr("tab\t"), repr("\n"))
print(1_000_000, 0x_ff, 0o17, 0b1010, 1e2, 2.5e-1, 10 ** 15, 2 ** 40, -(2 ** 33))
print(2147483647 + 1, -2147483648 - 1, 3000000000 * 3, 12345678901234 // 7, 12345678901234 % 7)
print(0.1 + 0.2, 1 / 3, 2 / 3, 1e16, 1e15, 123456789.0, 0.0001, 0.00001, -0.0, 1.0, 100.0, 1e22, 1e-7, 3.0e10)
print(float("inf"), -float("inf"), float("nan") != float("nan"), 5 // 0.5, 7.5 // 2.5)
x = 5
x += 2; x -= 1; x *= 3; x //= 2; x %= 5; x **= 2; x <<= 1; x >>= 1; x |= 8; x &= 12; x ^= 1
print(x)
a, b = 1, 2
a, b = b, a
print(a, b)
(c, d), e = (3, 4), 5
print(c, d, e)
first, *rest = [1, 2, 3, 4]
*init, last = [1, 2, 3, 4]
h, *mid, t = "abcde"
print(first, rest, init, last, h, mid, t)
print(chr(65), ord("a"), chr(0x1F600) == "😀", ord("é"), len("héllo"), "héllo"[1], "héllo"[-1], "日本語"[::-1])
print(hex(255), oct(8), bin(5), hex(-1), hash(1) == hash(1.0), hash("a") == hash("a"), hash((1, 2)) == hash((1, 2)))
print(pow(2, 10), pow(2, 10, 7), pow(2.0, 3), 10 ** -2)
print(type(1).__name__, type(1.0).__name__, type("").__name__, type([]).__name__, type({}).__name__, type(()).__name__, type(None).__name__, type(len).__name__, type(print), type(type))
print(isinstance(1, int), isinstance(True, int), isinstance(1, (str, int)), isinstance(1.0, int), issubclass(bool, int), issubclass(int, object))
print(callable(len), callable(1), callable(lambda: 0), callable(int))
