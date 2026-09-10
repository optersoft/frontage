# datetime: repr and isoformat byte for byte, arithmetic, parsing, strftime, ordering.
# Nothing here reads the clock — `datetime.now()` is UTC in this runtime and local in
# CPython, which is the one documented difference (`vm/src/lib/datetime.py`).
from datetime import date, datetime, time, timedelta, timezone

d = date(2026, 9, 10)
print(repr(d), d, d.weekday(), d.isoweekday(), d.toordinal(), d.isoformat())
print(repr(d + timedelta(days=30)), repr(d - timedelta(weeks=2)), date(2026, 12, 25) - d)
print(date.fromordinal(739500), date.fromisoformat("2026-02-28"), date(2024, 2, 29).weekday())
print(sorted([date(2026, 1, 2), date(2025, 5, 5), date(2026, 1, 1)]))

dt = datetime(2026, 9, 10, 14, 30, 5, 123456, timezone.utc)
print(repr(dt))
print(dt.isoformat(), "|", dt.isoformat(" "), "|", str(dt))
print(dt.strftime("%Y-%m-%d %H:%M:%S.%f %z %Z %A %B %j %I%p"))
print(dt.timestamp(), repr(datetime.fromtimestamp(0, timezone.utc)))
print(repr(dt.date()), repr(dt.time()), repr(dt.timetz()))
print(repr(dt.replace(microsecond=0, tzinfo=None)))
print(repr(datetime.fromisoformat("2026-09-10T14:30:05.123456+02:00")))
print(repr(datetime.fromisoformat("2026-09-10T14:30:05Z")), repr(datetime.fromisoformat("2026-09-10")))
print(repr(dt.astimezone(timezone(timedelta(hours=2)))))
print(dt - datetime(2026, 9, 1, tzinfo=timezone.utc), repr(dt + timedelta(hours=36)))
print(repr(datetime.combine(date(2026, 1, 1), time(9, 30))))
print(datetime(2026, 1, 1) < datetime(2026, 1, 2), datetime(2026, 1, 1) == datetime(2026, 1, 1))

td = timedelta(days=1, hours=2, minutes=3, seconds=4, milliseconds=5, microseconds=6)
print(repr(td), str(td), td.total_seconds(), td.days, td.seconds, td.microseconds)
print(repr(timedelta(0)), str(timedelta(seconds=-1)), repr(-td), bool(timedelta(0)))
print(repr(td * 2), repr(td // 2), td / timedelta(hours=1))
print(str(timedelta(minutes=90)), str(timedelta(days=-2, hours=1)))

print(repr(timezone.utc), str(timezone.utc), repr(timezone(timedelta(hours=-3))))
print(repr(time(9, 5)), repr(time(9, 5, 1, 7)), time(9, 5, tzinfo=timezone.utc).isoformat())
print(repr(datetime.min), repr(datetime(1, 1, 1) + timedelta(days=1)), repr(date.max))

try:
    date(2026, 2, 30)
except ValueError as e:
    print("ValueError", e)
try:
    datetime(2026, 1, 1, 25)
except ValueError as e:
    print("ValueError", e)
try:
    datetime.fromisoformat("nope")
except ValueError as e:
    print("ValueError", e)

# The clock, without printing it: only that it moves and lands in this decade.
now = datetime.now(timezone.utc)
print(now.year >= 2026, now.tzinfo is timezone.utc, isinstance(now, datetime), isinstance(now, date))
