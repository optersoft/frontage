# The frontage variant. See FASTER.md §2 and frontage/cli/micropython.py.
JSFLAGS += -s ALLOW_MEMORY_GROWTH

# Only the port's own asyncio (scheduled on the JavaScript event loop) is frozen in. The
# `pyscript` variant freezes 27 micropython-lib packages on top: 35 KB of gzip nothing in a
# page imports.
FROZEN_MANIFEST ?= $(VARIANT_DIR)/manifest.py

# MicroPython's nlr is setjmp/longjmp. With SUPPORT_LONGJMP=emscripten every call out of a
# function containing a setjmp goes through a JavaScript trampoline; with =wasm it is
# wasm's own exception handling: 3-5x on every call the interpreter makes, and a smaller
# binary. Needs Safari 15.2 / Chrome 95 / Firefox 100. The port hard-codes the emscripten
# spelling in its JSFLAGS after these, so the build script rewrites that one line.
CFLAGS += -sSUPPORT_LONGJMP=wasm
LDFLAGS += -sSUPPORT_LONGJMP=wasm

# Upstream compiles at -Os and links with no optimisation level at all, so Binaryen never
# runs over the whole program and ASSERTIONS stays on. -Oz at the link is a fifth of the
# binary; with wasm exceptions in place, -O2/-O3 measures no faster and costs 20 KB.
LDFLAGS += -Oz
