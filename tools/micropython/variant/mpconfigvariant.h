// The frontage variant of MicroPython's webassembly port. See FASTER.md §2.
//
// Starts from the `pyscript` variant (full features, the split heap, weakrefs) and switches
// off what no page imports. Every line here was measured on the browser suite before it
// was kept; a module a component needs goes back in, and costs a few KB.

#define MICROPY_CONFIG_ROM_LEVEL                (MICROPY_CONFIG_ROM_LEVEL_FULL_FEATURES)
#define MICROPY_GC_SPLIT_HEAP                   (1)
#define MICROPY_GC_SPLIT_HEAP_AUTO              (1)
#define MICROPY_PY_WEAKREF                      (1)

// C modules nothing in the page imports. `re`, `json`, `binascii`, `random`, `struct`,
// `math` and `collections` stay: the framework, the components or an example uses each.
#define MICROPY_PY_HASHLIB                      (0)
#define MICROPY_PY_DEFLATE                      (0)
#define MICROPY_PY_FRAMEBUF                     (0)
#define MICROPY_PY_UCTYPES                      (0)
#define MICROPY_PY_SELECT                       (0)
#define MICROPY_PY_HEAPQ                        (0)
#define MICROPY_PY_CMATH                        (0)
#define MICROPY_PY_PLATFORM                     (0)
#define MICROPY_PY_MATH_SPECIAL_FUNCTIONS       (0)
#define MICROPY_PY_RANDOM_EXTRA_FUNCS           (0)

// REPL and introspection helpers: a page has no terminal.
#define MICROPY_REPL_EMACS_KEYS                 (0)
#define MICROPY_REPL_AUTO_INDENT                (0)
#define MICROPY_PY_BUILTINS_HELP                (0)
#define MICROPY_PY_BUILTINS_HELP_MODULES        (0)
#define MICROPY_PY_MICROPYTHON_MEM_INFO         (0)
#define MICROPY_PY_BUILTINS_EXECFILE            (0)
