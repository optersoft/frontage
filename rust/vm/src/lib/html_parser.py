"""A small html.parser.HTMLParser: tags, attributes, text, comments, doctype."""

from html import unescape

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_RAW = {"script", "style"}


class HTMLParser:
    def __init__(self, convert_charrefs=True):
        self.convert_charrefs = convert_charrefs
        self.rawdata = ""

    def reset(self):
        self.rawdata = ""

    def feed(self, data):
        self.rawdata += data
        self.goahead()

    def close(self):
        self.goahead()

    def handle_starttag(self, tag, attrs):
        pass

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        pass

    def handle_data(self, data):
        pass

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def _text(self, s):
        if s:
            self.handle_data(unescape(s) if self.convert_charrefs else s)

    def goahead(self):
        s = self.rawdata
        self.rawdata = ""
        i = 0
        n = len(s)
        while i < n:
            lt = s.find("<", i)
            if lt < 0:
                self._text(s[i:])
                break
            self._text(s[i:lt])
            if s.startswith("<!--", lt):
                end = s.find("-->", lt + 4)
                if end < 0:
                    end = n
                self.handle_comment(s[lt + 4:end])
                i = end + 3
            elif s.startswith("<!", lt):
                end = s.find(">", lt)
                if end < 0:
                    end = n
                self.handle_decl(s[lt + 2:end])
                i = end + 1
            elif s.startswith("<?", lt):
                end = s.find(">", lt)
                if end < 0:
                    end = n
                self.handle_pi(s[lt + 2:end])
                i = end + 1
            elif s.startswith("</", lt):
                end = s.find(">", lt)
                if end < 0:
                    end = n
                self.handle_endtag(s[lt + 2:end].strip().lower())
                i = end + 1
            else:
                j = lt + 1
                while j < n and (s[j].isalnum() or s[j] in "-_:"):
                    j += 1
                tag = s[lt + 1:j].lower()
                if not tag:
                    self._text("<")
                    i = lt + 1
                    continue
                attrs = []
                selfclosing = False
                while j < n:
                    while j < n and s[j] in " \t\n\r":
                        j += 1
                    if j >= n:
                        break
                    if s[j] == ">":
                        j += 1
                        break
                    if s.startswith("/>", j):
                        selfclosing = True
                        j += 2
                        break
                    k = j
                    while k < n and s[k] not in " \t\n\r=>/":
                        k += 1
                    name = s[j:k].lower()
                    j = k
                    while j < n and s[j] in " \t\n\r":
                        j += 1
                    value = None
                    if j < n and s[j] == "=":
                        j += 1
                        while j < n and s[j] in " \t\n\r":
                            j += 1
                        if j < n and s[j] in "\"'":
                            q = s[j]
                            end = s.find(q, j + 1)
                            if end < 0:
                                end = n
                            value = s[j + 1:end]
                            j = end + 1
                        else:
                            k = j
                            while k < n and s[k] not in " \t\n\r>":
                                k += 1
                            value = s[j:k]
                            j = k
                        if self.convert_charrefs:
                            value = unescape(value)
                    if name:
                        attrs.append((name, value))
                i = j
                if selfclosing:
                    self.handle_startendtag(tag, attrs)
                else:
                    self.handle_starttag(tag, attrs)
                    if tag in _RAW:
                        close = s.find("</" + tag, i)
                        if close < 0:
                            close = n
                        self.handle_data(s[i:close])
                        i = close
