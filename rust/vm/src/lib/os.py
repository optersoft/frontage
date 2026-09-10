# `os`, as much of it as a runtime with no file system has: the environment, through `_env`.
# The browser's host answers nothing, so `environ` is empty there rather than missing —
# `os.getenv("KEY")` is then None in the page and the key in the server, which is the whole
# point of the module existing on both.
#
# `environ` is a snapshot taken at import, as CPython's is, and a plain dict rather than a
# mapping that writes through to the process.
import _env

name = "posix"
sep = "/"
linesep = "\n"

environ = {}
for _k, _v in _env.all():
    environ[_k] = _v


def getenv(key, default=None):
    return environ.get(key, default)
