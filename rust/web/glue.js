// The JavaScript half of the runtime: the host and bridge imports the wasm needs, the value
// protocol, and a small API to load bytecode and run it. Works in a browser and under node.
//
//   const rt = await load(wasmBytesOrUrl, { stdout, stderr });
//   rt.addModule("frontage.reactive", fbcBytes);
//   rt.run(mainFbcBytes);   // 0 ok, 1 after a traceback on stderr; then the loop is pumped

const decoder = new TextDecoder();
const encoder = new TextEncoder();

// Slot tags (see vm/src/jshooks.rs).
const T_UNDEFINED = 0, T_NULL = 1, T_BOOL = 2, T_NUMBER = 3, T_STRING = 4, T_HANDLE = 5, T_TREE = 6, T_BIGINT = 7, T_PIN = 8;

export async function load(source, options = {}) {
  const stdout = options.stdout || ((s) => console.log(s.replace(/\n$/, "")));
  const stderr = options.stderr || ((s) => console.error(s.replace(/\n$/, "")));
  let memory = null;
  let ex = null;
  const u8 = () => new Uint8Array(memory.buffer);
  const bytes = (ptr, len) => new Uint8Array(memory.buffer, ptr, len);
  const now = typeof performance !== "undefined" ? () => performance.now() : () => Date.now();

  // -- the handle table: 0 is globalThis --------------------------------------------------
  const handles = [globalThis];
  const free = [];
  const hold = (obj) => {
    const i = free.length ? free.pop() : handles.length;
    handles[i] = obj;
    return i;
  };
  const UNDEF_HANDLE = 0xffffffff;
  const proxies = new Map(); // pin → JS function

  // -- slots --------------------------------------------------------------------------------
  const view = () => new DataView(memory.buffer);
  function readSlot(ptr) {
    const v = view();
    return { tag: v.getUint32(ptr, true), aux: v.getUint32(ptr + 4, true), lo: v.getUint32(ptr + 8, true), hi: v.getUint32(ptr + 12, true), f: v.getFloat64(ptr + 8, true) };
  }
  function writeSlot(ptr, tag, aux, payloadWriter) {
    const v = view();
    v.setUint32(ptr, tag, true);
    v.setUint32(ptr + 4, aux, true);
    v.setBigUint64(ptr + 8, 0n, true);
    if (payloadWriter) payloadWriter(v, ptr + 8);
  }
  function decode(s) {
    switch (s.tag) {
      case T_UNDEFINED: return undefined;
      case T_NULL: return null;
      case T_BOOL: return s.lo !== 0;
      case T_NUMBER: return s.f;
      case T_STRING: {
        const len = s.aux & 0x7fffffff;
        const b = bytes(s.lo, len);
        return s.aux & 0x80000000 ? new Uint8Array(b) : decoder.decode(b);
      }
      case T_HANDLE: return s.lo === UNDEF_HANDLE ? undefined : handles[s.lo];
      case T_TREE: return decodeTree(s.lo, s.aux);
      case T_BIGINT: return BigInt.asIntN(64, (BigInt(s.hi) << 32n) | BigInt(s.lo));
      case T_PIN: return proxyFor(s.lo);
      default: return undefined;
    }
  }
  // Write a JavaScript value into a slot the wasm reads.
  function encode(ptr, value) {
    if (value === undefined) return writeSlot(ptr, T_UNDEFINED, 0);
    if (value === null) return writeSlot(ptr, T_NULL, 0);
    const t = typeof value;
    if (t === "boolean") return writeSlot(ptr, T_BOOL, 0, (v, p) => v.setUint32(p, value ? 1 : 0, true));
    if (t === "number") return writeSlot(ptr, T_NUMBER, 0, (v, p) => v.setFloat64(p, value, true));
    if (t === "bigint") return writeSlot(ptr, T_BIGINT, 0, (v, p) => v.setBigInt64(p, value, true));
    if (t === "string") {
      const data = encoder.encode(value);
      const p = ex.alloc(data.length);
      u8().set(data, p);
      return writeSlot(ptr, T_STRING, data.length, (v, q) => v.setUint32(q, p, true));
    }
    return writeSlot(ptr, T_HANDLE, 0, (v, p) => v.setUint32(p, hold(value), true));
  }
  function decodeTree(ptr, len) {
    const v = view();
    let i = ptr;
    const str = () => {
      const n = v.getUint32(i, true);
      i += 4;
      const s = decoder.decode(bytes(i, n));
      i += n;
      return s;
    };
    const one = () => {
      const tag = v.getUint8(i++);
      switch (tag) {
        case 0: return undefined;
        case 1: return v.getUint8(i++) !== 0;
        case 2: { const f = v.getFloat64(i, true); i += 8; return f; }
        case 3: return str();
        case 4: { const h = v.getUint32(i, true); i += 4; return handles[h]; }
        case 5: { const n = v.getUint32(i, true); i += 4; const a = []; for (let k = 0; k < n; k++) a.push(one()); return a; }
        case 6: { const n = v.getUint32(i, true); i += 4; const o = {}; for (let k = 0; k < n; k++) { const key = str(); o[key] = one(); } return o; }
        case 7: { const p = v.getUint32(i, true); i += 4; return proxyFor(p); }
        default: throw new Error("frontage: bad tree tag " + tag);
      }
    };
    const out = one();
    void len;
    return out;
  }
  function readArgs(argv, argc) {
    const out = [];
    for (let k = 0; k < argc; k++) out.push(decode(readSlot(argv + 16 * k)));
    return out;
  }
  const scratch = () => ex.alloc(16);
  function proxyFor(pin) {
    let f = proxies.get(pin);
    if (!f) {
      f = (...args) => callPython(pin, args);
      proxies.set(pin, f);
    }
    return f;
  }
  function callPython(pin, args) {
    const argv = ex.alloc(16 * Math.max(args.length, 1));
    args.forEach((a, k) => encode(argv + 16 * k, a));
    const out = scratch();
    const rc = ex.py_call(pin, argv, args.length, out);
    const slot = readSlot(out);
    const value = decode(slot);
    flushAll();
    pump();
    if (rc !== 0) return undefined;
    return value;
  }
  function fail(out, error) {
    encode(out, error);
    return 1;
  }
  const name = (ptr, len) => decoder.decode(bytes(ptr, len));

  // Line-buffered output.
  const buffers = { 1: "", 2: "" };
  const flush = (fd) => {
    if (buffers[fd]) {
      (fd === 1 ? stdout : stderr)(buffers[fd]);
      buffers[fd] = "";
    }
  };
  const flushAll = () => {
    flush(1);
    flush(2);
  };

  const imports = {
    host: {
      write(fd, ptr, len) {
        buffers[fd] += decoder.decode(bytes(ptr, len));
        if (buffers[fd].endsWith("\n")) flush(fd);
      },
      now_ms: now,
      random: Math.random,
    },
    js: {
      js_get(h, np, nl, out) {
        try {
          const v = handles[h][name(np, nl)];
          encode(out, v);
          if (typeof v === "function") view().setUint32(out + 4, 1, true); // aux 1: a function
          return 0;
        } catch (e) { return fail(out, e); }
      },
      js_set(h, np, nl, val) {
        try { handles[h][name(np, nl)] = decode(readSlot(val)); return 0; } catch (e) { return 1; }
      },
      js_call(h, thisH, argv, argc, out) {
        try {
          const f = handles[h];
          const thisArg = thisH === UNDEF_HANDLE ? undefined : handles[thisH];
          encode(out, Reflect.apply(f, thisArg, readArgs(argv, argc)));
          return 0;
        } catch (e) { return fail(out, e); }
      },
      js_new(h, argv, argc, out) {
        try { encode(out, Reflect.construct(handles[h], readArgs(argv, argc))); return 0; } catch (e) { return fail(out, e); }
      },
      js_index(h, key, out) {
        try { encode(out, handles[h][decode(readSlot(key))]); return 0; } catch (e) { return fail(out, e); }
      },
      js_set_index(h, key, val) {
        try { handles[h][decode(readSlot(key))] = decode(readSlot(val)); return 0; } catch (e) { return 1; }
      },
      js_len(h) {
        const o = handles[h];
        if (o == null) return -1;
        if (typeof o.length === "number") return o.length;
        if (typeof o.size === "number") return o.size;
        return -1;
      },
      js_truthy(h) { return handles[h] ? 1 : 0; },
      js_str(h, out) {
        let s;
        try { s = String(handles[h]); } catch (e) { s = "[object]"; }
        encode(out, s);
      },
      js_kind(h, out) {
        const o = handles[h];
        let k = typeof o;
        if (k === "object") {
          if (Array.isArray(o)) k = "array";
          else if (o instanceof Promise || (o && typeof o.then === "function")) k = "promise";
          else if (o instanceof Error) k = "error";
        }
        encode(out, k);
      },
      js_make_proxy(pin) { return hold(proxyFor(pin)); },
      js_release(h) {
        if (h > 0) {
          handles[h] = undefined;
          free.push(h);
        }
      },
      js_same(a, b) { return handles[a] === handles[b] ? 1 : 0; },
    },
  };
  const result =
    source instanceof Uint8Array || source instanceof ArrayBuffer
      ? await WebAssembly.instantiate(source, imports)
      : await WebAssembly.instantiateStreaming(await fetch(source), imports);
  ex = result.instance.exports;
  memory = ex.memory;

  const put = (data) => {
    const ptr = ex.alloc(data.length);
    u8().set(data, ptr);
    return ptr;
  };
  const putString = (s) => {
    const data = encoder.encode(s);
    return [put(data), data.length];
  };

  // The asyncio loop is driven from here: a turn now, then a timer for the next one.
  let timer = null;
  function pump() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    const wait = ex.loop_turn();
    flushAll();
    if (wait >= 0) timer = setTimeout(pump, wait);
  }

  ex.init();
  return {
    exports: ex,
    memory,
    addModule(name, fbc) {
      const [np, nl] = putString(name);
      const p = put(fbc);
      ex.add_module(np, nl, p, fbc.length);
    },
    /// 0: ran; 1: raised (the traceback went to stderr); 2 + n: `sys.exit(n)`.
    run(fbc) {
      const p = put(fbc);
      const code = ex.run(p, fbc.length);
      flushAll();
      pump();
      return code;
    },
    /// Resolves when the asyncio loop has nothing left to do.
    idle() {
      return new Promise((done) => {
        const check = () => {
          const wait = ex.loop_turn();
          flushAll();
          if (wait < 0) done();
          else setTimeout(check, wait);
        };
        check();
      });
    },
    collect: () => ex.collect(),
    heapLen: () => ex.heap_len(),
    flush: flushAll,
  };
}
