"""Open documents, and the one conversion every LSP server gets wrong once.

The protocol addresses text as `{line, character}` where *character* counts UTF-16 code
units, not Python characters: an emoji is two, an accented letter is one. The package's own
docs are written in Catalan and Spanish as well as English, so this is not a hypothetical —
a `<p>Àlex</p>` past column zero would shift every range after it if we counted bytes, and
an emoji in a template would shift them if we counted code points. `offset_at` and
`position_at` are the only places that know this; everything above them works in plain
Python string offsets.
"""


def _utf16_len(text):
    """The length of `text` in UTF-16 code units."""
    extra = 0
    for char in text:
        if ord(char) > 0xFFFF:  # astral plane: a surrogate pair
            extra += 1
    return len(text) + extra


class Document:
    """One open file: its text, the client's version, and a line index."""

    def __init__(self, uri, text, version=0, language_id="python"):
        self.uri = uri
        self.language_id = language_id
        self.replace(text, version)

    def replace(self, text, version=None):
        self.text = text
        if version is not None:
            self.version = version
        # Start offset of each line. A trailing newline makes a final empty line, which is
        # where a cursor sits after the last character, so it has to be in the index.
        starts = [0]
        for index, char in enumerate(text):
            if char == "\n":
                starts.append(index + 1)
        self._starts = starts

    @property
    def line_count(self):
        return len(self._starts)

    def line(self, number):
        """Line `number` (0-based) including its newline, or "" past the end."""
        if number < 0 or number >= len(self._starts):
            return ""
        start = self._starts[number]
        end = self._starts[number + 1] if number + 1 < len(self._starts) else len(self.text)
        return self.text[start:end]

    def offset_at(self, position):
        """A protocol `{line, character}` as a Python string offset, clamped to the text."""
        number = position.get("line", 0)
        if number < 0:
            return 0
        if number >= len(self._starts):
            return len(self.text)
        start = self._starts[number]
        line = self.line(number).rstrip("\n").rstrip("\r")
        wanted = position.get("character", 0)
        units = 0
        for index, char in enumerate(line):
            if units >= wanted:
                return start + index
            units += 2 if ord(char) > 0xFFFF else 1
        return start + len(line)

    def position_at(self, offset):
        """A Python string offset as a protocol `{line, character}`."""
        offset = max(0, min(offset, len(self.text)))
        # The last line whose start is at or before `offset`; linear from a bisect would be
        # fine at this scale, but files get long and this runs per finding.
        low, high = 0, len(self._starts) - 1
        while low < high:
            mid = (low + high + 1) // 2
            if self._starts[mid] <= offset:
                low = mid
            else:
                high = mid - 1
        return {"line": low, "character": _utf16_len(self.text[self._starts[low] : offset])}

    def range_at(self, start, end):
        return {"start": self.position_at(start), "end": self.position_at(end)}

    def offset_of_line(self, number):
        """Start offset of a 1-based line number, as `ast` reports them."""
        index = number - 1
        if index < 0:
            return 0
        if index >= len(self._starts):
            return len(self.text)
        return self._starts[index]

    def offset_of(self, lineno, col_offset):
        """An `ast` position — 1-based line, 0-based *byte* column — as a string offset.

        `col_offset` counts UTF-8 bytes, which is a third encoding and the reason this
        helper exists rather than a bare addition.
        """
        start = self.offset_of_line(lineno)
        line = self.text[start:]
        newline = line.find("\n")
        if newline >= 0:
            line = line[:newline]
        if col_offset <= 0:
            return start
        encoded = line.encode("utf-8")[:col_offset]
        return start + len(encoded.decode("utf-8", "ignore"))


class Documents:
    """The set of files the client has open. `didClose` means we stop knowing about a file;
    what is on disk is the CLI's business, not the server's."""

    def __init__(self):
        self._by_uri = {}

    def open(self, uri, text, version=0, language_id="python"):
        document = Document(uri, text, version, language_id)
        self._by_uri[uri] = document
        return document

    def update(self, uri, text, version=None):
        document = self._by_uri.get(uri)
        if document is None:
            return self.open(uri, text, version or 0)
        document.replace(text, version)
        return document

    def close(self, uri):
        self._by_uri.pop(uri, None)

    def get(self, uri):
        return self._by_uri.get(uri)

    def __iter__(self):
        return iter(self._by_uri.values())

    def __len__(self):
        return len(self._by_uri)
