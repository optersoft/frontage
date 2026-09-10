"""Cross-origin headers, and the preflight that asks for them.

    app = App(cors=["https://example.com"])      # or ["*"]

A frontage page built to static files and served from somewhere else is the normal case here,
not the exception — `frontage build` writes a directory, and that directory often sits on
Cloudflare Pages while this process is on a VM. So CORS is a constructor argument rather than
a middleware to remember.

The sandboxed runner of the docs is why `*` has to keep working: a frame without
`allow-same-origin` sits in an opaque origin and sends `Origin: null`.
"""

__all__ = ["Cors"]

DEFAULT_HEADERS = "content-type, authorization"


class Cors:
    def __init__(self, origins, methods=None, headers=None, credentials=False, max_age=600):
        self.origins = list(origins)
        self.any = "*" in self.origins
        self.methods = list(methods or ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
        self.headers = headers or DEFAULT_HEADERS
        self.credentials = credentials
        self.max_age = max_age

    def allowed(self, origin):
        if origin is None:
            return None
        if self.any:
            # With credentials, `*` is not a legal answer and the browser refuses it; echo
            # the origin instead, which is what the header actually means here.
            return origin if self.credentials else "*"
        return origin if origin in self.origins else None

    def headers_for(self, origin, preflight=False):
        allow = self.allowed(origin)
        if allow is None:
            return []
        out = [("access-control-allow-origin", allow)]
        if allow != "*":
            # Any answer that varies by origin must say so, or a shared cache serves one
            # site's response to another.
            out.append(("vary", "origin"))
        if self.credentials:
            out.append(("access-control-allow-credentials", "true"))
        if preflight:
            out.append(("access-control-allow-methods", ", ".join(self.methods)))
            out.append(("access-control-allow-headers", self.headers))
            out.append(("access-control-max-age", str(self.max_age)))
        return out
