# binascii: base64 and hex both ways, a checksum, whitespace and an odd length.
import binascii
raw = binascii.a2b_base64(b"aGVsbG8gd29ybGQ=")
print(raw, binascii.b2a_base64(raw), binascii.b2a_base64(raw, newline=False))
print(binascii.hexlify(b"\x00\xff\x10"), binascii.unhexlify(b"00ff10"))
print(binascii.hexlify(b"\x00\xff\x10", b"-"))
print(binascii.crc32(b"hello world"))
print(binascii.a2b_base64(b"aGVs bG8g\nd29ybGQ="))
try:
    binascii.unhexlify(b"abc")
except ValueError as e:
    print("ValueError", e)
