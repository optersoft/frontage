# bytes.find / startswith / endswith. A streamed body arrives in pieces that cut anywhere, so
# the reader that reassembles it searches bytes, not text — decoding first is what breaks on a
# multi-byte character split across two chunks.
b = b"data: hello\r\ndata: \xc3\xa9t\xc3\xa9\r\n"

print(b.find(b"\n"), b.find(b"\r\n"), b.find(b"data: ", 1), b.find(b"nope"))
print(b.find(b""), b"".find(b""), b"".find(b"x"))
print(b.find(b"data", 0, 3), b.find(b"data", -6))
print(b.startswith(b"data"), b.startswith(b"ata", 1), b.endswith(b"\r\n"), b.endswith(b"x"))
print(b[:11].endswith(b"hello"), b.startswith(b""), b.endswith(b""))

# The pieces, reassembled and split on the boundary, decode whole.
rest = b""
lines = []
for piece in (b"data: caf", b"\xc3\xa9\r\ndata: two\r\n"):
    rest = rest + piece
    while True:
        cut = rest.find(b"\n")
        if cut < 0:
            break
        line = rest[:cut]
        rest = rest[cut + 1:]
        if line.endswith(b"\r"):
            line = line[:-1]
        lines.append(line.decode("utf-8"))
print(lines, rest)

print(bytearray(b"abcabc").find(b"c"), bytearray(b"abc").endswith(b"bc"))

try:
    b"abc".find("a")
except TypeError as e:
    print("TypeError")
