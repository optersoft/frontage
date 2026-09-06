"""The handlers: what the server does when the editor says something.

Full-document sync, and analysis on every change — the whole diagnostics pass is `ast.parse`
plus one walk, which measures at 3 ms on the largest file in this repository and well under
one on the size of file people actually write, so there is nothing here to debounce yet.

One deliberate silence: a syntax error is not reported. Whatever Python language server the
editor already runs says it better, and while someone types, most keystrokes leave the file
briefly unparseable — publishing then would replace the real findings with a red squiggle
that moves around. When the parse fails the last good diagnostics simply stay up.
"""

import os
from urllib.parse import unquote, urlparse

from . import data, features, rules
from .documents import Documents
from .protocol import Connection, serve

SEVERITY = {rules.ERROR: 1, rules.WARNING: 2}


def path_from_uri(uri):
    """The filesystem path behind a `file://` URI, or `None` for anything else."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path


def uri_from_path(path):
    return "file://" + str(path).replace(os.sep, "/")


class Server:
    """One editor session."""

    def __init__(self, connection=None):
        self.connection = connection or Connection()
        self.documents = Documents()
        self.shutting_down = False
        self.handlers = {
            "initialize": self.initialize,
            "initialized": self.initialized,
            "shutdown": self.shutdown,
            "exit": self.exit,
            "textDocument/didOpen": self.did_open,
            "textDocument/didChange": self.did_change,
            "textDocument/didSave": self.did_save,
            "textDocument/didClose": self.did_close,
            "textDocument/completion": self.completion,
            "textDocument/hover": self.hover,
            "textDocument/definition": self.definition,
            "textDocument/semanticTokens/full": self.semantic_tokens,
            "workspace/didChangeConfiguration": self.ignore,
            "workspace/didChangeWatchedFiles": self.ignore,
            "$/setTrace": self.ignore,
            "$/cancelRequest": self.ignore,
        }

    def run(self):
        return serve(self.handlers, self.connection)

    # --- lifecycle ------------------------------------------------------------------------

    def initialize(self, connection, params):
        return {
            "capabilities": {
                "textDocumentSync": {"openClose": True, "change": 1, "save": {"includeText": True}},
                "completionProvider": {"triggerCharacters": ["<", "/", ":", "=", '"', "{"], "resolveProvider": False},
                "hoverProvider": True,
                "definitionProvider": True,
                "semanticTokensProvider": {
                    "legend": {"tokenTypes": features.TOKEN_TYPES, "tokenModifiers": []},
                    "full": True,
                },
            },
            "serverInfo": {"name": "frontage", "version": _version()},
        }

    def initialized(self, connection, params):
        connection.log(f"frontage language server {_version()}, {len(data.TAGS)} elements")
        if not rules.supported():
            # Two of the three rules cannot fire below 3.14, and a server that goes quiet
            # looks broken rather than limited. Say it once, where a person will see it.
            connection.notify(
                "window/showMessage",
                {
                    "type": 2,
                    "message": "frontage: this Python cannot parse template strings. "
                    "Run the server on 3.14 (uvx --python 3.14 frontage lsp) for the template rules.",
                },
            )
        return None

    def shutdown(self, connection, params):
        self.shutting_down = True
        return None

    def exit(self, connection, params):
        return None

    def ignore(self, connection, params):
        return None

    # --- documents ------------------------------------------------------------------------

    def did_open(self, connection, params):
        item = params["textDocument"]
        document = self.documents.open(
            item["uri"], item.get("text", ""), item.get("version", 0), item.get("languageId", "python")
        )
        self.publish(document)
        return None

    def did_change(self, connection, params):
        changes = params.get("contentChanges") or []
        if not changes:
            return None
        # Full sync: the last change carries the whole document.
        document = self.documents.update(
            params["textDocument"]["uri"], changes[-1]["text"], params["textDocument"].get("version")
        )
        self.publish(document)
        return None

    def did_save(self, connection, params):
        text = params.get("text")
        uri = params["textDocument"]["uri"]
        document = self.documents.update(uri, text) if text is not None else self.documents.get(uri)
        if document is not None:
            self.publish(document)
        return None

    def did_close(self, connection, params):
        uri = params["textDocument"]["uri"]
        self.documents.close(uri)
        # Clear what we said about a file we no longer track, or the editor keeps it forever.
        self.connection.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})
        return None

    # --- analysis -------------------------------------------------------------------------

    def publish(self, document):
        path = path_from_uri(document.uri) or document.uri
        if document.language_id == "markdown" or path.endswith(".md"):
            found = rules.findings_in_markdown(document.text, path)
        else:
            found = rules.findings(document.text, path)
        if any(finding.code == "syntax" for finding in found):
            return  # mid-edit; keep the last good diagnostics rather than flashing a parse error
        self.connection.notify(
            "textDocument/publishDiagnostics",
            {
                "uri": document.uri,
                "version": document.version,
                "diagnostics": [self._diagnostic(document, finding) for finding in found],
            },
        )

    def _diagnostic(self, document, finding):
        start = document.offset_of(finding.line, finding.col)
        end = document.offset_of(finding.end_line, finding.end_col)
        return {
            "range": document.range_at(start, max(end, start + 1)),
            "severity": SEVERITY.get(finding.severity, 1),
            "code": finding.code,
            "source": "frontage",
            "message": finding.message,
        }

    # --- requests -------------------------------------------------------------------------

    def _at(self, params):
        document = self.documents.get(params["textDocument"]["uri"])
        if document is None:
            return None, 0
        return document, document.offset_at(params["position"])

    def completion(self, connection, params):
        document, offset = self._at(params)
        if document is None:
            return {"isIncomplete": False, "items": []}
        return {"isIncomplete": False, "items": features.complete(document, offset)}

    def hover(self, connection, params):
        document, offset = self._at(params)
        if document is None:
            return None
        return features.hover(document, offset)

    def definition(self, connection, params):
        document, offset = self._at(params)
        if document is None:
            return None
        return features.definition(document, offset, read_file=self._read_relative)

    def semantic_tokens(self, connection, params):
        document = self.documents.get(params["textDocument"]["uri"])
        if document is None:
            return {"data": []}
        return features.semantic_tokens(document)

    def _read_relative(self, uri, relative):
        """Read a sibling module for go-to-definition, from an open buffer or from disk."""
        base = path_from_uri(uri)
        if base is None:
            return None
        candidate = os.path.normpath(os.path.join(os.path.dirname(base), relative))
        other = uri_from_path(candidate)
        open_document = self.documents.get(other)
        if open_document is not None:
            return other, open_document.text  # the editor's copy wins; it may be unsaved
        try:
            with open(candidate, encoding="utf-8") as handle:
                return other, handle.read()
        except OSError:
            return None


def _version():
    from frontage.version import __version__

    return __version__


def main(argv=None):
    """`python -m frontage lsp`. Speaks the protocol on stdin and stdout; nothing else may
    write to stdout while it runs, which is why every message goes through `window/logMessage`."""
    import argparse

    from ..cli import PROG

    parser = argparse.ArgumentParser(prog=f"{PROG} lsp", description=__doc__)
    parser.add_argument("--stdio", action="store_true", help="speak the protocol on stdin/stdout (the default)")
    parser.parse_args(argv)
    return Server().run()
