"""html.escape / html.unescape."""

_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": "\xa0", "copy": "\xa9", "reg": "\xae", "hellip": "…", "mdash": "—", "ndash": "–", "laquo": "\xab", "raquo": "\xbb", "times": "\xd7", "euro": "€"}


def escape(s, quote=True):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if quote:
        s = s.replace('"', "&quot;").replace("'", "&#x27;")
    return s


def unescape(s):
    if "&" not in s:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "&":
            out.append(c)
            i += 1
            continue
        end = s.find(";", i + 1)
        if end < 0 or end - i > 12:
            out.append("&")
            i += 1
            continue
        name = s[i + 1:end]
        if name.startswith("#x") or name.startswith("#X"):
            try:
                out.append(chr(int(name[2:], 16)))
                i = end + 1
                continue
            except ValueError:
                pass
        elif name.startswith("#"):
            try:
                out.append(chr(int(name[1:])))
                i = end + 1
                continue
            except ValueError:
                pass
        elif name in _ENTITIES:
            out.append(_ENTITIES[name])
            i = end + 1
            continue
        out.append("&")
        i += 1
    return "".join(out)
