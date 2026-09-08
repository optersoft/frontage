//! `.fbc`: a code object as bytes. What `frontage build` writes and the browser loads, so no
//! parser ships in the page.
//!
//! Compact by construction: every integer is a LEB128 varint (an instruction is one opcode
//! byte and one or two bytes of argument), every string in the module — names, variable
//! names, file names, string constants — lives once in a table at the front and is referred
//! to by index, and line tables are deltas. No compression: the transport compresses.

use crate::code::*;
use crate::object::{Obj, PyStr};
use crate::value::Value;
use crate::vm::Vm;
use std::collections::HashMap;
use std::rc::Rc;

pub const MAGIC: &[u8; 4] = b"FBC2";

const C_NONE: u8 = 0;
const C_TRUE: u8 = 1;
const C_FALSE: u8 = 2;
const C_INT: u8 = 3;
const C_FLOAT: u8 = 4;
const C_STR: u8 = 5;
const C_BYTES: u8 = 6;
const C_TUPLE: u8 = 7;
const C_CODE: u8 = 8;
const C_ELLIPSIS: u8 = 9;
const C_UNDEF: u8 = 10;

fn put_uvar(out: &mut Vec<u8>, mut v: u64) {
    loop {
        let b = (v & 0x7f) as u8;
        v >>= 7;
        if v == 0 {
            out.push(b);
            return;
        }
        out.push(b | 0x80);
    }
}
fn put_ivar(out: &mut Vec<u8>, v: i64) {
    put_uvar(out, ((v << 1) ^ (v >> 63)) as u64);
}

struct Writer<'a> {
    vm: &'a Vm,
    out: Vec<u8>,
    strings: Vec<String>,
    index: HashMap<String, u32>,
}

impl<'a> Writer<'a> {
    fn u8(&mut self, v: u8) {
        self.out.push(v);
    }
    fn uv(&mut self, v: u64) {
        put_uvar(&mut self.out, v);
    }
    fn iv(&mut self, v: i64) {
        put_ivar(&mut self.out, v);
    }
    fn f64(&mut self, v: f64) {
        self.out.extend_from_slice(&v.to_le_bytes());
    }
    fn sid(&mut self, s: &str) -> u32 {
        if let Some(&i) = self.index.get(s) {
            return i;
        }
        let i = self.strings.len() as u32;
        self.strings.push(s.to_string());
        self.index.insert(s.to_string(), i);
        i
    }
    fn str(&mut self, s: &str) {
        let i = self.sid(s);
        self.uv(i as u64);
    }
    fn strs(&mut self, vals: &[Value]) {
        self.uv(vals.len() as u64);
        for &v in vals {
            let s = self.vm.as_str(v).unwrap_or("").to_string();
            self.str(&s);
        }
    }
    fn value(&mut self, v: Value, nested: &[Rc<Code>]) -> Result<(), String> {
        if v.is_none() {
            self.u8(C_NONE);
        } else if v.is_bool() {
            self.u8(if v.as_bool() { C_TRUE } else { C_FALSE });
        } else if v.is_int() {
            self.u8(C_INT);
            self.iv(v.as_int() as i64);
        } else if v.is_float() {
            self.u8(C_FLOAT);
            self.f64(v.as_float());
        } else if v.is_undef() {
            self.u8(C_UNDEF);
        } else {
            match self.vm.heap.get(v) {
                Obj::Int(i) => {
                    self.u8(C_INT);
                    self.iv(*i);
                }
                Obj::Str(s) => {
                    self.u8(C_STR);
                    let s = s.s.to_string();
                    self.str(&s);
                }
                Obj::Bytes(b) => {
                    self.u8(C_BYTES);
                    let b = b.clone();
                    self.uv(b.len() as u64);
                    self.out.extend_from_slice(&b);
                }
                Obj::Tuple(items) => {
                    self.u8(C_TUPLE);
                    let items = items.clone();
                    self.uv(items.len() as u64);
                    for it in items {
                        self.value(it, nested)?;
                    }
                }
                Obj::Code(c) => {
                    let idx = nested.iter().position(|n| Rc::ptr_eq(n, c)).ok_or("code constant not among the nested codes")?;
                    self.u8(C_CODE);
                    self.uv(idx as u64);
                }
                Obj::Ellipsis => self.u8(C_ELLIPSIS),
                other => return Err(format!("cannot serialise a constant of kind {}", other.kind())),
            }
        }
        Ok(())
    }
    fn code(&mut self, c: &Code) -> Result<(), String> {
        self.str(&c.name);
        self.str(&c.qualname);
        self.str(&c.filename);
        self.uv(c.firstline as u64);
        self.uv(c.argcount as u64);
        self.uv(c.posonlyargcount as u64);
        self.uv(c.kwonlyargcount as u64);
        self.uv(c.flags as u64);
        self.uv(c.instrs.len() as u64);
        for i in &c.instrs {
            self.u8(i.op as u8);
            self.uv(i.arg as u64);
        }
        self.uv(c.lines.len() as u64);
        let (mut lpc, mut lline) = (0u32, c.firstline);
        for (pc, line) in &c.lines {
            self.uv((*pc - lpc) as u64);
            self.iv(*line as i64 - lline as i64);
            lpc = *pc;
            lline = *line;
        }
        self.uv(c.handlers.len() as u64);
        for h in &c.handlers {
            self.uv(h.start as u64);
            self.uv((h.end - h.start) as u64);
            self.uv(h.target as u64);
            self.uv(h.depth as u64);
            self.uv(h.hdepth as u64);
        }
        self.strs(&c.names);
        self.strs(&c.varnames);
        self.strs(&c.cellvars);
        self.strs(&c.freevars);
        self.uv(c.cell_of_local.len() as u64);
        for (l, cell) in &c.cell_of_local {
            self.uv(*l as u64);
            self.uv(*cell as u64);
        }
        self.uv(c.nested.len() as u64);
        for n in &c.nested {
            self.code(n)?;
        }
        self.uv(c.consts.len() as u64);
        for &v in &c.consts {
            self.value(v, &c.nested)?;
        }
        Ok(())
    }
}

pub fn dump(vm: &Vm, code: &Code) -> Result<Vec<u8>, String> {
    let mut w = Writer { vm, out: Vec::with_capacity(4096), strings: Vec::new(), index: HashMap::new() };
    w.code(code)?;
    let body = core::mem::take(&mut w.out);
    let mut out = Vec::with_capacity(body.len() + 1024);
    out.extend_from_slice(MAGIC);
    put_uvar(&mut out, w.strings.len() as u64);
    for s in &w.strings {
        put_uvar(&mut out, s.len() as u64);
        out.extend_from_slice(s.as_bytes());
    }
    out.extend_from_slice(&body);
    Ok(out)
}

struct Reader<'a> {
    vm: &'a mut Vm,
    b: &'a [u8],
    i: usize,
    /// The string table, as interned or pinned values.
    strings: Vec<Value>,
    texts: Vec<String>,
}

impl<'a> Reader<'a> {
    fn u8(&mut self) -> Result<u8, String> {
        let v = *self.b.get(self.i).ok_or("truncated bytecode")?;
        self.i += 1;
        Ok(v)
    }
    fn uv(&mut self) -> Result<u64, String> {
        let mut v: u64 = 0;
        let mut shift = 0;
        loop {
            let b = self.u8()?;
            v |= ((b & 0x7f) as u64) << shift;
            if b & 0x80 == 0 {
                return Ok(v);
            }
            shift += 7;
            if shift > 63 {
                return Err("bad varint".into());
            }
        }
    }
    fn u32(&mut self) -> Result<u32, String> {
        Ok(self.uv()? as u32)
    }
    fn iv(&mut self) -> Result<i64, String> {
        let u = self.uv()?;
        Ok(((u >> 1) as i64) ^ -((u & 1) as i64))
    }
    fn f64(&mut self) -> Result<f64, String> {
        let s = self.b.get(self.i..self.i + 8).ok_or("truncated bytecode")?;
        self.i += 8;
        let mut a = [0u8; 8];
        a.copy_from_slice(s);
        Ok(f64::from_le_bytes(a))
    }
    fn sval(&mut self) -> Result<Value, String> {
        let i = self.uv()? as usize;
        self.strings.get(i).copied().ok_or_else(|| "bad string index".to_string())
    }
    fn stext(&mut self) -> Result<String, String> {
        let i = self.uv()? as usize;
        self.texts.get(i).cloned().ok_or_else(|| "bad string index".to_string())
    }
    fn svals(&mut self) -> Result<Vec<Value>, String> {
        let n = self.uv()? as usize;
        let mut out = Vec::with_capacity(n);
        for _ in 0..n {
            out.push(self.sval()?);
        }
        Ok(out)
    }
    fn value(&mut self, nested: &[Rc<Code>]) -> Result<Value, String> {
        Ok(match self.u8()? {
            C_NONE => Value::NONE,
            C_TRUE => Value::TRUE,
            C_FALSE => Value::FALSE,
            C_INT => {
                let i = self.iv()?;
                if i >= i32::MIN as i64 && i <= i32::MAX as i64 {
                    Value::int(i as i32)
                } else {
                    self.vm.heap.alloc_pinned(Obj::Int(i))
                }
            }
            C_FLOAT => Value::float(self.f64()?),
            C_STR => self.sval()?,
            C_BYTES => {
                let n = self.uv()? as usize;
                let s = self.b.get(self.i..self.i + n).ok_or("truncated bytecode")?.to_vec();
                self.i += n;
                self.vm.heap.alloc_pinned(Obj::Bytes(s))
            }
            C_TUPLE => {
                let n = self.uv()? as usize;
                let mut items = Vec::with_capacity(n);
                for _ in 0..n {
                    items.push(self.value(nested)?);
                }
                self.vm.heap.alloc_pinned(Obj::Tuple(items))
            }
            C_CODE => {
                let idx = self.uv()? as usize;
                let c = nested.get(idx).ok_or("bad nested code index")?.clone();
                self.vm.heap.alloc_pinned(Obj::Code(c))
            }
            C_ELLIPSIS => {
                let b = self.vm.builtins;
                self.vm.dict_get_str(b, "Ellipsis").unwrap_or(Value::NONE)
            }
            C_UNDEF => Value::UNDEF,
            other => return Err(format!("unknown constant tag {other}")),
        })
    }
    fn code(&mut self) -> Result<Rc<Code>, String> {
        let name = self.stext()?;
        let qualname = self.stext()?;
        let filename = self.stext()?;
        let firstline = self.u32()?;
        let argcount = self.u32()?;
        let posonlyargcount = self.u32()?;
        let kwonlyargcount = self.u32()?;
        let flags = self.u32()?;
        let n = self.uv()? as usize;
        let mut instrs = Vec::with_capacity(n);
        for _ in 0..n {
            let op = self.u8()?;
            if op > Op::RaiseAssert as u8 {
                return Err(format!("unknown opcode {op}"));
            }
            let op: Op = unsafe { core::mem::transmute(op) };
            let arg = self.u32()?;
            instrs.push(Instr { op, arg });
        }
        let n = self.uv()? as usize;
        let mut lines = Vec::with_capacity(n);
        let (mut lpc, mut lline) = (0u32, firstline as i64);
        for _ in 0..n {
            lpc += self.u32()?;
            lline += self.iv()?;
            lines.push((lpc, lline as u32));
        }
        let n = self.uv()? as usize;
        let mut handlers = Vec::with_capacity(n);
        for _ in 0..n {
            let start = self.u32()?;
            let len = self.u32()?;
            handlers.push(Handler { start, end: start + len, target: self.u32()?, depth: self.u32()?, hdepth: self.u32()? });
        }
        let names = self.svals()?;
        let varnames = self.svals()?;
        let cellvars = self.svals()?;
        let freevars = self.svals()?;
        let n = self.uv()? as usize;
        let mut cell_of_local = Vec::with_capacity(n);
        for _ in 0..n {
            cell_of_local.push((self.u32()?, self.u32()?));
        }
        let n = self.uv()? as usize;
        let mut nested = Vec::with_capacity(n);
        for _ in 0..n {
            nested.push(self.code()?);
        }
        let n = self.uv()? as usize;
        let mut consts = Vec::with_capacity(n);
        for _ in 0..n {
            consts.push(self.value(&nested)?);
        }
        Ok(Rc::new(Code {
            name,
            qualname,
            filename: filename.into(),
            firstline,
            instrs,
            lines,
            consts,
            names,
            varnames,
            cellvars,
            freevars,
            cell_of_local,
            argcount,
            posonlyargcount,
            kwonlyargcount,
            flags,
            handlers,
            nested,
            gcache: Default::default(),
        }))
    }
}

pub fn load(vm: &mut Vm, bytes: &[u8]) -> Result<Rc<Code>, String> {
    if bytes.len() < 4 || &bytes[..4] != MAGIC {
        return Err("not frontage bytecode (FBC2)".into());
    }
    let mut r = Reader { vm, b: bytes, i: 4, strings: Vec::new(), texts: Vec::new() };
    let n = r.uv()? as usize;
    for _ in 0..n {
        let len = r.uv()? as usize;
        let s = r.b.get(r.i..r.i + len).ok_or("truncated bytecode")?;
        r.i += len;
        let text = String::from_utf8(s.to_vec()).map_err(|_| "bytecode string is not UTF-8".to_string())?;
        let v = if text.len() <= 40 { r.vm.intern(&text) } else { r.vm.heap.alloc_pinned(Obj::Str(PyStr::from_string(text.clone()))) };
        r.strings.push(v);
        r.texts.push(text);
    }
    r.code()
}
