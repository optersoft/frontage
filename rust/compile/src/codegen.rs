//! Code generation: ruff's AST → the VM's bytecode, one `Code` per scope.

use crate::symtable::{Kind, Sym, SymTable};
use frontage_vm::code::*;
use frontage_vm::dict::PyDict;
use frontage_vm::object::Obj;
use frontage_vm::value::Value;
use frontage_vm::vm::Vm;
use ruff_python_ast as ast;
use ruff_python_ast::{Expr, Stmt};
use ruff_text_size::Ranged;
use std::collections::HashMap;
use std::rc::Rc;

pub type CResult<T = ()> = Result<T, String>;

#[derive(Clone, Copy, PartialEq, Eq)]
struct Label(usize);

#[derive(Clone, Copy)]
enum Slot {
    Fast(u32),
    Name(u32),
}

enum Block<'ast> {
    Loop { is_for: bool, start: Label, end: Label },
    Except { hdepth_before: u32 },
    Finally { body: &'ast [Stmt] },
    With { exit: Slot },
}

#[derive(Hash, PartialEq, Eq)]
enum ConstKey {
    Int(i64),
    Float(u64),
    Str(String),
    None,
    True,
    False,
}

struct Unit<'ast> {
    scope: usize,
    kind: Kind,
    next_child: usize,
    instrs: Vec<Instr>,
    consts: Vec<Value>,
    const_keys: HashMap<ConstKey, u32>,
    names: Vec<Value>,
    name_idx: HashMap<String, u32>,
    varnames: Vec<String>,
    cellvars: Vec<String>,
    freevars: Vec<String>,
    lines: Vec<(u32, u32)>,
    last_line: u32,
    firstline: u32,
    handlers: Vec<Handler>,
    blocks: Vec<Block<'ast>>,
    handling_depth: u32,
    stack_base: u32,
    labels: Vec<Option<u32>>,
    fixups: Vec<(usize, Label)>,
    qualname: String,
    name: String,
    hidden: u32,
    nested: Vec<Rc<Code>>,
    argcount: u32,
    posonly: u32,
    kwonly: u32,
    flags: u32,
    is_generator: bool,
    is_coroutine: bool,
}

pub struct Gen<'a> {
    vm: &'a mut Vm,
    table: &'a SymTable,
    source: &'a str,
    filename: Rc<str>,
    line_starts: Vec<usize>,
}

pub fn generate(vm: &mut Vm, module: &ast::ModModule, table: &SymTable, source: &str, filename: &str) -> Result<Rc<Code>, String> {
    let mut line_starts = vec![0usize];
    for (i, b) in source.bytes().enumerate() {
        if b == b'\n' {
            line_starts.push(i + 1);
        }
    }
    let mut g = Gen { vm, table, source, filename: filename.into(), line_starts };
    let mut unit = g.new_unit(0, "<module>", "<module>", Kind::Module, 1);
    unit.flags |= FLAG_NAMESPACE;
    g.docstring(&mut unit, &module.body);
    g.stmts(&mut unit, &module.body)?;
    g.emit_const(&mut unit, ConstKey::None);
    g.emit(&mut unit, Op::Return, 0);
    g.finish(unit)
}

/// A docstring with its indentation removed, as CPython 3.13 does at compile time
/// (`_PyCompile_CleanDoc`) — the source's indentation belongs to the source, and a reader of
/// `__doc__` should not have to undo it.
///
/// The first line loses *all* its leading spaces and tabs, because it starts right after the
/// quotes and whatever is there is spacing rather than structure. Every line after it loses
/// the *smallest* leading indentation found across the non-blank ones, so relative
/// indentation inside the text survives; a line that is nothing but whitespace does not count
/// towards that minimum but is dedented like any other, which is where the trailing newline
/// of a `"""…\n    """` comes from.
///
/// ⚠ **Indentation is measured in columns with tab stops of eight, not in characters**, and
/// a partly-consumed tab comes back as the spaces it covered. Counting characters agrees with
/// CPython until a docstring mixes tabs and spaces, and then it does not: `"\tb"` under an
/// indent of two is six spaces and a `b`. Found by the differential case, not by reading.
fn clean_doc(text: &str) -> String {
    let Some((first, rest)) = text.split_once('\n') else {
        return text.trim_start_matches([' ', '\t']).to_string();
    };
    let lines: Vec<(usize, &str)> = rest.split('\n').map(split_indent).collect();
    let indent = lines
        .iter()
        .filter(|(_, body)| !body.is_empty())
        .map(|(columns, _)| *columns)
        .min()
        .unwrap_or(0);
    let mut out = String::with_capacity(text.len());
    out.push_str(first.trim_start_matches([' ', '\t']));
    for (columns, body) in lines {
        out.push('\n');
        for _ in 0..columns.saturating_sub(indent) {
            out.push(' ');
        }
        out.push_str(body);
    }
    out
}

/// A line's leading whitespace as columns, and what follows it.
fn split_indent(line: &str) -> (usize, &str) {
    let mut columns = 0;
    let mut at = 0;
    for c in line.chars() {
        match c {
            ' ' => columns += 1,
            '\t' => columns += 8 - (columns % 8),
            _ => break,
        }
        at += c.len_utf8();
    }
    (columns, &line[at..])
}

impl<'a> Gen<'a> {
    fn line_of(&self, offset: usize) -> u32 {
        match self.line_starts.binary_search(&offset) {
            Ok(i) => i as u32 + 1,
            Err(i) => i as u32,
        }
    }

    fn new_unit<'ast>(&mut self, scope: usize, name: &str, qualname: &str, kind: Kind, firstline: u32) -> Unit<'ast> {
        let s = &self.table.scopes[scope];
        let mut u = Unit {
            scope,
            kind,
            next_child: 0,
            instrs: Vec::new(),
            consts: Vec::new(),
            const_keys: HashMap::new(),
            names: Vec::new(),
            name_idx: HashMap::new(),
            varnames: Vec::new(),
            cellvars: s.cellvars.clone(),
            freevars: s.freevars.clone(),
            lines: Vec::new(),
            last_line: 0,
            firstline,
            handlers: Vec::new(),
            blocks: Vec::new(),
            handling_depth: 0,
            stack_base: 0,
            labels: Vec::new(),
            fixups: Vec::new(),
            qualname: qualname.to_string(),
            name: name.to_string(),
            hidden: 0,
            nested: Vec::new(),
            argcount: 0,
            posonly: 0,
            kwonly: 0,
            flags: 0,
            is_generator: s.is_generator,
            is_coroutine: s.is_coroutine,
        };
        if matches!(kind, Kind::Function | Kind::Lambda | Kind::Comprehension) {
            u.varnames = s.params.clone();
        }
        u
    }

    fn finish(&mut self, mut u: Unit) -> Result<Rc<Code>, String> {
        for (at, label) in &u.fixups {
            let target = u.labels[label.0].ok_or_else(|| format!("unbound label in {}", u.qualname))?;
            u.instrs[*at].arg = target;
        }
        let mut flags = u.flags;
        if u.is_generator && u.is_coroutine {
            flags |= FLAG_ASYNC_GENERATOR;
        } else if u.is_generator {
            flags |= FLAG_GENERATOR;
        } else if u.is_coroutine {
            flags |= FLAG_COROUTINE;
        }
        let varnames: Vec<Value> = u.varnames.iter().map(|n| self.vm.intern(n)).collect();
        let cellvars: Vec<Value> = u.cellvars.iter().map(|n| self.vm.intern(n)).collect();
        let freevars: Vec<Value> = u.freevars.iter().map(|n| self.vm.intern(n)).collect();
        let mut cell_of_local = Vec::new();
        for (ci, c) in u.cellvars.iter().enumerate() {
            if let Some(li) = u.varnames.iter().position(|v| v == c) {
                cell_of_local.push((li as u32, ci as u32));
            }
        }
        Ok(Rc::new(Code {
            name: u.name,
            qualname: u.qualname,
            filename: self.filename.clone(),
            firstline: u.firstline,
            instrs: u.instrs,
            lines: u.lines,
            consts: u.consts,
            names: u.names,
            varnames,
            cellvars,
            freevars,
            cell_of_local,
            argcount: u.argcount,
            posonlyargcount: u.posonly,
            kwonlyargcount: u.kwonly,
            flags,
            handlers: u.handlers,
            nested: u.nested,
            gcache: Default::default(),
        }))
    }

    // -- emission helpers ---------------------------------------------------------------------

    fn emit(&mut self, u: &mut Unit, op: Op, arg: u32) {
        u.instrs.push(Instr { op, arg });
    }
    fn label(&mut self, u: &mut Unit) -> Label {
        u.labels.push(None);
        Label(u.labels.len() - 1)
    }
    fn bind(&mut self, u: &mut Unit, l: Label) {
        u.labels[l.0] = Some(u.instrs.len() as u32);
    }
    fn jump(&mut self, u: &mut Unit, op: Op, l: Label) {
        u.fixups.push((u.instrs.len(), l));
        u.instrs.push(Instr { op, arg: 0 });
    }
    fn pc(&self, u: &Unit) -> u32 {
        u.instrs.len() as u32
    }
    fn set_line(&mut self, u: &mut Unit, node: &impl Ranged) {
        let line = self.line_of(node.range().start().to_usize());
        if line != u.last_line {
            u.last_line = line;
            u.lines.push((u.instrs.len() as u32, line));
        }
    }
    fn name_index(&mut self, u: &mut Unit, name: &str) -> u32 {
        if let Some(&i) = u.name_idx.get(name) {
            return i;
        }
        let v = self.vm.intern(name);
        u.names.push(v);
        let i = u.names.len() as u32 - 1;
        u.name_idx.insert(name.to_string(), i);
        i
    }
    fn var_index(&mut self, u: &mut Unit, name: &str) -> u32 {
        if let Some(i) = u.varnames.iter().position(|v| v == name) {
            return i as u32;
        }
        u.varnames.push(name.to_string());
        u.varnames.len() as u32 - 1
    }
    fn cell_index(&self, u: &Unit, name: &str) -> CResult<u32> {
        if let Some(i) = u.cellvars.iter().position(|v| v == name) {
            return Ok(i as u32);
        }
        if let Some(i) = u.freevars.iter().position(|v| v == name) {
            return Ok((u.cellvars.len() + i) as u32);
        }
        Err(format!("internal: no cell for '{name}' in {}", u.qualname))
    }
    fn add_const(&mut self, u: &mut Unit, v: Value) -> u32 {
        u.consts.push(v);
        u.consts.len() as u32 - 1
    }
    fn const_index(&mut self, u: &mut Unit, key: ConstKey) -> u32 {
        if let Some(&i) = u.const_keys.get(&key) {
            return i;
        }
        let v = match &key {
            ConstKey::Int(i) => {
                if *i >= i32::MIN as i64 && *i <= i32::MAX as i64 {
                    Value::int(*i as i32)
                } else {
                    self.vm.heap.alloc_pinned(Obj::Int(*i))
                }
            }
            ConstKey::Float(bits) => Value::float(f64::from_bits(*bits)),
            ConstKey::Str(s) => {
                if s.len() <= 40 {
                    self.vm.intern(s)
                } else {
                    self.vm.heap.alloc_pinned(Obj::Str(frontage_vm::object::PyStr::new(s)))
                }
            }
            ConstKey::None => Value::NONE,
            ConstKey::True => Value::TRUE,
            ConstKey::False => Value::FALSE,
        };
        let i = self.add_const(u, v);
        u.const_keys.insert(key, i);
        i
    }
    fn emit_const(&mut self, u: &mut Unit, key: ConstKey) {
        let i = self.const_index(u, key);
        self.emit(u, Op::LoadConst, i);
    }
    fn emit_str(&mut self, u: &mut Unit, s: &str) {
        self.emit_const(u, ConstKey::Str(s.to_string()));
    }
    fn emit_value_const(&mut self, u: &mut Unit, v: Value) {
        let i = self.add_const(u, v);
        self.emit(u, Op::LoadConst, i);
    }

    fn resolve(&self, u: &Unit, name: &str) -> Sym {
        match self.table.scopes[u.scope].resolved.get(name) {
            Some(s) => *s,
            None => match u.kind {
                Kind::Module | Kind::Class => Sym::Name,
                _ => Sym::Global,
            },
        }
    }
    fn load_name(&mut self, u: &mut Unit, name: &str) -> CResult {
        match self.resolve(u, name) {
            Sym::Local => {
                let i = self.var_index(u, name);
                self.emit(u, Op::LoadFast, i);
            }
            Sym::Cell | Sym::Free => {
                let i = self.cell_index(u, name)?;
                self.emit(u, Op::LoadDeref, i);
            }
            Sym::Global => {
                let i = self.name_index(u, name);
                self.emit(u, Op::LoadGlobal, i);
            }
            Sym::Name => {
                let i = self.name_index(u, name);
                self.emit(u, Op::LoadName, i);
            }
        }
        Ok(())
    }
    fn store_name(&mut self, u: &mut Unit, name: &str) -> CResult {
        match self.resolve(u, name) {
            Sym::Local => {
                let i = self.var_index(u, name);
                self.emit(u, Op::StoreFast, i);
            }
            Sym::Cell | Sym::Free => {
                let i = self.cell_index(u, name)?;
                self.emit(u, Op::StoreDeref, i);
            }
            Sym::Global => {
                let i = self.name_index(u, name);
                self.emit(u, Op::StoreGlobal, i);
            }
            Sym::Name => {
                let i = self.name_index(u, name);
                self.emit(u, Op::StoreName, i);
            }
        }
        Ok(())
    }
    fn delete_name(&mut self, u: &mut Unit, name: &str) -> CResult {
        match self.resolve(u, name) {
            Sym::Local => {
                let i = self.var_index(u, name);
                self.emit(u, Op::DeleteFast, i);
            }
            Sym::Cell | Sym::Free => {
                let i = self.cell_index(u, name)?;
                self.emit_const(u, ConstKey::None);
                self.emit(u, Op::StoreDeref, i);
            }
            Sym::Global => {
                let i = self.name_index(u, name);
                self.emit(u, Op::DeleteGlobal, i);
            }
            Sym::Name => {
                let i = self.name_index(u, name);
                self.emit(u, Op::DeleteName, i);
            }
        }
        Ok(())
    }
    /// A compiler-private slot: a fast local in a function, a namespace name elsewhere.
    fn hidden_slot(&mut self, u: &mut Unit, prefix: &str) -> Slot {
        u.hidden += 1;
        let name = format!(".{prefix}{}", u.hidden);
        if matches!(u.kind, Kind::Function | Kind::Lambda | Kind::Comprehension) {
            Slot::Fast(self.var_index(u, &name))
        } else {
            Slot::Name(self.name_index(u, &name))
        }
    }
    fn load_slot(&mut self, u: &mut Unit, s: Slot) {
        match s {
            Slot::Fast(i) => self.emit(u, Op::LoadFast, i),
            Slot::Name(i) => self.emit(u, Op::LoadName, i),
        }
    }
    fn store_slot(&mut self, u: &mut Unit, s: Slot) {
        match s {
            Slot::Fast(i) => self.emit(u, Op::StoreFast, i),
            Slot::Name(i) => self.emit(u, Op::StoreName, i),
        }
    }

    // -- statements ----------------------------------------------------------------------------

    /// A leading string literal is this unit's docstring: `consts[0]`, plus the flag that
    /// says so.
    ///
    /// Called before anything else in the unit adds a constant, which is what makes the
    /// index 0 — `attr.rs` reads `consts[0]` directly rather than searching, because a
    /// scan per `__doc__` is work on a path that has no reason to do any. The statement
    /// itself is still dropped by `stmt`, so nothing is emitted for it either way.
    fn docstring<'ast>(&mut self, u: &mut Unit<'ast>, body: &'ast [Stmt]) {
        if !self.vm.keep_docstrings {
            return;
        }
        let Some(Stmt::Expr(e)) = body.first() else { return };
        let Expr::StringLiteral(lit) = &*e.value else { return };
        if self.const_index(u, ConstKey::Str(clean_doc(lit.value.to_str()))) == 0 {
            u.flags |= FLAG_DOCSTRING;
        }
    }

    fn stmts<'ast>(&mut self, u: &mut Unit<'ast>, body: &'ast [Stmt]) -> CResult {
        for s in body {
            self.stmt(u, s)?;
        }
        Ok(())
    }

    fn stmt<'ast>(&mut self, u: &mut Unit<'ast>, s: &'ast Stmt) -> CResult {
        self.set_line(u, s);
        match s {
            Stmt::Expr(e) => {
                if matches!(*e.value, Expr::StringLiteral(_) | Expr::NumberLiteral(_) | Expr::NoneLiteral(_) | Expr::EllipsisLiteral(_)) {
                    return Ok(());
                }
                self.expr(u, &e.value)?;
                self.emit(u, Op::Pop, 0);
            }
            Stmt::Assign(a) => {
                self.expr(u, &a.value)?;
                for (i, t) in a.targets.iter().enumerate() {
                    if i + 1 < a.targets.len() {
                        self.emit(u, Op::Dup, 0);
                    }
                    self.assign(u, t)?;
                }
            }
            Stmt::AugAssign(a) => self.aug_assign(u, a)?,
            Stmt::AnnAssign(a) => {
                if let Some(v) = &a.value {
                    self.expr(u, v)?;
                    self.assign(u, &a.target)?;
                }
            }
            Stmt::Return(r) => {
                if !matches!(u.kind, Kind::Function | Kind::Lambda) {
                    return Err("'return' outside function".into());
                }
                match &r.value {
                    Some(v) => self.expr(u, v)?,
                    None => self.emit_const(u, ConstKey::None),
                }
                if u.blocks.is_empty() {
                    self.emit(u, Op::Return, 0);
                } else {
                    let slot = self.hidden_slot(u, "ret");
                    self.store_slot(u, slot);
                    self.unwind_blocks(u, 0, true)?;
                    self.load_slot(u, slot);
                    self.emit(u, Op::Return, 0);
                }
            }
            Stmt::Pass(_) | Stmt::Global(_) | Stmt::Nonlocal(_) | Stmt::TypeAlias(_) | Stmt::IpyEscapeCommand(_) => {}
            Stmt::Break(_) => {
                let target = self.innermost_loop(u).ok_or("'break' outside loop")?;
                self.unwind_blocks(u, target + 1, false)?;
                let (is_for, end) = match &u.blocks[target] {
                    Block::Loop { is_for, end, .. } => (*is_for, *end),
                    _ => unreachable!(),
                };
                if is_for {
                    self.emit(u, Op::Pop, 0);
                }
                self.jump(u, Op::Jump, end);
            }
            Stmt::Continue(_) => {
                let target = self.innermost_loop(u).ok_or("'continue' outside loop")?;
                self.unwind_blocks(u, target + 1, false)?;
                let start = match &u.blocks[target] {
                    Block::Loop { start, .. } => *start,
                    _ => unreachable!(),
                };
                self.jump(u, Op::Jump, start);
            }
            Stmt::If(i) => {
                let end = self.label(u);
                let mut next = self.label(u);
                self.expr(u, &i.test)?;
                self.jump(u, Op::JumpIfFalse, next);
                self.stmts(u, &i.body)?;
                self.jump(u, Op::Jump, end);
                for c in &i.elif_else_clauses {
                    self.bind(u, next);
                    next = self.label(u);
                    if let Some(t) = &c.test {
                        self.set_line(u, c);
                        self.expr(u, t)?;
                        self.jump(u, Op::JumpIfFalse, next);
                    }
                    self.stmts(u, &c.body)?;
                    self.jump(u, Op::Jump, end);
                }
                self.bind(u, next);
                self.bind(u, end);
            }
            Stmt::While(w) => {
                let start = self.label(u);
                let orelse = self.label(u);
                let end = self.label(u);
                self.bind(u, start);
                self.expr(u, &w.test)?;
                self.jump(u, Op::JumpIfFalse, orelse);
                u.blocks.push(Block::Loop { is_for: false, start, end });
                self.stmts(u, &w.body)?;
                u.blocks.pop();
                self.jump(u, Op::Jump, start);
                self.bind(u, orelse);
                self.stmts(u, &w.orelse)?;
                self.bind(u, end);
            }
            Stmt::For(f) => {
                if f.is_async {
                    return self.async_for(u, f);
                }
                let start = self.label(u);
                let orelse = self.label(u);
                let end = self.label(u);
                self.expr(u, &f.iter)?;
                self.emit(u, Op::GetIter, 0);
                self.bind(u, start);
                self.jump(u, Op::ForIter, orelse);
                self.assign(u, &f.target)?;
                u.blocks.push(Block::Loop { is_for: true, start, end });
                u.stack_base += 1;
                self.stmts(u, &f.body)?;
                u.stack_base -= 1;
                u.blocks.pop();
                self.jump(u, Op::Jump, start);
                self.bind(u, orelse);
                self.stmts(u, &f.orelse)?;
                self.bind(u, end);
            }
            Stmt::FunctionDef(f) => {
                self.function_def(u, f)?;
                self.store_name(u, f.name.id.as_str())?;
            }
            Stmt::ClassDef(c) => {
                self.class_def(u, c)?;
                self.store_name(u, c.name.id.as_str())?;
            }
            Stmt::Raise(r) => match (&r.exc, &r.cause) {
                (None, _) => self.emit(u, Op::Raise, 0),
                (Some(e), None) => {
                    self.expr(u, e)?;
                    self.emit(u, Op::Raise, 1);
                }
                (Some(e), Some(c)) => {
                    self.expr(u, e)?;
                    self.expr(u, c)?;
                    self.emit(u, Op::Raise, 2);
                }
            },
            Stmt::Try(t) => self.try_stmt(u, t)?,
            Stmt::With(w) => {
                if w.is_async {
                    return self.async_with(u, w, 0);
                }
                self.with_stmt(u, w, 0)?;
            }
            Stmt::Assert(a) => {
                let end = self.label(u);
                self.expr(u, &a.test)?;
                self.jump(u, Op::JumpIfTrue, end);
                match &a.msg {
                    Some(m) => {
                        self.expr(u, m)?;
                        self.emit(u, Op::RaiseAssert, 1);
                    }
                    None => self.emit(u, Op::RaiseAssert, 0),
                }
                self.bind(u, end);
            }
            Stmt::Delete(d) => {
                for t in &d.targets {
                    self.delete(u, t)?;
                }
            }
            Stmt::Import(i) => {
                for a in &i.names {
                    let full = a.name.id.as_str();
                    self.emit_const(u, ConstKey::Int(0));
                    self.emit_const(u, ConstKey::None);
                    let ni = self.name_index(u, full);
                    self.emit(u, Op::ImportName, ni);
                    match &a.asname {
                        Some(asname) => {
                            for part in full.split('.').skip(1) {
                                let pi = self.name_index(u, part);
                                self.emit(u, Op::LoadAttr, pi);
                            }
                            self.store_name(u, asname.id.as_str())?;
                        }
                        None => {
                            let top = full.split('.').next().unwrap();
                            self.store_name(u, top)?;
                        }
                    }
                }
            }
            Stmt::ImportFrom(i) => {
                let module = i.module.as_ref().map(|m| m.id.to_string()).unwrap_or_default();
                self.emit_const(u, ConstKey::Int(i.level as i64));
                let names: Vec<Value> = i.names.iter().map(|a| self.vm.intern(a.name.id.as_str())).collect();
                let t = self.vm.tuple(names);
                self.vm.heap.pinned.push(t);
                self.emit_value_const(u, t);
                let mi = self.name_index(u, &module);
                self.emit(u, Op::ImportName, mi);
                if i.names.len() == 1 && i.names[0].name.id.as_str() == "*" {
                    self.emit(u, Op::ImportStar, 0);
                } else {
                    for a in &i.names {
                        let ni = self.name_index(u, a.name.id.as_str());
                        self.emit(u, Op::ImportFrom, ni);
                        let bind = a.asname.as_ref().map(|n| n.id.as_str()).unwrap_or(a.name.id.as_str());
                        self.store_name(u, bind)?;
                    }
                    self.emit(u, Op::Pop, 0);
                }
            }
            Stmt::Match(m) => self.match_stmt(u, m)?,
        }
        Ok(())
    }

    fn innermost_loop(&self, u: &Unit) -> Option<usize> {
        u.blocks.iter().rposition(|b| matches!(b, Block::Loop { .. }))
    }

    /// Emit the exits for every block above index `until` (innermost first): pop except
    /// state, run `finally` bodies, call `__exit__`, drop iterators on a `return`.
    fn unwind_blocks<'ast>(&mut self, u: &mut Unit<'ast>, until: usize, returning: bool) -> CResult {
        let mut i = u.blocks.len();
        while i > until {
            i -= 1;
            match &u.blocks[i] {
                Block::Loop { is_for, .. } => {
                    if returning && *is_for {
                        self.emit(u, Op::Pop, 0);
                    }
                }
                Block::Except { hdepth_before } => {
                    let d = *hdepth_before;
                    self.emit(u, Op::PopExcept, d);
                }
                Block::Finally { body } => {
                    let body: &'ast [Stmt] = body;
                    // Compile the finally body as if outside the blocks above and including it.
                    let saved: Vec<Block<'ast>> = u.blocks.drain(i..).collect();
                    let saved_base = u.stack_base;
                    self.stmts(u, body)?;
                    u.stack_base = saved_base;
                    u.blocks.extend(saved);
                }
                Block::With { exit } => {
                    let exit = *exit;
                    self.load_slot(u, exit);
                    self.emit_const(u, ConstKey::None);
                    self.emit_const(u, ConstKey::None);
                    self.emit_const(u, ConstKey::None);
                    self.emit(u, Op::Call, 3);
                    self.emit(u, Op::Pop, 0);
                }
            }
        }
        Ok(())
    }

    fn try_stmt<'ast>(&mut self, u: &mut Unit<'ast>, t: &'ast ast::StmtTry) -> CResult {
        if t.is_star {
            return Err("except* is not supported".into());
        }
        if !t.finalbody.is_empty() {
            // try: [try/except/else] finally: F
            let end = self.label(u);
            let handler = self.label(u);
            let start = self.pc(u);
            u.blocks.push(Block::Finally { body: &t.finalbody });
            if t.handlers.is_empty() {
                self.stmts(u, &t.body)?;
                self.stmts(u, &t.orelse)?;
            } else {
                self.try_except(u, t)?;
            }
            u.blocks.pop();
            let stop = self.pc(u);
            let depth = u.stack_base;
            let hdepth = u.handling_depth;
            // normal path
            self.stmts(u, &t.finalbody)?;
            self.jump(u, Op::Jump, end);
            // exception path
            self.bind(u, handler);
            let target = self.pc(u);
            u.handlers.push(Handler { start, end: stop, target, depth, hdepth });
            u.handling_depth += 1;
            u.blocks.push(Block::Except { hdepth_before: hdepth });
            self.stmts(u, &t.finalbody)?;
            u.blocks.pop();
            u.handling_depth -= 1;
            self.emit(u, Op::Reraise, 0);
            self.bind(u, end);
            return Ok(());
        }
        self.try_except(u, t)
    }

    fn try_except<'ast>(&mut self, u: &mut Unit<'ast>, t: &'ast ast::StmtTry) -> CResult {
        let end = self.label(u);
        let handler = self.label(u);
        let start = self.pc(u);
        self.stmts(u, &t.body)?;
        let stop = self.pc(u);
        self.stmts(u, &t.orelse)?;
        self.jump(u, Op::Jump, end);
        self.bind(u, handler);
        let target = self.pc(u);
        let depth = u.stack_base;
        let hdepth = u.handling_depth;
        u.handlers.push(Handler { start, end: stop, target, depth, hdepth });
        u.handling_depth += 1;
        for h in &t.handlers {
            let ast::ExceptHandler::ExceptHandler(h) = h;
            self.set_line(u, h);
            let next = self.label(u);
            if let Some(ty) = &h.type_ {
                self.expr(u, ty)?;
                self.emit(u, Op::CheckExcMatch, 0);
                self.jump(u, Op::JumpIfFalse, next);
            }
            match &h.name {
                Some(n) => self.store_name(u, n.id.as_str())?,
                None => self.emit(u, Op::Pop, 0),
            }
            u.blocks.push(Block::Except { hdepth_before: hdepth });
            self.stmts(u, &h.body)?;
            u.blocks.pop();
            self.emit(u, Op::PopExcept, hdepth);
            if let Some(n) = &h.name {
                self.emit_const(u, ConstKey::None);
                self.store_name(u, n.id.as_str())?;
                self.delete_name(u, n.id.as_str())?;
            }
            self.jump(u, Op::Jump, end);
            self.bind(u, next);
        }
        u.handling_depth -= 1;
        self.emit(u, Op::Reraise, 0);
        self.bind(u, end);
        Ok(())
    }

    fn with_stmt<'ast>(&mut self, u: &mut Unit<'ast>, w: &'ast ast::StmtWith, index: usize) -> CResult {
        if index >= w.items.len() {
            return self.stmts(u, &w.body);
        }
        let item = &w.items[index];
        let exit = self.hidden_slot(u, "w");
        self.expr(u, &item.context_expr)?;
        self.emit(u, Op::Dup, 0);
        let ei = self.name_index(u, "__exit__");
        self.emit(u, Op::LoadAttr, ei);
        self.store_slot(u, exit);
        let en = self.name_index(u, "__enter__");
        self.emit(u, Op::LoadAttr, en);
        self.emit(u, Op::Call, 0);
        match &item.optional_vars {
            Some(v) => self.assign(u, v)?,
            None => self.emit(u, Op::Pop, 0),
        }
        let end = self.label(u);
        let handler = self.label(u);
        let suppressed = self.label(u);
        let start = self.pc(u);
        u.blocks.push(Block::With { exit });
        self.with_stmt(u, w, index + 1)?;
        u.blocks.pop();
        let stop = self.pc(u);
        let depth = u.stack_base;
        let hdepth = u.handling_depth;
        self.load_slot(u, exit);
        self.emit_const(u, ConstKey::None);
        self.emit_const(u, ConstKey::None);
        self.emit_const(u, ConstKey::None);
        self.emit(u, Op::Call, 3);
        self.emit(u, Op::Pop, 0);
        self.jump(u, Op::Jump, end);
        self.bind(u, handler);
        let target = self.pc(u);
        u.handlers.push(Handler { start, end: stop, target, depth, hdepth });
        self.load_slot(u, exit);
        self.emit(u, Op::Rot2, 0);
        self.jump(u, Op::WithExcept, suppressed);
        self.bind(u, suppressed);
        self.emit(u, Op::PopExcept, hdepth);
        self.bind(u, end);
        Ok(())
    }

    fn async_for<'ast>(&mut self, u: &mut Unit<'ast>, f: &'ast ast::StmtFor) -> CResult {
        // it = aiter(x); while True: try: v = await anext(it) except StopAsyncIteration: break; body
        let start = self.label(u);
        let end = self.label(u);
        let handler = self.label(u);
        self.expr(u, &f.iter)?;
        self.emit(u, Op::GetAIter, 0);
        u.stack_base += 1;
        self.bind(u, start);
        let tstart = self.pc(u);
        self.emit(u, Op::GetANext, 0);
        self.emit_const(u, ConstKey::None);
        self.emit(u, Op::YieldFrom, 0);
        let tstop = self.pc(u);
        self.assign(u, &f.target)?;
        u.blocks.push(Block::Loop { is_for: true, start, end });
        self.stmts(u, &f.body)?;
        u.blocks.pop();
        self.jump(u, Op::Jump, start);
        self.bind(u, handler);
        let target = self.pc(u);
        u.handlers.push(Handler { start: tstart, end: tstop, target, depth: u.stack_base, hdepth: u.handling_depth });
        // stack: iter, exc
        let sai = self.name_index(u, "StopAsyncIteration");
        self.emit(u, Op::LoadGlobal, sai);
        self.emit(u, Op::CheckExcMatch, 0);
        let reraise = self.label(u);
        self.jump(u, Op::JumpIfFalse, reraise);
        self.emit(u, Op::Pop, 0);
        self.emit(u, Op::PopExcept, u.handling_depth);
        self.emit(u, Op::Pop, 0); // the iterator
        u.stack_base -= 1;
        self.stmts(u, &f.orelse)?;
        self.jump(u, Op::Jump, end);
        self.bind(u, reraise);
        self.emit(u, Op::Reraise, 0);
        self.bind(u, end);
        Ok(())
    }

    fn async_with<'ast>(&mut self, u: &mut Unit<'ast>, w: &'ast ast::StmtWith, index: usize) -> CResult {
        if index >= w.items.len() {
            return self.stmts(u, &w.body);
        }
        let item = &w.items[index];
        // exit = ctx.__aexit__; value = await ctx.__aenter__()
        let exit = self.hidden_slot(u, "aw");
        let ctx = self.hidden_slot(u, "actx");
        self.expr(u, &item.context_expr)?;
        self.store_slot(u, ctx);
        self.load_slot(u, ctx);
        let ei = self.name_index(u, "__aexit__");
        self.emit(u, Op::LoadAttr, ei);
        self.store_slot(u, exit);
        self.load_slot(u, ctx);
        let en = self.name_index(u, "__aenter__");
        self.emit(u, Op::LoadAttr, en);
        self.emit(u, Op::Call, 0);
        self.emit(u, Op::GetAwaitable, 0);
        self.emit_const(u, ConstKey::None);
        self.emit(u, Op::YieldFrom, 0);
        match &item.optional_vars {
            Some(v) => self.assign(u, v)?,
            None => self.emit(u, Op::Pop, 0),
        }
        let end = self.label(u);
        let handler = self.label(u);
        let start = self.pc(u);
        self.async_with(u, w, index + 1)?;
        let stop = self.pc(u);
        let depth = u.stack_base;
        let hdepth = u.handling_depth;
        // normal exit: await exit(None, None, None)
        self.load_slot(u, exit);
        self.emit_const(u, ConstKey::None);
        self.emit_const(u, ConstKey::None);
        self.emit_const(u, ConstKey::None);
        self.emit(u, Op::Call, 3);
        self.emit(u, Op::GetAwaitable, 0);
        self.emit_const(u, ConstKey::None);
        self.emit(u, Op::YieldFrom, 0);
        self.emit(u, Op::Pop, 0);
        self.jump(u, Op::Jump, end);
        self.bind(u, handler);
        let target = self.pc(u);
        u.handlers.push(Handler { start, end: stop, target, depth, hdepth });
        // stack: exc → call exit(type(exc), exc, None), await, truthy → suppress
        let e = self.hidden_slot(u, "aexc");
        self.store_slot(u, e);
        self.load_slot(u, exit);
        self.load_slot(u, e);
        let cls = self.name_index(u, "__class__");
        self.emit(u, Op::LoadAttr, cls);
        self.load_slot(u, e);
        self.emit_const(u, ConstKey::None);
        self.emit(u, Op::Call, 3);
        self.emit(u, Op::GetAwaitable, 0);
        self.emit_const(u, ConstKey::None);
        self.emit(u, Op::YieldFrom, 0);
        let suppressed = self.label(u);
        self.jump(u, Op::JumpIfTrue, suppressed);
        self.load_slot(u, e);
        self.emit(u, Op::Reraise, 0);
        self.bind(u, suppressed);
        self.emit(u, Op::PopExcept, hdepth);
        self.bind(u, end);
        Ok(())
    }

    // -- assignment targets ----------------------------------------------------------------------

    fn assign<'ast>(&mut self, u: &mut Unit<'ast>, target: &'ast Expr) -> CResult {
        match target {
            Expr::Name(n) => self.store_name(u, n.id.as_str()),
            Expr::Attribute(a) => {
                self.expr(u, &a.value)?;
                let i = self.name_index(u, a.attr.id.as_str());
                self.emit(u, Op::StoreAttr, i);
                Ok(())
            }
            Expr::Subscript(s) => {
                self.expr(u, &s.value)?;
                self.expr(u, &s.slice)?;
                self.emit(u, Op::StoreSubscr, 0);
                Ok(())
            }
            Expr::Tuple(ast::ExprTuple { elts, .. }) | Expr::List(ast::ExprList { elts, .. }) => {
                let star = elts.iter().position(|e| matches!(e, Expr::Starred(_)));
                match star {
                    None => self.emit(u, Op::UnpackSequence, elts.len() as u32),
                    Some(i) => {
                        let after = elts.len() - i - 1;
                        self.emit(u, Op::UnpackEx, i as u32 | (after as u32) << 16);
                    }
                }
                for e in elts {
                    match e {
                        Expr::Starred(s) => self.assign(u, &s.value)?,
                        other => self.assign(u, other)?,
                    }
                }
                Ok(())
            }
            Expr::Starred(_) => Err("starred assignment target must be in a list or tuple".into()),
            _ => Err(format!("line {}: cannot assign to expression", u.last_line)),
        }
    }

    fn delete<'ast>(&mut self, u: &mut Unit<'ast>, target: &'ast Expr) -> CResult {
        match target {
            Expr::Name(n) => self.delete_name(u, n.id.as_str()),
            Expr::Attribute(a) => {
                self.expr(u, &a.value)?;
                let i = self.name_index(u, a.attr.id.as_str());
                self.emit(u, Op::DeleteAttr, i);
                Ok(())
            }
            Expr::Subscript(s) => {
                self.expr(u, &s.value)?;
                self.expr(u, &s.slice)?;
                self.emit(u, Op::DeleteSubscr, 0);
                Ok(())
            }
            Expr::Tuple(ast::ExprTuple { elts, .. }) | Expr::List(ast::ExprList { elts, .. }) => {
                for e in elts {
                    self.delete(u, e)?;
                }
                Ok(())
            }
            _ => Err("cannot delete expression".into()),
        }
    }

    fn aug_assign<'ast>(&mut self, u: &mut Unit<'ast>, a: &'ast ast::StmtAugAssign) -> CResult {
        let op = binop(a.op);
        match &*a.target {
            Expr::Name(n) => {
                self.load_name(u, n.id.as_str())?;
                self.expr(u, &a.value)?;
                self.emit(u, Op::InplaceOp, op as u32);
                self.store_name(u, n.id.as_str())
            }
            Expr::Attribute(at) => {
                self.expr(u, &at.value)?;
                self.emit(u, Op::Dup, 0);
                let i = self.name_index(u, at.attr.id.as_str());
                self.emit(u, Op::LoadAttr, i);
                self.expr(u, &a.value)?;
                self.emit(u, Op::InplaceOp, op as u32);
                self.emit(u, Op::Rot2, 0);
                self.emit(u, Op::StoreAttr, i);
                Ok(())
            }
            Expr::Subscript(s) => {
                self.expr(u, &s.value)?;
                self.expr(u, &s.slice)?;
                self.emit(u, Op::Dup2, 0);
                self.emit(u, Op::LoadSubscr, 0);
                self.expr(u, &a.value)?;
                self.emit(u, Op::InplaceOp, op as u32);
                self.emit(u, Op::Rot3, 0);
                self.emit(u, Op::StoreSubscr, 0);
                Ok(())
            }
            _ => Err("illegal augmented assignment target".into()),
        }
    }

    // -- functions and classes -----------------------------------------------------------------------

    fn child_scope(&mut self, u: &mut Unit, kind: Kind, what: &str) -> CResult<usize> {
        let s = &self.table.scopes[u.scope];
        let child = *s.children.get(u.next_child).ok_or_else(|| format!("internal: scope order mismatch at {what} in {}", u.qualname))?;
        u.next_child += 1;
        let ck = self.table.scopes[child].kind;
        if ck != Some(kind) {
            return Err(format!("internal: expected {kind:?} scope at {what}, found {ck:?}"));
        }
        Ok(child)
    }

    fn child_qualname(&self, u: &Unit, name: &str) -> String {
        match u.kind {
            Kind::Module => name.to_string(),
            Kind::Class => format!("{}.{}", u.qualname, name),
            _ => format!("{}.<locals>.{}", u.qualname, name),
        }
    }

    fn param_counts(u: &mut Unit, p: &ast::Parameters) {
        u.argcount = (p.posonlyargs.len() + p.args.len()) as u32;
        u.posonly = p.posonlyargs.len() as u32;
        u.kwonly = p.kwonlyargs.len() as u32;
        if p.vararg.is_some() {
            u.flags |= FLAG_VARARGS;
        }
        if p.kwarg.is_some() {
            u.flags |= FLAG_VARKW;
        }
    }

    fn function_def<'ast>(&mut self, u: &mut Unit<'ast>, f: &'ast ast::StmtFunctionDef) -> CResult {
        for d in &f.decorator_list {
            self.expr(u, &d.expression)?;
        }
        // decorator/default lambdas are children before the function's own scope
        let child = {
            // defaults may contain lambdas: they are evaluated inside make_function, but their
            // scopes come first in the table's order (the walker visits defaults first).
            // So look ahead: count child scopes consumed by defaults during expression compile.
            // To keep the order consistent we compile defaults first (in make_function), which
            // consumes their scopes, then take the function scope.
            None::<usize>
        };
        let _ = child;
        let name = f.name.id.as_str();
        let qualname = self.child_qualname(u, name);
        let line = self.line_of(f.range().start().to_usize());
        // Compile defaults now (consuming lambda scopes), then the function scope.
        let mut flags = 0;
        let p = &f.parameters;
        // `__annotations__`, as the **source text** of each annotation rather than its value.
        //
        // This runtime has never evaluated an annotation — `def g(x: Undefined)` does not
        // raise — and storing the text keeps that exactly, so no existing code can start
        // failing. What it buys is a contract something can read: `frontage_api` builds a
        // route's spec from it, and an editor could too. Pushed first, because MakeFunction
        // pops in reverse and this is the deepest of the four.
        let annotations = self.annotation_pairs(f);
        if !annotations.is_empty() {
            for (name, text) in &annotations {
                self.emit_str(u, name);
                self.emit_str(u, text);
            }
            self.emit(u, Op::BuildDict, annotations.len() as u32);
            flags |= 8;
        }
        let defaults: Vec<&Expr> = p.posonlyargs.iter().chain(p.args.iter()).filter_map(|a| a.default.as_deref()).collect();
        if !defaults.is_empty() {
            for d in &defaults {
                self.expr(u, d)?;
            }
            self.emit(u, Op::BuildTuple, defaults.len() as u32);
            flags |= 1;
        }
        let kwdefaults: Vec<(&str, &Expr)> = p.kwonlyargs.iter().filter_map(|a| a.default.as_deref().map(|d| (a.parameter.name.id.as_str(), d))).collect();
        if !kwdefaults.is_empty() {
            for (name, d) in &kwdefaults {
                self.emit_str(u, name);
                self.expr(u, d)?;
            }
            self.emit(u, Op::BuildDict, kwdefaults.len() as u32);
            flags |= 2;
        }
        let child = self.child_scope(u, Kind::Function, name)?;
        let mut cu = self.new_unit(child, name, &qualname, Kind::Function, line);
        Self::param_counts(&mut cu, p);
        self.docstring(&mut cu, &f.body);
        self.stmts(&mut cu, &f.body)?;
        self.emit_const(&mut cu, ConstKey::None);
        self.emit(&mut cu, Op::Return, 0);
        let code = self.finish(cu)?;
        u.nested.push(code.clone());
        self.make_function_tail(u, code, &qualname, child, flags)?;
        for _ in &f.decorator_list {
            self.emit(u, Op::Call, 1);
        }
        Ok(())
    }

    /// `(name, annotation source)` for every annotated parameter, and `"return"` for the
    /// return annotation, in declaration order — which is the order they read in.
    fn annotation_pairs<'ast>(&self, f: &'ast ast::StmtFunctionDef) -> Vec<(String, String)> {
        let p = &f.parameters;
        let mut out = Vec::new();
        let mut push = |name: &str, ann: Option<&Expr>| {
            if let Some(expr) = ann {
                out.push((name.to_string(), self.source[expr.range()].trim().to_string()));
            }
        };
        for a in p.posonlyargs.iter().chain(p.args.iter()) {
            push(a.parameter.name.id.as_str(), a.parameter.annotation.as_deref());
        }
        if let Some(a) = &p.vararg {
            push(a.name.id.as_str(), a.annotation.as_deref());
        }
        for a in p.kwonlyargs.iter() {
            push(a.parameter.name.id.as_str(), a.parameter.annotation.as_deref());
        }
        if let Some(a) = &p.kwarg {
            push(a.name.id.as_str(), a.annotation.as_deref());
        }
        push("return", f.returns.as_deref());
        out
    }

    fn make_function_tail(&mut self, u: &mut Unit, code: Rc<Code>, qualname: &str, child_scope: usize, mut flags: u32) -> CResult {
        let freevars = self.table.scopes[child_scope].freevars.clone();
        if !freevars.is_empty() {
            for fv in &freevars {
                let i = self.cell_index(u, fv)?;
                self.emit(u, Op::LoadClosure, i);
            }
            self.emit(u, Op::BuildTuple, freevars.len() as u32);
            flags |= 4;
        }
        let cv = self.vm.heap.alloc_pinned(Obj::Code(code));
        self.emit_value_const(u, cv);
        let name = qualname.rsplit('.').next().unwrap_or(qualname).to_string();
        self.emit_str(u, &name);
        self.emit(u, Op::MakeFunction, flags);
        Ok(())
    }

    fn lambda<'ast>(&mut self, u: &mut Unit<'ast>, l: &'ast ast::ExprLambda) -> CResult {
        let qualname = self.child_qualname(u, "<lambda>");
        let line = self.line_of(l.range().start().to_usize());
        let mut flags = 0;
        if let Some(p) = &l.parameters {
            let defaults: Vec<&Expr> = p.posonlyargs.iter().chain(p.args.iter()).filter_map(|a| a.default.as_deref()).collect();
            if !defaults.is_empty() {
                for d in &defaults {
                    self.expr(u, d)?;
                }
                self.emit(u, Op::BuildTuple, defaults.len() as u32);
                flags |= 1;
            }
            let kwdefaults: Vec<(&str, &Expr)> = p.kwonlyargs.iter().filter_map(|a| a.default.as_deref().map(|d| (a.parameter.name.id.as_str(), d))).collect();
            if !kwdefaults.is_empty() {
                for (name, d) in &kwdefaults {
                    self.emit_str(u, name);
                    self.expr(u, d)?;
                }
                self.emit(u, Op::BuildDict, kwdefaults.len() as u32);
                flags |= 2;
            }
        }
        let child = self.child_scope(u, Kind::Lambda, "<lambda>")?;
        let mut cu = self.new_unit(child, "<lambda>", &qualname, Kind::Lambda, line);
        if let Some(p) = &l.parameters {
            Self::param_counts(&mut cu, p);
        }
        self.expr(&mut cu, &l.body)?;
        self.emit(&mut cu, Op::Return, 0);
        let code = self.finish(cu)?;
        u.nested.push(code.clone());
        self.make_function_tail(u, code, &qualname, child, flags)
    }

    // -- match statements (PEP 634) ------------------------------------------------------------
    //
    // The subject sits in a hidden slot; each case tests its pattern (falling through on a
    // match, jumping to the next case on a miss), then the guard, then runs its body. The
    // structural tests are four hidden builtins (`__match_seq__`, `__match_map__`,
    // `__match_map_rest__`, `__match_class__`) that answer a list of the sub-values or None,
    // so a nested pattern is the same code over another hidden slot.

    fn match_stmt<'ast>(&mut self, u: &mut Unit<'ast>, m: &'ast ast::StmtMatch) -> CResult {
        self.expr(u, &m.subject)?;
        let subject = self.hidden_slot(u, "m");
        self.store_slot(u, subject);
        let end = self.label(u);
        for case in &m.cases {
            let next = self.label(u);
            self.pattern(u, &case.pattern, subject, next)?;
            if let Some(guard) = &case.guard {
                self.expr(u, guard)?;
                self.jump(u, Op::JumpIfFalse, next);
            }
            self.stmts(u, &case.body)?;
            self.jump(u, Op::Jump, end);
            self.bind(u, next);
        }
        self.bind(u, end);
        Ok(())
    }

    /// `result = helper(...)` into a hidden slot, jumping to `fail` when it is None.
    fn match_helper_result(&mut self, u: &mut Unit, fail: Label) -> Slot {
        let values = self.hidden_slot(u, "mv");
        self.store_slot(u, values);
        self.load_slot(u, values);
        self.emit_const(u, ConstKey::None);
        self.emit(u, Op::IsOp, 0);
        self.jump(u, Op::JumpIfTrue, fail);
        values
    }

    /// `values[i]` into a fresh hidden slot.
    fn match_item(&mut self, u: &mut Unit, values: Slot, i: usize) -> Slot {
        let elem = self.hidden_slot(u, "me");
        self.load_slot(u, values);
        self.emit_const(u, ConstKey::Int(i as i64));
        self.emit(u, Op::LoadSubscr, 0);
        self.store_slot(u, elem);
        elem
    }

    fn pattern<'ast>(&mut self, u: &mut Unit<'ast>, p: &'ast ast::Pattern, subject: Slot, fail: Label) -> CResult {
        match p {
            ast::Pattern::MatchValue(v) => {
                self.load_slot(u, subject);
                self.expr(u, &v.value)?;
                self.emit(u, Op::CompareOp, CmpOp::Eq as u32);
                self.jump(u, Op::JumpIfFalse, fail);
            }
            ast::Pattern::MatchSingleton(s) => {
                self.load_slot(u, subject);
                let key = match s.value {
                    ast::Singleton::None => ConstKey::None,
                    ast::Singleton::True => ConstKey::True,
                    ast::Singleton::False => ConstKey::False,
                };
                self.emit_const(u, key);
                self.emit(u, Op::IsOp, 0);
                self.jump(u, Op::JumpIfFalse, fail);
            }
            ast::Pattern::MatchAs(a) => {
                if let Some(inner) = &a.pattern {
                    self.pattern(u, inner, subject, fail)?;
                }
                if let Some(name) = &a.name {
                    self.load_slot(u, subject);
                    self.store_name(u, name.id.as_str())?;
                }
            }
            ast::Pattern::MatchOr(o) => {
                let ok = self.label(u);
                let last = o.patterns.len().saturating_sub(1);
                for (i, alt) in o.patterns.iter().enumerate() {
                    if i == last {
                        self.pattern(u, alt, subject, fail)?;
                    } else {
                        let alt_fail = self.label(u);
                        self.pattern(u, alt, subject, alt_fail)?;
                        self.jump(u, Op::Jump, ok);
                        self.bind(u, alt_fail);
                    }
                }
                self.bind(u, ok);
            }
            ast::Pattern::MatchStar(_) => return Err(format!("line {}: a star pattern belongs in a sequence pattern", u.last_line)),
            ast::Pattern::MatchSequence(s) => {
                let star = s.patterns.iter().position(|p| matches!(p, ast::Pattern::MatchStar(_)));
                let (before, after) = match star {
                    Some(i) => (i, s.patterns.len() - i - 1),
                    None => (s.patterns.len(), 0),
                };
                self.load_name(u, "__match_seq__")?;
                self.load_slot(u, subject);
                self.emit_const(u, ConstKey::Int(before as i64));
                self.emit_const(u, ConstKey::Int(after as i64));
                self.emit_const(u, if star.is_some() { ConstKey::True } else { ConstKey::False });
                self.emit(u, Op::Call, 4);
                let values = self.match_helper_result(u, fail);
                for (i, sub) in s.patterns.iter().enumerate() {
                    if let ast::Pattern::MatchStar(st) = sub {
                        if let Some(name) = &st.name {
                            let elem = self.match_item(u, values, i);
                            self.load_slot(u, elem);
                            self.store_name(u, name.id.as_str())?;
                        }
                        continue;
                    }
                    let elem = self.match_item(u, values, i);
                    self.pattern(u, sub, elem, fail)?;
                }
            }
            ast::Pattern::MatchMapping(m) => {
                self.load_name(u, "__match_map__")?;
                self.load_slot(u, subject);
                for k in m.keys.iter() {
                    self.expr(u, k)?;
                }
                self.emit(u, Op::BuildTuple, m.keys.len() as u32);
                self.emit(u, Op::Call, 2);
                let values = self.match_helper_result(u, fail);
                for (i, sub) in m.patterns.iter().enumerate() {
                    let elem = self.match_item(u, values, i);
                    self.pattern(u, sub, elem, fail)?;
                }
                if let Some(rest) = &m.rest {
                    self.load_name(u, "__match_map_rest__")?;
                    self.load_slot(u, subject);
                    for k in m.keys.iter() {
                        self.expr(u, k)?;
                    }
                    self.emit(u, Op::BuildTuple, m.keys.len() as u32);
                    self.emit(u, Op::Call, 2);
                    self.store_name(u, rest.id.as_str())?;
                }
            }
            ast::Pattern::MatchClass(c) => {
                let positional = &c.arguments.patterns;
                let keywords = &c.arguments.keywords;
                self.load_name(u, "__match_class__")?;
                self.load_slot(u, subject);
                self.expr(u, &c.cls)?;
                self.emit_const(u, ConstKey::Int(positional.len() as i64));
                for k in keywords {
                    self.emit_str(u, k.attr.id.as_str());
                }
                self.emit(u, Op::BuildTuple, keywords.len() as u32);
                self.emit(u, Op::Call, 4);
                let values = self.match_helper_result(u, fail);
                let subs = positional.iter().chain(keywords.iter().map(|k| &k.pattern));
                for (i, sub) in subs.enumerate() {
                    let elem = self.match_item(u, values, i);
                    self.pattern(u, sub, elem, fail)?;
                }
            }
        }
        Ok(())
    }

    fn class_def<'ast>(&mut self, u: &mut Unit<'ast>, c: &'ast ast::StmtClassDef) -> CResult {
        for d in &c.decorator_list {
            self.expr(u, &d.expression)?;
        }
        let name = c.name.id.as_str();
        let qualname = self.child_qualname(u, name);
        let line = self.line_of(c.range().start().to_usize());
        // bases are evaluated in the enclosing scope, before the body scope
        let mut nbases = 0u32;
        let mut base_exprs: Vec<&Expr> = Vec::new();
        let mut keywords: Vec<(&str, &Expr)> = Vec::new();
        if let Some(a) = &c.arguments {
            for e in a.args.iter() {
                base_exprs.push(e);
            }
            for k in a.keywords.iter() {
                match &k.arg {
                    Some(n) => keywords.push((n.id.as_str(), &k.value)),
                    None => return Err(format!("line {}: `**kwargs` in a class statement is not supported", self.line_of(k.range().start().to_usize()))),
                }
            }
        }
        let child = self.child_scope(u, Kind::Class, name)?;
        let mut cu = self.new_unit(child, name, &qualname, Kind::Class, line);
        cu.flags |= FLAG_NAMESPACE;
        self.stmts(&mut cu, &c.body)?;
        if self.table.scopes[child].cellvars.iter().any(|n| n == "__class__") {
            let i = self.cell_index(&cu, "__class__")?;
            self.emit(&mut cu, Op::LoadClosure, i);
            let cc = self.name_index(&mut cu, "__classcell__");
            self.emit(&mut cu, Op::StoreName, cc);
        }
        self.emit_const(&mut cu, ConstKey::None);
        self.emit(&mut cu, Op::Return, 0);
        let code = self.finish(cu)?;
        u.nested.push(code.clone());
        self.make_function_tail(u, code, &qualname, child, 0)?;
        self.emit_str(u, name);
        for b in base_exprs {
            self.expr(u, b)?;
            nbases += 1;
        }
        // `metaclass=` and the other keywords travel as a dict on top; the flag bit says so.
        if keywords.is_empty() {
            self.emit(u, Op::MakeClass, nbases);
        } else {
            for (name, value) in &keywords {
                self.emit_str(u, name);
                self.expr(u, value)?;
            }
            self.emit(u, Op::BuildDict, keywords.len() as u32);
            self.emit(u, Op::MakeClass, nbases | (1 << 31));
        }
        for _ in &c.decorator_list {
            self.emit(u, Op::Call, 1);
        }
        Ok(())
    }

    fn comprehension<'ast>(&mut self, u: &mut Unit<'ast>, generators: &'ast [ast::Comprehension], kind: CompKind, elt: &'ast Expr, key: Option<&'ast Expr>) -> CResult {
        let name = match kind {
            CompKind::List => "<listcomp>",
            CompKind::Set => "<setcomp>",
            CompKind::Dict => "<dictcomp>",
            CompKind::Gen => "<genexpr>",
        };
        // the outermost iterable, in this scope
        self.expr(u, &generators[0].iter)?;
        self.emit(u, Op::GetIter, 0);
        let qualname = self.child_qualname(u, name);
        let line = self.line_of(elt.range().start().to_usize());
        let child = self.child_scope(u, Kind::Comprehension, name)?;
        let mut cu = self.new_unit(child, name, &qualname, Kind::Comprehension, line);
        cu.argcount = 1;
        let is_gen = kind == CompKind::Gen;
        cu.is_generator = is_gen;
        match kind {
            CompKind::List => self.emit(&mut cu, Op::BuildList, 0),
            CompKind::Set => self.emit(&mut cu, Op::BuildSet, 0),
            CompKind::Dict => self.emit(&mut cu, Op::BuildDict, 0),
            CompKind::Gen => {}
        }
        let mut ends = Vec::new();
        let mut starts = Vec::new();
        for (i, g) in generators.iter().enumerate() {
            if g.is_async {
                return Err("async comprehensions are not supported".into());
            }
            if i == 0 {
                self.emit(&mut cu, Op::LoadFast, 0);
            } else {
                self.expr(&mut cu, &g.iter)?;
                self.emit(&mut cu, Op::GetIter, 0);
            }
            let start = self.label(&mut cu);
            let end = self.label(&mut cu);
            self.bind(&mut cu, start);
            self.jump(&mut cu, Op::ForIter, end);
            self.assign(&mut cu, &g.target)?;
            for cond in &g.ifs {
                self.expr(&mut cu, cond)?;
                self.jump(&mut cu, Op::JumpIfFalse, start);
            }
            cu.stack_base += 1;
            starts.push(start);
            ends.push(end);
        }
        let depth = generators.len() as u32 + 1;
        match kind {
            CompKind::List => {
                self.expr(&mut cu, elt)?;
                self.emit(&mut cu, Op::ListAppend, depth);
            }
            CompKind::Set => {
                self.expr(&mut cu, elt)?;
                self.emit(&mut cu, Op::SetAdd, depth);
            }
            CompKind::Dict => {
                self.expr(&mut cu, key.unwrap())?;
                self.expr(&mut cu, elt)?;
                self.emit(&mut cu, Op::MapAdd, depth);
            }
            CompKind::Gen => {
                self.expr(&mut cu, elt)?;
                self.emit(&mut cu, Op::Yield, 0);
                self.emit(&mut cu, Op::Pop, 0);
            }
        }
        for i in (0..generators.len()).rev() {
            self.jump(&mut cu, Op::Jump, starts[i]);
            self.bind(&mut cu, ends[i]);
            cu.stack_base -= 1;
        }
        if is_gen {
            self.emit_const(&mut cu, ConstKey::None);
        }
        self.emit(&mut cu, Op::Return, 0);
        let code = self.finish(cu)?;
        u.nested.push(code.clone());
        self.make_function_tail(u, code, &qualname, child, 0)?;
        self.emit(u, Op::Rot2, 0);
        self.emit(u, Op::Call, 1);
        Ok(())
    }

    // -- expressions ---------------------------------------------------------------------------------

    fn expr<'ast>(&mut self, u: &mut Unit<'ast>, e: &'ast Expr) -> CResult {
        match e {
            Expr::Name(n) => self.load_name(u, n.id.as_str()),
            Expr::NumberLiteral(n) => {
                match &n.value {
                    ast::Number::Int(i) => match i.as_i64() {
                        Some(v) => self.emit_const(u, ConstKey::Int(v)),
                        None => return Err(format!("line {}: integer literal too large for this runtime (64 bits)", self.line_of(n.range().start().to_usize()))),
                    },
                    ast::Number::Float(f) => self.emit_const(u, ConstKey::Float(f.to_bits())),
                    ast::Number::Complex { .. } => return Err("complex literals are not supported".into()),
                }
                Ok(())
            }
            Expr::StringLiteral(s) => {
                self.emit_str(u, s.value.to_str());
                Ok(())
            }
            Expr::BytesLiteral(b) => {
                let bytes: Vec<u8> = b.value.bytes().collect();
                let v = self.vm.heap.alloc_pinned(Obj::Bytes(bytes));
                self.emit_value_const(u, v);
                Ok(())
            }
            Expr::BooleanLiteral(b) => {
                self.emit_const(u, if b.value { ConstKey::True } else { ConstKey::False });
                Ok(())
            }
            Expr::NoneLiteral(_) => {
                self.emit_const(u, ConstKey::None);
                Ok(())
            }
            Expr::EllipsisLiteral(_) => {
                let b = self.vm.builtins;
                let v = self.vm.dict_get_str(b, "Ellipsis").unwrap_or(Value::NONE);
                self.emit_value_const(u, v);
                Ok(())
            }
            Expr::Attribute(a) => {
                self.expr(u, &a.value)?;
                let i = self.name_index(u, a.attr.id.as_str());
                self.emit(u, Op::LoadAttr, i);
                Ok(())
            }
            Expr::Subscript(s) => {
                self.expr(u, &s.value)?;
                self.expr(u, &s.slice)?;
                self.emit(u, Op::LoadSubscr, 0);
                Ok(())
            }
            Expr::Slice(s) => {
                match &s.lower {
                    Some(v) => self.expr(u, v)?,
                    None => self.emit_const(u, ConstKey::None),
                }
                match &s.upper {
                    Some(v) => self.expr(u, v)?,
                    None => self.emit_const(u, ConstKey::None),
                }
                match &s.step {
                    Some(v) => {
                        self.expr(u, v)?;
                        self.emit(u, Op::BuildSlice, 3);
                    }
                    None => self.emit(u, Op::BuildSlice, 2),
                }
                Ok(())
            }
            Expr::BinOp(b) => {
                self.expr(u, &b.left)?;
                self.expr(u, &b.right)?;
                self.emit(u, Op::BinaryOp, binop(b.op) as u32);
                Ok(())
            }
            Expr::UnaryOp(un) => {
                self.expr(u, &un.operand)?;
                let op = match un.op {
                    ast::UnaryOp::Not => UnOp::Not,
                    ast::UnaryOp::USub => UnOp::Neg,
                    ast::UnaryOp::UAdd => UnOp::Pos,
                    ast::UnaryOp::Invert => UnOp::Invert,
                };
                self.emit(u, Op::UnaryOp, op as u32);
                Ok(())
            }
            Expr::BoolOp(b) => {
                let end = self.label(u);
                let op = if b.op == ast::BoolOp::And { Op::JumpIfFalseOrPop } else { Op::JumpIfTrueOrPop };
                for (i, v) in b.values.iter().enumerate() {
                    self.expr(u, v)?;
                    if i + 1 < b.values.len() {
                        self.jump(u, op, end);
                    }
                }
                self.bind(u, end);
                Ok(())
            }
            Expr::Compare(c) => self.compare(u, c),
            Expr::If(i) => {
                let orelse = self.label(u);
                let end = self.label(u);
                self.expr(u, &i.test)?;
                self.jump(u, Op::JumpIfFalse, orelse);
                self.expr(u, &i.body)?;
                self.jump(u, Op::Jump, end);
                self.bind(u, orelse);
                self.expr(u, &i.orelse)?;
                self.bind(u, end);
                Ok(())
            }
            Expr::Call(c) => self.call(u, c),
            Expr::Lambda(l) => self.lambda(u, l),
            Expr::List(l) => self.sequence(u, &l.elts, Op::BuildList, Op::ListAppend, Op::ListExtend, false),
            Expr::Tuple(t) => self.sequence(u, &t.elts, Op::BuildTuple, Op::ListAppend, Op::ListExtend, true),
            Expr::Set(s) => self.sequence(u, &s.elts, Op::BuildSet, Op::SetAdd, Op::SetUpdate, false),
            Expr::Dict(d) => {
                let has_splat = d.items.iter().any(|i| i.key.is_none());
                if !has_splat {
                    for item in &d.items {
                        self.expr(u, item.key.as_ref().unwrap())?;
                        self.expr(u, &item.value)?;
                    }
                    self.emit(u, Op::BuildDict, d.items.len() as u32);
                    return Ok(());
                }
                self.emit(u, Op::BuildDict, 0);
                for item in &d.items {
                    match &item.key {
                        Some(k) => {
                            self.expr(u, k)?;
                            self.expr(u, &item.value)?;
                            self.emit(u, Op::MapAdd, 1);
                        }
                        None => {
                            self.expr(u, &item.value)?;
                            self.emit(u, Op::DictUpdate, 1);
                        }
                    }
                }
                Ok(())
            }
            Expr::ListComp(c) => self.comprehension(u, &c.generators, CompKind::List, &c.elt, None),
            Expr::SetComp(c) => self.comprehension(u, &c.generators, CompKind::Set, &c.elt, None),
            Expr::DictComp(c) => {
                let key: &Expr = c.key.as_deref().unwrap_or(&c.value);
                self.comprehension(u, &c.generators, CompKind::Dict, &c.value, Some(key))
            }
            Expr::Generator(g) => self.comprehension(u, &g.generators, CompKind::Gen, &g.elt, None),
            Expr::Await(a) => {
                self.expr(u, &a.value)?;
                self.emit(u, Op::GetAwaitable, 0);
                self.emit_const(u, ConstKey::None);
                self.emit(u, Op::YieldFrom, 0);
                Ok(())
            }
            Expr::Yield(y) => {
                match &y.value {
                    Some(v) => self.expr(u, v)?,
                    None => self.emit_const(u, ConstKey::None),
                }
                self.emit(u, Op::Yield, 0);
                Ok(())
            }
            Expr::YieldFrom(y) => {
                self.expr(u, &y.value)?;
                self.emit(u, Op::GetIter, 0);
                self.emit_const(u, ConstKey::None);
                self.emit(u, Op::YieldFrom, 0);
                Ok(())
            }
            Expr::Named(n) => {
                self.expr(u, &n.value)?;
                self.emit(u, Op::Dup, 0);
                self.assign(u, &n.target)
            }
            Expr::Starred(_) => Err(format!("line {}: can't use starred expression here", u.last_line)),
            Expr::FString(f) => self.fstring(u, f),
            Expr::TString(t) => self.tstring(u, t),
            Expr::IpyEscapeCommand(_) => Err("IPython escapes are not Python".into()),
        }
    }

    fn sequence<'ast>(&mut self, u: &mut Unit<'ast>, elts: &'ast [Expr], build: Op, append: Op, extend: Op, tuple: bool) -> CResult {
        let has_star = elts.iter().any(|e| matches!(e, Expr::Starred(_)));
        if !has_star {
            for e in elts {
                self.expr(u, e)?;
            }
            self.emit(u, build, elts.len() as u32);
            return Ok(());
        }
        self.emit(u, if tuple { Op::BuildList } else { build }, 0);
        for e in elts {
            match e {
                Expr::Starred(s) => {
                    self.expr(u, &s.value)?;
                    self.emit(u, extend, 1);
                }
                other => {
                    self.expr(u, other)?;
                    self.emit(u, append, 1);
                }
            }
        }
        if tuple {
            self.emit(u, Op::ListToTuple, 0);
        }
        Ok(())
    }

    fn compare<'ast>(&mut self, u: &mut Unit<'ast>, c: &'ast ast::ExprCompare) -> CResult {
        self.expr(u, &c.left)?;
        if c.ops.len() == 1 {
            self.expr(u, &c.comparators[0])?;
            self.emit_cmp(u, c.ops[0]);
            return Ok(());
        }
        let cleanup = self.label(u);
        let end = self.label(u);
        for (i, (op, right)) in c.ops.iter().zip(c.comparators.iter()).enumerate() {
            self.expr(u, right)?;
            if i + 1 < c.ops.len() {
                self.emit(u, Op::Dup, 0);
                self.emit(u, Op::Rot3, 0);
                self.emit_cmp(u, *op);
                self.jump(u, Op::JumpIfFalseOrPop, cleanup);
            } else {
                self.emit_cmp(u, *op);
            }
        }
        self.jump(u, Op::Jump, end);
        self.bind(u, cleanup);
        self.emit(u, Op::Rot2, 0);
        self.emit(u, Op::Pop, 0);
        self.bind(u, end);
        Ok(())
    }

    fn emit_cmp(&mut self, u: &mut Unit, op: ast::CmpOp) {
        match op {
            ast::CmpOp::Eq => self.emit(u, Op::CompareOp, CmpOp::Eq as u32),
            ast::CmpOp::NotEq => self.emit(u, Op::CompareOp, CmpOp::Ne as u32),
            ast::CmpOp::Lt => self.emit(u, Op::CompareOp, CmpOp::Lt as u32),
            ast::CmpOp::LtE => self.emit(u, Op::CompareOp, CmpOp::Le as u32),
            ast::CmpOp::Gt => self.emit(u, Op::CompareOp, CmpOp::Gt as u32),
            ast::CmpOp::GtE => self.emit(u, Op::CompareOp, CmpOp::Ge as u32),
            ast::CmpOp::Is => self.emit(u, Op::IsOp, 0),
            ast::CmpOp::IsNot => self.emit(u, Op::IsOp, 1),
            ast::CmpOp::In => self.emit(u, Op::ContainsOp, 0),
            ast::CmpOp::NotIn => self.emit(u, Op::ContainsOp, 1),
        }
    }

    fn call<'ast>(&mut self, u: &mut Unit<'ast>, c: &'ast ast::ExprCall) -> CResult {
        // zero-argument super() → super(__class__, <first arg>)
        if let Expr::Name(n) = &*c.func {
            if n.id.as_str() == "super" && c.arguments.args.is_empty() && c.arguments.keywords.is_empty() {
                self.load_name(u, "super")?;
                self.load_name(u, "__class__")?;
                if u.varnames.is_empty() {
                    return Err(format!("line {}: super(): no arguments", u.last_line));
                }
                let first = u.varnames[0].clone();
                // the first parameter may itself be a cell
                self.load_name(u, &first)?;
                self.emit(u, Op::Call, 2);
                return Ok(());
            }
        }
        let args = &c.arguments;
        let has_star = args.args.iter().any(|a| matches!(a, Expr::Starred(_)));
        let has_kwsplat = args.keywords.iter().any(|k| k.arg.is_none());
        // `obj.name(a, b)`: the method and its receiver, no bound-method object.
        if let Expr::Attribute(a) = &*c.func {
            if !has_star && args.keywords.is_empty() {
                self.expr(u, &a.value)?;
                let i = self.name_index(u, a.attr.id.as_str());
                self.emit(u, Op::LoadMethod, i);
                for arg in args.args.iter() {
                    self.expr(u, arg)?;
                }
                self.emit(u, Op::CallMethod, args.args.len() as u32);
                return Ok(());
            }
        }
        self.expr(u, &c.func)?;
        if !has_star && !has_kwsplat {
            for a in args.args.iter() {
                self.expr(u, a)?;
            }
            if args.keywords.is_empty() {
                self.emit(u, Op::Call, args.args.len() as u32);
                return Ok(());
            }
            let mut names = Vec::with_capacity(args.keywords.len());
            for k in args.keywords.iter() {
                self.expr(u, &k.value)?;
                names.push(self.vm.intern(k.arg.as_ref().unwrap().id.as_str()));
            }
            let t = self.vm.tuple(names);
            self.vm.heap.pinned.push(t);
            self.emit_value_const(u, t);
            self.emit(u, Op::CallKw, (args.args.len() + args.keywords.len()) as u32);
            return Ok(());
        }
        // *args / **kwargs: build a tuple and a dict
        self.emit(u, Op::BuildList, 0);
        for a in args.args.iter() {
            match a {
                Expr::Starred(s) => {
                    self.expr(u, &s.value)?;
                    self.emit(u, Op::ListExtend, 1);
                }
                other => {
                    self.expr(u, other)?;
                    self.emit(u, Op::ListAppend, 1);
                }
            }
        }
        self.emit(u, Op::ListToTuple, 0);
        let has_kw = !args.keywords.is_empty();
        if has_kw {
            self.emit(u, Op::BuildDict, 0);
            for k in args.keywords.iter() {
                match &k.arg {
                    Some(name) => {
                        self.emit_str(u, name.id.as_str());
                        self.expr(u, &k.value)?;
                        self.emit(u, Op::MapAdd, 1);
                    }
                    None => {
                        self.expr(u, &k.value)?;
                        self.emit(u, Op::DictUpdate, 1);
                    }
                }
            }
        }
        self.emit(u, Op::CallEx, has_kw as u32);
        Ok(())
    }

    fn fstring<'ast>(&mut self, u: &mut Unit<'ast>, f: &'ast ast::ExprFString) -> CResult {
        let mut n = 0u32;
        for part in f.value.iter() {
            match part {
                ast::FStringPart::Literal(s) => {
                    self.emit_str(u, &s.value);
                    n += 1;
                }
                ast::FStringPart::FString(fs) => {
                    n += self.interpolated_elements(u, &fs.elements)?;
                }
            }
        }
        if n != 1 {
            self.emit(u, Op::BuildString, n);
        }
        Ok(())
    }

    /// Emit each element as a string on the stack; returns how many were pushed.
    fn interpolated_elements<'ast>(&mut self, u: &mut Unit<'ast>, elements: &'ast ast::InterpolatedStringElements) -> CResult<u32> {
        let mut n = 0;
        for el in elements.iter() {
            match el {
                ast::InterpolatedStringElement::Literal(l) => {
                    self.emit_str(u, &l.value);
                    n += 1;
                }
                ast::InterpolatedStringElement::Interpolation(i) => {
                    let mut conv = match i.conversion {
                        ast::ConversionFlag::None => 0,
                        ast::ConversionFlag::Str => 1,
                        ast::ConversionFlag::Repr => 2,
                        ast::ConversionFlag::Ascii => 3,
                    };
                    if let Some(dbg) = &i.debug_text {
                        // `{x=}` → the text "x=" then repr (unless a conversion or spec is given)
                        let text = format!("{}{}{}", dbg.leading(), &self.source[i.expression.range()], dbg.trailing());
                        self.emit_str(u, &text);
                        n += 1;
                        if conv == 0 && i.format_spec.is_none() {
                            conv = 2;
                        }
                    }
                    self.expr(u, &i.expression)?;
                    let mut flags = conv;
                    if let Some(spec) = &i.format_spec {
                        let k = self.interpolated_elements(u, &spec.elements)?;
                        if k != 1 {
                            self.emit(u, Op::BuildString, k);
                        }
                        flags |= 4;
                    }
                    self.emit(u, Op::FormatValue, flags);
                    n += 1;
                }
            }
        }
        Ok(n)
    }

    fn tstring<'ast>(&mut self, u: &mut Unit<'ast>, t: &'ast ast::ExprTString) -> CResult {
        // strings: literal runs between interpolations, across implicit concatenation
        let mut strings: Vec<String> = vec![String::new()];
        let mut interps: Vec<&'ast ast::InterpolatedElement> = Vec::new();
        for ts in t.value.iter() {
            for el in ts.elements.iter() {
                match el {
                    ast::InterpolatedStringElement::Literal(l) => strings.last_mut().unwrap().push_str(&l.value),
                    ast::InterpolatedStringElement::Interpolation(i) => {
                        if let Some(dbg) = &i.debug_text {
                            let text = format!("{}{}{}", dbg.leading(), &self.source[i.expression.range()], dbg.trailing());
                            strings.last_mut().unwrap().push_str(&text);
                        }
                        interps.push(i);
                        strings.push(String::new());
                    }
                }
            }
        }
        let svals: Vec<Value> = strings.iter().map(|s| self.vm.intern(s)).collect();
        let tuple = self.vm.tuple(svals);
        self.vm.heap.pinned.push(tuple);
        self.emit_value_const(u, tuple);
        for i in &interps {
            let text = self.source[i.expression.range()].to_string();
            let text = match &i.debug_text {
                Some(_) => text,
                None => text,
            };
            self.emit_str(u, text.trim());
            self.expr(u, &i.expression)?;
            let mut conv = match i.conversion {
                ast::ConversionFlag::None => 0,
                ast::ConversionFlag::Str => 1,
                ast::ConversionFlag::Repr => 2,
                ast::ConversionFlag::Ascii => 3,
            };
            if i.debug_text.is_some() && conv == 0 && i.format_spec.is_none() {
                conv = 2;
            }
            let mut flags = conv;
            if let Some(spec) = &i.format_spec {
                let k = self.interpolated_elements(u, &spec.elements)?;
                if k != 1 {
                    self.emit(u, Op::BuildString, k);
                }
                flags |= 4;
            }
            self.emit(u, Op::BuildInterpolation, flags);
        }
        self.emit(u, Op::BuildTemplate, interps.len() as u32);
        Ok(())
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum CompKind {
    List,
    Set,
    Dict,
    Gen,
}

fn binop(op: ast::Operator) -> BinOp {
    match op {
        ast::Operator::Add => BinOp::Add,
        ast::Operator::Sub => BinOp::Sub,
        ast::Operator::Mult => BinOp::Mul,
        ast::Operator::MatMult => BinOp::MatMul,
        ast::Operator::Div => BinOp::TrueDiv,
        ast::Operator::Mod => BinOp::Mod,
        ast::Operator::Pow => BinOp::Pow,
        ast::Operator::LShift => BinOp::LShift,
        ast::Operator::RShift => BinOp::RShift,
        ast::Operator::BitOr => BinOp::Or,
        ast::Operator::BitXor => BinOp::Xor,
        ast::Operator::BitAnd => BinOp::And,
        ast::Operator::FloorDiv => BinOp::FloorDiv,
    }
}

#[allow(dead_code)]
fn unused(_: PyDict) {}
