# typings

Type stubs for the modules that only exist inside the browser: `js` (the JavaScript
global scope), `the runtime's modules
`ty` (see `[tool.ty.environment] extra-paths` in pyproject.toml) and nothing else. Every
name resolves to `Any`, which is honest: the real objects are JavaScript proxies with no
Python type. Nothing here is packaged or shipped.
