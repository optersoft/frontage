# time: the calendar half — gmtime's nine fields and strftime's directives, in the C locale.
# `gmtime` answers a plain tuple here and a `struct_time` in CPython; both index the same,
# so the case indexes rather than printing the object.
import time

for secs in (0, 1, 951825600, 1757500000, 4102444800, -1, -86400 * 400):
    print(tuple(time.gmtime(secs)))

t = time.gmtime(1757500000)
print(time.strftime("%Y-%m-%d %H:%M:%S", t))
print(time.strftime("%a %A %b %B %j %I %p %y %D %F %T", t))
print(time.strftime("100%% literal", t))
print(time.strftime("%Y-%m-%d", time.gmtime(0)), time.strftime("%H:%M", (2026, 9, 10, 7, 5, 0, 3, 253, 0)))
print(time.strftime("%A", time.gmtime(86400 * 3)), time.strftime("%j", time.gmtime(86400 * 364)))

now = time.gmtime(time.time())
print(now[0] >= 2026, 1 <= now[1] <= 12, 0 <= now[6] <= 6, 1 <= now[7] <= 366, now[8])
