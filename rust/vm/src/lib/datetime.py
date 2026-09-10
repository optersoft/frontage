# `datetime`, over `time.gmtime`'s calendar (`modules.rs`) — the subset a server and a page
# actually write: `timedelta`, `timezone`, `date`, `time`, `datetime`.
#
# ⚠ There is no time zone database, so **the runtime's local time is UTC**: `datetime.now()`
# with no `tz` is the UTC wall clock, and a naive datetime is read as UTC by `timestamp()`.
# CPython would use the machine's zone for both. Everything else here matches CPython byte
# for byte, `repr` and `isoformat` included — `rust/py/tests/cases/datetime_mod.py` is the
# proof.
import time as _time

MINYEAR = 1
MAXYEAR = 9999

_DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_EPOCH_ORDINAL = 719163  # 1970-01-01


def _is_leap(y):
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0


def _days_in_month(y, m):
    if m == 2 and _is_leap(y):
        return 29
    return _DAYS_IN_MONTH[m]


def _days_from_civil(y, m, d):
    # Howard Hinnant's, the inverse of the one in `modules.rs`. Days since 1970-01-01.
    if m <= 2:
        y = y - 1
        mp = m + 9
    else:
        mp = m - 3
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(days):
    t = _time.gmtime(days * 86400)
    return t[0], t[1], t[2]


def _check_date(y, m, d):
    if not MINYEAR <= y <= MAXYEAR:
        raise ValueError("year " + str(y) + " is out of range")
    if not 1 <= m <= 12:
        raise ValueError("month must be in 1..12, not " + str(m))
    dim = _days_in_month(y, m)
    if not 1 <= d <= dim:
        raise ValueError("day " + str(d) + " must be in range 1.." + str(dim) + " for month " + str(m) + " in year " + str(y))


def _check_time(h, mi, s, us):
    if not 0 <= h <= 23:
        raise ValueError("hour must be in 0..23, not " + str(h))
    if not 0 <= mi <= 59:
        raise ValueError("minute must be in 0..59, not " + str(mi))
    if not 0 <= s <= 59:
        raise ValueError("second must be in 0..59, not " + str(s))
    if not 0 <= us <= 999999:
        raise ValueError("microsecond must be in 0..999999, not " + str(us))


def _f(n, width):
    neg = n < 0
    s = str(-n if neg else n)
    while len(s) < width:
        s = "0" + s
    return ("-" + s) if neg else s


class timedelta:
    def __init__(self, days=0, seconds=0, microseconds=0, milliseconds=0, minutes=0, hours=0, weeks=0):
        # Days are carried whole rather than folded into a microsecond total: the runtime's
        # ints are 64 bits, and `timedelta.max` in microseconds is 8.6e19, which is not.
        d = days + weeks * 7
        extra = 0
        if isinstance(d, float):
            whole = int(d)
            extra = round((d - whole) * 86400000000)
            d = whole
        us = round((hours * 3600 + minutes * 60 + seconds) * 1000000 + milliseconds * 1000 + microseconds) + extra
        carry, us = divmod(us, 86400000000)
        s, us = divmod(us, 1000000)
        self._d = d + carry
        self._s = s
        self._us = us

    days = property(lambda self: self._d)
    seconds = property(lambda self: self._s)
    microseconds = property(lambda self: self._us)

    def total_seconds(self):
        return (self._d * 86400 + self._s) + self._us / 1000000

    def _all_us(self):
        # ⚠ Only safe within about ±106,000 days; the comparisons use `_key` for that reason.
        return (self._d * 86400 + self._s) * 1000000 + self._us

    def _key(self):
        return (self._d, self._s, self._us)

    def __repr__(self):
        parts = []
        if self._d:
            parts.append("days=" + str(self._d))
        if self._s:
            parts.append("seconds=" + str(self._s))
        if self._us:
            parts.append("microseconds=" + str(self._us))
        if not parts:
            parts.append("0")
        return "datetime.timedelta(" + ", ".join(parts) + ")"

    def __str__(self):
        mm, ss = divmod(self._s, 60)
        hh, mm = divmod(mm, 60)
        s = str(hh) + ":" + _f(mm, 2) + ":" + _f(ss, 2)
        if self._d:
            plural = "s" if abs(self._d) != 1 else ""
            s = str(self._d) + " day" + plural + ", " + s
        if self._us:
            s = s + "." + _f(self._us, 6)
        return s

    def __add__(self, other):
        if isinstance(other, timedelta):
            return timedelta(days=self._d + other._d, seconds=self._s + other._s, microseconds=self._us + other._us)
        return NotImplemented

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        if isinstance(other, timedelta):
            return timedelta(days=self._d - other._d, seconds=self._s - other._s, microseconds=self._us - other._us)
        return NotImplemented

    def __neg__(self):
        return timedelta(days=-self._d, seconds=-self._s, microseconds=-self._us)

    def __pos__(self):
        return self

    def __abs__(self):
        return -self if self._d < 0 else self

    def __mul__(self, other):
        if isinstance(other, int):
            return timedelta(microseconds=self._all_us() * other)
        if isinstance(other, float):
            return timedelta(microseconds=round(self._all_us() * other))
        return NotImplemented

    def __rmul__(self, other):
        return self.__mul__(other)

    def __truediv__(self, other):
        if isinstance(other, timedelta):
            return self._all_us() / other._all_us()
        if isinstance(other, int) or isinstance(other, float):
            return timedelta(microseconds=round(self._all_us() / other))
        return NotImplemented

    def __floordiv__(self, other):
        if isinstance(other, timedelta):
            return self._all_us() // other._all_us()
        if isinstance(other, int):
            return timedelta(microseconds=self._all_us() // other)
        return NotImplemented

    def __bool__(self):
        return self._d != 0 or self._s != 0 or self._us != 0

    def __eq__(self, other):
        return isinstance(other, timedelta) and self._key() == other._key()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        return self._key() < other._key()

    def __le__(self, other):
        return self._key() <= other._key()

    def __gt__(self, other):
        return self._key() > other._key()

    def __ge__(self, other):
        return self._key() >= other._key()

    def __hash__(self):
        return hash(self._key())


timedelta.min = timedelta(days=-999999999)
timedelta.max = timedelta(days=999999999, hours=23, minutes=59, seconds=59, microseconds=999999)
timedelta.resolution = timedelta(microseconds=1)


class timezone:
    def __init__(self, offset, name=None):
        if not isinstance(offset, timedelta):
            raise TypeError("offset must be a timedelta")
        self._offset = offset
        self._name = name

    def utcoffset(self, dt=None):
        return self._offset

    def tzname(self, dt=None):
        if self._name is not None:
            return self._name
        if self._offset._all_us() == 0:
            return "UTC"
        return "UTC" + self._iso()

    def dst(self, dt=None):
        return None

    def _iso(self):
        us = self._offset._all_us()
        sign = "-" if us < 0 else "+"
        us = abs(us)
        s, us = divmod(us, 1000000)
        mm, ss = divmod(s, 60)
        hh, mm = divmod(mm, 60)
        out = sign + _f(hh, 2) + ":" + _f(mm, 2)
        if ss or us:
            out = out + ":" + _f(ss, 2)
            if us:
                out = out + "." + _f(us, 6)
        return out

    def __repr__(self):
        if self._offset._all_us() == 0 and self._name is None:
            return "datetime.timezone.utc"
        r = "datetime.timezone(" + repr(self._offset)
        if self._name is not None:
            r = r + ", " + repr(self._name)
        return r + ")"

    def __str__(self):
        return self.tzname(None)

    def __eq__(self, other):
        return isinstance(other, timezone) and self._offset == other._offset

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._offset)


timezone.utc = timezone(timedelta(0))


class date:
    def __init__(self, year, month, day):
        _check_date(year, month, day)
        self._y = year
        self._m = month
        self._d = day

    year = property(lambda self: self._y)
    month = property(lambda self: self._m)
    day = property(lambda self: self._d)

    @staticmethod
    def today():
        t = _time.gmtime(_time.time())
        return date(t[0], t[1], t[2])

    @staticmethod
    def fromtimestamp(ts):
        t = _time.gmtime(ts)
        return date(t[0], t[1], t[2])

    @staticmethod
    def fromordinal(n):
        y, m, d = _civil_from_days(n - _EPOCH_ORDINAL)
        return date(y, m, d)

    @staticmethod
    def fromisoformat(s):
        if len(s) != 10 or s[4] != "-" or s[7] != "-":
            raise ValueError("Invalid isoformat string: " + repr(s))
        return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))

    def toordinal(self):
        return _days_from_civil(self._y, self._m, self._d) + _EPOCH_ORDINAL

    def replace(self, year=None, month=None, day=None):
        return date(self._y if year is None else year, self._m if month is None else month, self._d if day is None else day)

    def weekday(self):
        return (self.toordinal() + 6) % 7

    def isoweekday(self):
        return self.weekday() + 1

    def timetuple(self):
        return _time.gmtime(_days_from_civil(self._y, self._m, self._d) * 86400)

    def isoformat(self):
        return _f(self._y, 4) + "-" + _f(self._m, 2) + "-" + _f(self._d, 2)

    def strftime(self, fmt):
        return _strftime(fmt, self.timetuple(), 0, None)

    def __format__(self, spec):
        return self.strftime(spec) if spec else str(self)

    def __repr__(self):
        return "datetime.date(" + str(self._y) + ", " + str(self._m) + ", " + str(self._d) + ")"

    def __str__(self):
        return self.isoformat()

    def _key(self):
        return self.toordinal()

    def __eq__(self, other):
        return isinstance(other, date) and not isinstance(other, datetime) and self._key() == other._key()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        return self._key() < other._key()

    def __le__(self, other):
        return self._key() <= other._key()

    def __gt__(self, other):
        return self._key() > other._key()

    def __ge__(self, other):
        return self._key() >= other._key()

    def __hash__(self):
        return hash(self._key())

    def __add__(self, other):
        if isinstance(other, timedelta):
            return date.fromordinal(self.toordinal() + other.days)
        return NotImplemented

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        if isinstance(other, timedelta):
            return date.fromordinal(self.toordinal() - other.days)
        if isinstance(other, date):
            return timedelta(days=self.toordinal() - other.toordinal())
        return NotImplemented


date.min = date(1, 1, 1)
date.max = date(9999, 12, 31)
date.resolution = timedelta(days=1)


class time:
    def __init__(self, hour=0, minute=0, second=0, microsecond=0, tzinfo=None):
        _check_time(hour, minute, second, microsecond)
        self._h = hour
        self._mi = minute
        self._s = second
        self._us = microsecond
        self._tz = tzinfo

    hour = property(lambda self: self._h)
    minute = property(lambda self: self._mi)
    second = property(lambda self: self._s)
    microsecond = property(lambda self: self._us)
    tzinfo = property(lambda self: self._tz)

    def replace(self, hour=None, minute=None, second=None, microsecond=None, tzinfo=True):
        return time(
            self._h if hour is None else hour,
            self._mi if minute is None else minute,
            self._s if second is None else second,
            self._us if microsecond is None else microsecond,
            self._tz if tzinfo is True else tzinfo,
        )

    def utcoffset(self):
        return None if self._tz is None else self._tz.utcoffset(None)

    def isoformat(self):
        s = _f(self._h, 2) + ":" + _f(self._mi, 2) + ":" + _f(self._s, 2)
        if self._us:
            s = s + "." + _f(self._us, 6)
        if self._tz is not None:
            s = s + self._tz._iso()
        return s

    @staticmethod
    def fromisoformat(s):
        h, mi, sec, us, tz, used = _parse_time(s)
        if used != len(s):
            raise ValueError("Invalid isoformat string: " + repr(s))
        return time(h, mi, sec, us, tz)

    def __repr__(self):
        parts = [str(self._h), str(self._mi)]
        if self._s or self._us:
            parts.append(str(self._s))
        if self._us:
            parts.append(str(self._us))
        r = "datetime.time(" + ", ".join(parts)
        if self._tz is not None:
            r = r + ", tzinfo=" + repr(self._tz)
        return r + ")"

    def __str__(self):
        return self.isoformat()

    def _key(self):
        return (self._h, self._mi, self._s, self._us)

    def __eq__(self, other):
        return isinstance(other, time) and self._key() == other._key() and self._tz == other._tz

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        return self._key() < other._key()

    def __le__(self, other):
        return self._key() <= other._key()

    def __gt__(self, other):
        return self._key() > other._key()

    def __ge__(self, other):
        return self._key() >= other._key()

    def __hash__(self):
        return hash(self._key())


time.min = time(0, 0)
time.max = time(23, 59, 59, 999999)
time.resolution = timedelta(microseconds=1)


class datetime(date):
    def __init__(self, year, month, day, hour=0, minute=0, second=0, microsecond=0, tzinfo=None):
        _check_date(year, month, day)
        _check_time(hour, minute, second, microsecond)
        self._y = year
        self._m = month
        self._d = day
        self._h = hour
        self._mi = minute
        self._s = second
        self._us = microsecond
        self._tz = tzinfo

    hour = property(lambda self: self._h)
    minute = property(lambda self: self._mi)
    second = property(lambda self: self._s)
    microsecond = property(lambda self: self._us)
    tzinfo = property(lambda self: self._tz)

    @staticmethod
    def now(tz=None):
        # ⚠ UTC, with or without `tz`: the runtime has no zone database.
        return datetime.fromtimestamp(_time.time(), tz)

    @staticmethod
    def utcnow():
        return datetime.fromtimestamp(_time.time(), None)

    @staticmethod
    def today():
        return datetime.now(None)

    @staticmethod
    def fromtimestamp(ts, tz=None):
        off = 0.0 if tz is None else tz.utcoffset(None).total_seconds()
        shifted = ts + off
        whole = shifted // 1
        us = round((shifted - whole) * 1000000)
        if us >= 1000000:
            whole = whole + 1
            us = us - 1000000
        t = _time.gmtime(whole)
        return datetime(t[0], t[1], t[2], t[3], t[4], t[5], us, tz)

    @staticmethod
    def utcfromtimestamp(ts):
        return datetime.fromtimestamp(ts, None)

    @staticmethod
    def combine(d, t, tzinfo=True):
        tz = t._tz if tzinfo is True else tzinfo
        return datetime(d._y, d._m, d._d, t._h, t._mi, t._s, t._us, tz)

    @staticmethod
    def fromordinal(n):
        y, m, d = _civil_from_days(n - _EPOCH_ORDINAL)
        return datetime(y, m, d)

    @staticmethod
    def fromisoformat(s):
        if len(s) < 10 or s[4] != "-" or s[7] != "-":
            raise ValueError("Invalid isoformat string: " + repr(s))
        y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        if len(s) == 10:
            return datetime(y, mo, d)
        rest = s[11:]
        h, mi, sec, us, tz, used = _parse_time(rest)
        if used != len(rest):
            raise ValueError("Invalid isoformat string: " + repr(s))
        return datetime(y, mo, d, h, mi, sec, us, tz)

    def date(self):
        return date(self._y, self._m, self._d)

    def time(self):
        return time(self._h, self._mi, self._s, self._us)

    def timetz(self):
        return time(self._h, self._mi, self._s, self._us, self._tz)

    def replace(self, year=None, month=None, day=None, hour=None, minute=None, second=None, microsecond=None, tzinfo=True):
        return datetime(
            self._y if year is None else year,
            self._m if month is None else month,
            self._d if day is None else day,
            self._h if hour is None else hour,
            self._mi if minute is None else minute,
            self._s if second is None else second,
            self._us if microsecond is None else microsecond,
            self._tz if tzinfo is True else tzinfo,
        )

    def utcoffset(self):
        return None if self._tz is None else self._tz.utcoffset(self)

    def tzname(self):
        return None if self._tz is None else self._tz.tzname(self)

    def dst(self):
        return None if self._tz is None else self._tz.dst(self)

    def astimezone(self, tz=None):
        if tz is None:
            tz = timezone.utc
        if self._tz is None:
            return self.replace(tzinfo=tz)
        return datetime.fromtimestamp(self.timestamp(), tz)

    def timestamp(self):
        # ⚠ A naive datetime is read as UTC; CPython reads it as local time.
        off = 0 if self._tz is None else self._tz.utcoffset(self)._all_us()
        us = (_days_from_civil(self._y, self._m, self._d) * 86400 + self._h * 3600 + self._mi * 60 + self._s) * 1000000 + self._us - off
        return us / 1000000

    def timetuple(self):
        return _time.gmtime(_days_from_civil(self._y, self._m, self._d) * 86400 + self._h * 3600 + self._mi * 60 + self._s)

    def toordinal(self):
        return _days_from_civil(self._y, self._m, self._d) + _EPOCH_ORDINAL

    def isoformat(self, sep="T"):
        s = _f(self._y, 4) + "-" + _f(self._m, 2) + "-" + _f(self._d, 2) + sep + _f(self._h, 2) + ":" + _f(self._mi, 2) + ":" + _f(self._s, 2)
        if self._us:
            s = s + "." + _f(self._us, 6)
        if self._tz is not None:
            s = s + self._tz._iso()
        return s

    def strftime(self, fmt):
        return _strftime(fmt, self.timetuple(), self._us, self._tz)

    def __repr__(self):
        parts = [str(self._y), str(self._m), str(self._d), str(self._h), str(self._mi)]
        if self._s or self._us:
            parts.append(str(self._s))
        if self._us:
            parts.append(str(self._us))
        r = "datetime.datetime(" + ", ".join(parts)
        if self._tz is not None:
            r = r + ", tzinfo=" + repr(self._tz)
        return r + ")"

    def __str__(self):
        return self.isoformat(" ")

    def _key(self):
        us = (_days_from_civil(self._y, self._m, self._d) * 86400 + self._h * 3600 + self._mi * 60 + self._s) * 1000000 + self._us
        if self._tz is not None:
            us = us - self._tz.utcoffset(self)._all_us()
        return us

    def __eq__(self, other):
        if not isinstance(other, datetime):
            return False
        if (self._tz is None) != (other._tz is None):
            return False
        return self._key() == other._key()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._key())

    def __add__(self, other):
        if isinstance(other, timedelta):
            return datetime._from_us(self._key() + other._all_us(), self._tz)
        return NotImplemented

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        if isinstance(other, timedelta):
            return datetime._from_us(self._key() - other._all_us(), self._tz)
        if isinstance(other, datetime):
            return timedelta(microseconds=self._key() - other._key())
        return NotImplemented

    @staticmethod
    def _from_us(us, tz):
        # `us` is UTC when `tz` is set, which is what `_key` produced.
        if tz is not None:
            us = us + tz.utcoffset(None)._all_us()
        s, rem = divmod(us, 1000000)
        t = _time.gmtime(s)
        return datetime(t[0], t[1], t[2], t[3], t[4], t[5], rem, tz)


datetime.min = datetime(1, 1, 1)
datetime.max = datetime(9999, 12, 31, 23, 59, 59, 999999)
datetime.resolution = timedelta(microseconds=1)


def _parse_time(s):
    """`HH[:MM[:SS[.ffffff]]][Z|±HH:MM[:SS]]` → (h, m, s, us, tz, characters used)."""
    n = len(s)
    if n < 2:
        raise ValueError("Invalid isoformat string")
    h = int(s[0:2])
    mi = sec = us = 0
    i = 2
    if i + 2 < n and s[i] == ":":
        mi = int(s[i + 1 : i + 3])
        i = i + 3
        if i + 2 < n and s[i] == ":":
            sec = int(s[i + 1 : i + 3])
            i = i + 3
            if i < n and s[i] == ".":
                j = i + 1
                while j < n and s[j].isdigit():
                    j = j + 1
                frac = s[i + 1 : j]
                while len(frac) < 6:
                    frac = frac + "0"
                us = int(frac[0:6])
                i = j
    tz = None
    if i < n and s[i] == "Z":
        tz = timezone.utc
        i = i + 1
    elif i < n and (s[i] == "+" or s[i] == "-"):
        sign = -1 if s[i] == "-" else 1
        oh = int(s[i + 1 : i + 3])
        om = os_ = 0
        i = i + 3
        if i + 2 < n and s[i] == ":":
            om = int(s[i + 1 : i + 3])
            i = i + 3
            if i + 2 < n and s[i] == ":":
                os_ = int(s[i + 1 : i + 3])
                i = i + 3
        off = timedelta(hours=sign * oh, minutes=sign * om, seconds=sign * os_)
        tz = timezone.utc if off._all_us() == 0 else timezone(off)
    return h, mi, sec, us, tz, i


def _strftime(fmt, tt, us, tz):
    """`time.strftime`, with the three directives it cannot know: `%f`, `%z`, `%Z`."""
    if "%f" in fmt or "%z" in fmt or "%Z" in fmt:
        out = []
        i = 0
        n = len(fmt)
        while i < n:
            c = fmt[i]
            if c == "%" and i + 1 < n:
                spec = fmt[i + 1]
                if spec == "f":
                    out.append(_f(us, 6))
                elif spec == "z":
                    out.append("" if tz is None else tz._iso().replace(":", ""))
                elif spec == "Z":
                    out.append("" if tz is None else tz.tzname(None))
                else:
                    out.append(c + spec)
                i = i + 2
                continue
            out.append(c)
            i = i + 1
        fmt = "".join(out)
    return _time.strftime(fmt, tt)
