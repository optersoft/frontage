//! Scopes and name resolution: which names are fast locals, cells, free variables, globals
//! or namespace lookups. Two passes over the tree — collect, then resolve — in the same
//! traversal order the code generator uses, so a nested scope is found by position.

use ruff_python_ast as ast;
use ruff_python_ast::{Expr, Stmt};
use std::collections::{HashMap, HashSet};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Module,
    Class,
    Function,
    Lambda,
    Comprehension,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Sym {
    /// A fast local slot.
    Local,
    /// A local captured by a nested scope: lives in a cell.
    Cell,
    /// Defined in an enclosing function scope: read through the closure.
    Free,
    /// `global` declared, or implicitly global in a function.
    Global,
    /// Module and class bodies: the namespace dict.
    Name,
}

#[derive(Default, Debug)]
pub struct Scope {
    pub kind: Option<Kind>,
    pub name: String,
    pub parent: Option<usize>,
    pub children: Vec<usize>,
    /// Parameters, in `varnames` order: positional, keyword-only, *args, **kwargs.
    pub params: Vec<String>,
    /// Names bound in this scope (assignment, def, import, for, with, except, params).
    pub bound: Vec<String>,
    bound_set: HashSet<String>,
    pub used: Vec<String>,
    used_set: HashSet<String>,
    pub globals: HashSet<String>,
    pub nonlocals: HashSet<String>,
    pub is_generator: bool,
    pub is_coroutine: bool,
    /// The body mentions `super` or `__class__`.
    pub uses_class_cell: bool,
    pub resolved: HashMap<String, Sym>,
    pub cellvars: Vec<String>,
    pub freevars: Vec<String>,
}

impl Scope {
    fn bind(&mut self, name: &str) {
        if self.bound_set.insert(name.to_string()) {
            self.bound.push(name.to_string());
        }
    }
    fn use_(&mut self, name: &str) {
        if self.used_set.insert(name.to_string()) {
            self.used.push(name.to_string());
        }
    }
    pub fn is_bound(&self, name: &str) -> bool {
        self.bound_set.contains(name)
    }
    pub fn is_function_like(&self) -> bool {
        matches!(self.kind, Some(Kind::Function | Kind::Lambda | Kind::Comprehension))
    }
}

pub struct SymTable {
    pub scopes: Vec<Scope>,
}

impl SymTable {
    pub fn build(module: &ast::ModModule) -> SymTable {
        let mut t = SymTable { scopes: Vec::new() };
        let root = t.push(Kind::Module, "<module>", None);
        let mut w = Walker { t: &mut t, cur: root };
        w.stmts(&module.body);
        t.resolve_all();
        t
    }

    fn push(&mut self, kind: Kind, name: &str, parent: Option<usize>) -> usize {
        let i = self.scopes.len();
        self.scopes.push(Scope { kind: Some(kind), name: name.to_string(), parent, ..Default::default() });
        if let Some(p) = parent {
            self.scopes[p].children.push(i);
        }
        i
    }

    fn resolve_all(&mut self) {
        // Resolve parents before children: a child's free variable marks the parent's cell.
        for i in 0..self.scopes.len() {
            self.resolve(i);
        }
        // `__class__` cells: a method that uses super() reads the enclosing class's cell.
        for i in 0..self.scopes.len() {
            if self.scopes[i].uses_class_cell && self.scopes[i].is_function_like() {
                // find the nearest enclosing class
                let mut p = self.scopes[i].parent;
                let mut path = vec![i];
                let mut class = None;
                while let Some(pi) = p {
                    if self.scopes[pi].kind == Some(Kind::Class) {
                        class = Some(pi);
                        break;
                    }
                    path.push(pi);
                    p = self.scopes[pi].parent;
                }
                if let Some(c) = class {
                    if !self.scopes[c].cellvars.iter().any(|n| n == "__class__") {
                        self.scopes[c].cellvars.push("__class__".into());
                    }
                    for s in path {
                        if !self.scopes[s].freevars.iter().any(|n| n == "__class__") {
                            self.scopes[s].freevars.push("__class__".into());
                            self.scopes[s].resolved.insert("__class__".into(), Sym::Free);
                        }
                    }
                }
            }
        }
    }

    fn resolve(&mut self, i: usize) {
        let kind = self.scopes[i].kind.unwrap();
        let names: Vec<String> = {
            let s = &self.scopes[i];
            let mut v = s.bound.clone();
            for u in &s.used {
                if !s.bound_set.contains(u) {
                    v.push(u.clone());
                }
            }
            for g in &s.globals {
                if !v.contains(g) {
                    v.push(g.clone());
                }
            }
            for n in &s.nonlocals {
                if !v.contains(n) {
                    v.push(n.clone());
                }
            }
            v
        };
        for name in names {
            let sym = self.classify(i, &name, kind);
            self.scopes[i].resolved.insert(name, sym);
        }
    }

    fn classify(&mut self, i: usize, name: &str, kind: Kind) -> Sym {
        if self.scopes[i].globals.contains(name) {
            return Sym::Global;
        }
        if self.scopes[i].nonlocals.contains(name) {
            return self.capture(i, name);
        }
        match kind {
            Kind::Module => Sym::Name,
            Kind::Class => {
                if self.scopes[i].is_bound(name) {
                    Sym::Name
                } else if self.enclosing_function_binds(i, name) {
                    self.capture(i, name)
                } else {
                    Sym::Name
                }
            }
            _ => {
                if self.scopes[i].is_bound(name) {
                    Sym::Local
                } else if self.enclosing_function_binds(i, name) {
                    self.capture(i, name)
                } else {
                    Sym::Global
                }
            }
        }
    }

    fn enclosing_function_binds(&self, i: usize, name: &str) -> bool {
        let mut p = self.scopes[i].parent;
        while let Some(pi) = p {
            let s = &self.scopes[pi];
            if s.is_function_like() && (s.is_bound(name) || s.nonlocals.contains(name)) && !s.globals.contains(name) {
                return true;
            }
            if s.is_function_like() && s.freevars.iter().any(|n| n == name) {
                return true;
            }
            p = s.parent;
        }
        false
    }

    /// Make `name` free in scope `i`, a cell where it is bound, and free in every function
    /// scope between.
    fn capture(&mut self, i: usize, name: &str) -> Sym {
        let mut chain = vec![];
        let mut p = self.scopes[i].parent;
        let mut owner = None;
        while let Some(pi) = p {
            let s = &self.scopes[pi];
            if s.is_function_like() && s.is_bound(name) && !s.globals.contains(name) && !s.nonlocals.contains(name) {
                owner = Some(pi);
                break;
            }
            if s.is_function_like() && (s.freevars.iter().any(|n| n == name) || s.nonlocals.contains(name)) {
                // Already free there: the owner is further up; keep walking to mark the chain.
                chain.push(pi);
                p = s.parent;
                continue;
            }
            chain.push(pi);
            p = s.parent;
        }
        if let Some(o) = owner {
            if !self.scopes[o].cellvars.iter().any(|n| n == name) {
                self.scopes[o].cellvars.push(name.to_string());
            }
            self.scopes[o].resolved.insert(name.to_string(), Sym::Cell);
            for c in chain {
                if self.scopes[c].is_function_like() || self.scopes[c].kind == Some(Kind::Class) {
                    if !self.scopes[c].freevars.iter().any(|n| n == name) {
                        self.scopes[c].freevars.push(name.to_string());
                    }
                    self.scopes[c].resolved.insert(name.to_string(), Sym::Free);
                }
            }
            if !self.scopes[i].freevars.iter().any(|n| n == name) {
                self.scopes[i].freevars.push(name.to_string());
            }
            Sym::Free
        } else {
            // `nonlocal` with no binding, or a lookup that reaches the module.
            Sym::Global
        }
    }
}

struct Walker<'a> {
    t: &'a mut SymTable,
    cur: usize,
}

impl<'a> Walker<'a> {
    fn scope(&mut self) -> &mut Scope {
        &mut self.t.scopes[self.cur]
    }
    fn stmts(&mut self, body: &[Stmt]) {
        for s in body {
            self.stmt(s);
        }
    }
    fn params(&mut self, p: &ast::Parameters) {
        // defaults evaluate in the enclosing scope, before the function scope exists
        for a in p.posonlyargs.iter().chain(p.args.iter()).chain(p.kwonlyargs.iter()) {
            if let Some(d) = &a.default {
                self.expr(d);
            }
        }
    }
    fn bind_params(&mut self, p: &ast::Parameters) {
        let mut names = Vec::new();
        for a in p.posonlyargs.iter().chain(p.args.iter()) {
            names.push(a.parameter.name.id.to_string());
        }
        for a in p.kwonlyargs.iter() {
            names.push(a.parameter.name.id.to_string());
        }
        if let Some(v) = &p.vararg {
            names.push(v.name.id.to_string());
        }
        if let Some(k) = &p.kwarg {
            names.push(k.name.id.to_string());
        }
        for n in &names {
            self.scope().bind(n);
        }
        self.scope().params = names;
    }
    fn stmt(&mut self, s: &Stmt) {
        match s {
            Stmt::FunctionDef(f) => {
                for d in &f.decorator_list {
                    self.expr(&d.expression);
                }
                self.params(&f.parameters);
                self.scope().bind(f.name.id.as_str());
                let parent = self.cur;
                let child = self.t.push(Kind::Function, f.name.id.as_str(), Some(parent));
                self.cur = child;
                self.scope().is_coroutine = f.is_async;
                self.bind_params(&f.parameters);
                self.stmts(&f.body);
                self.cur = parent;
            }
            Stmt::ClassDef(c) => {
                for d in &c.decorator_list {
                    self.expr(&d.expression);
                }
                if let Some(a) = &c.arguments {
                    for e in a.args.iter() {
                        self.expr(e);
                    }
                    for k in a.keywords.iter() {
                        self.expr(&k.value);
                    }
                }
                self.scope().bind(c.name.id.as_str());
                let parent = self.cur;
                let child = self.t.push(Kind::Class, c.name.id.as_str(), Some(parent));
                self.cur = child;
                self.stmts(&c.body);
                self.cur = parent;
            }
            Stmt::Return(r) => {
                if let Some(v) = &r.value {
                    self.expr(v);
                }
            }
            Stmt::Delete(d) => {
                for t in &d.targets {
                    self.target(t);
                }
            }
            Stmt::Assign(a) => {
                self.expr(&a.value);
                for t in &a.targets {
                    self.target(t);
                }
            }
            Stmt::AugAssign(a) => {
                self.expr(&a.value);
                self.expr(&a.target);
                self.target(&a.target);
            }
            Stmt::AnnAssign(a) => {
                if let Some(v) = &a.value {
                    self.expr(v);
                }
                if a.value.is_some() || matches!(*a.target, Expr::Name(_)) {
                    self.target(&a.target);
                }
            }
            Stmt::For(f) => {
                self.expr(&f.iter);
                self.target(&f.target);
                self.stmts(&f.body);
                self.stmts(&f.orelse);
            }
            Stmt::While(w) => {
                self.expr(&w.test);
                self.stmts(&w.body);
                self.stmts(&w.orelse);
            }
            Stmt::If(i) => {
                self.expr(&i.test);
                self.stmts(&i.body);
                for c in &i.elif_else_clauses {
                    if let Some(t) = &c.test {
                        self.expr(t);
                    }
                    self.stmts(&c.body);
                }
            }
            Stmt::With(w) => {
                for item in &w.items {
                    self.expr(&item.context_expr);
                    if let Some(v) = &item.optional_vars {
                        self.target(v);
                    }
                }
                self.stmts(&w.body);
            }
            Stmt::Raise(r) => {
                if let Some(e) = &r.exc {
                    self.expr(e);
                }
                if let Some(c) = &r.cause {
                    self.expr(c);
                }
            }
            Stmt::Try(t) => {
                self.stmts(&t.body);
                for h in &t.handlers {
                    let ast::ExceptHandler::ExceptHandler(h) = h;
                    if let Some(ty) = &h.type_ {
                        self.expr(ty);
                    }
                    if let Some(n) = &h.name {
                        self.scope().bind(n.id.as_str());
                    }
                    self.stmts(&h.body);
                }
                self.stmts(&t.orelse);
                self.stmts(&t.finalbody);
            }
            Stmt::Assert(a) => {
                self.expr(&a.test);
                if let Some(m) = &a.msg {
                    self.expr(m);
                }
            }
            Stmt::Import(i) => {
                for a in &i.names {
                    let name = a.asname.as_ref().map(|n| n.id.to_string()).unwrap_or_else(|| a.name.id.split('.').next().unwrap().to_string());
                    self.scope().bind(&name);
                }
            }
            Stmt::ImportFrom(i) => {
                for a in &i.names {
                    if a.name.id.as_str() == "*" {
                        continue;
                    }
                    let name = a.asname.as_ref().map(|n| n.id.to_string()).unwrap_or_else(|| a.name.id.to_string());
                    self.scope().bind(&name);
                }
            }
            Stmt::Global(g) => {
                for n in &g.names {
                    self.scope().globals.insert(n.id.to_string());
                }
            }
            Stmt::Nonlocal(n) => {
                for name in &n.names {
                    self.scope().nonlocals.insert(name.id.to_string());
                }
            }
            Stmt::Expr(e) => self.expr(&e.value),
            Stmt::Match(m) => {
                self.expr(&m.subject);
                for case in &m.cases {
                    self.pattern(&case.pattern);
                    if let Some(g) = &case.guard {
                        self.expr(g);
                    }
                    self.stmts(&case.body);
                }
            }
            Stmt::TypeAlias(_) | Stmt::Pass(_) | Stmt::Break(_) | Stmt::Continue(_) | Stmt::IpyEscapeCommand(_) => {}
        }
    }
    fn pattern(&mut self, p: &ast::Pattern) {
        use ast::Pattern::*;
        match p {
            MatchValue(v) => self.expr(&v.value),
            MatchSingleton(_) => {}
            MatchSequence(s) => {
                for q in &s.patterns {
                    self.pattern(q);
                }
            }
            MatchMapping(m) => {
                for k in &m.keys {
                    self.expr(k);
                }
                for q in &m.patterns {
                    self.pattern(q);
                }
                if let Some(r) = &m.rest {
                    self.scope().bind(r.id.as_str());
                }
            }
            MatchClass(c) => {
                self.expr(&c.cls);
                for q in &c.arguments.patterns {
                    self.pattern(q);
                }
                for k in &c.arguments.keywords {
                    self.pattern(&k.pattern);
                }
            }
            MatchStar(s) => {
                if let Some(n) = &s.name {
                    self.scope().bind(n.id.as_str());
                }
            }
            MatchAs(a) => {
                if let Some(q) = &a.pattern {
                    self.pattern(q);
                }
                if let Some(n) = &a.name {
                    self.scope().bind(n.id.as_str());
                }
            }
            MatchOr(o) => {
                for q in &o.patterns {
                    self.pattern(q);
                }
            }
        }
    }
    fn target(&mut self, t: &Expr) {
        match t {
            Expr::Name(n) => self.scope().bind(n.id.as_str()),
            Expr::Tuple(tu) => {
                for e in &tu.elts {
                    self.target(e);
                }
            }
            Expr::List(l) => {
                for e in &l.elts {
                    self.target(e);
                }
            }
            Expr::Starred(s) => self.target(&s.value),
            Expr::Attribute(a) => self.expr(&a.value),
            Expr::Subscript(s) => {
                self.expr(&s.value);
                self.expr(&s.slice);
            }
            other => self.expr(other),
        }
    }
    fn comprehension(&mut self, generators: &[ast::Comprehension], elts: &[&Expr], name: &str, is_gen: bool) {
        // The outermost iterable is evaluated in the enclosing scope.
        self.expr(&generators[0].iter);
        let parent = self.cur;
        let child = self.t.push(Kind::Comprehension, name, Some(parent));
        self.cur = child;
        self.scope().bind(".0");
        self.scope().params = vec![".0".into()];
        self.scope().is_generator = is_gen;
        for (i, g) in generators.iter().enumerate() {
            if i > 0 {
                self.expr(&g.iter);
            }
            self.target(&g.target);
            for cond in &g.ifs {
                self.expr(cond);
            }
        }
        for e in elts {
            self.expr(e);
        }
        self.cur = parent;
    }
    fn expr(&mut self, e: &Expr) {
        match e {
            Expr::BoolOp(b) => {
                for v in &b.values {
                    self.expr(v);
                }
            }
            Expr::Named(n) => {
                self.expr(&n.value);
                // walrus in a comprehension binds in the enclosing function scope
                if self.scope().kind == Some(Kind::Comprehension) {
                    if let Expr::Name(name) = &*n.target {
                        let mut p = self.scope().parent;
                        let mut target = self.cur;
                        while let Some(pi) = p {
                            target = pi;
                            if self.t.scopes[pi].kind != Some(Kind::Comprehension) {
                                break;
                            }
                            p = self.t.scopes[pi].parent;
                        }
                        self.t.scopes[target].bind(name.id.as_str());
                        if self.t.scopes[target].is_function_like() {
                            self.scope().nonlocals.insert(name.id.to_string());
                        } else {
                            self.scope().globals.insert(name.id.to_string());
                        }
                        return;
                    }
                }
                self.target(&n.target);
            }
            Expr::BinOp(b) => {
                self.expr(&b.left);
                self.expr(&b.right);
            }
            Expr::UnaryOp(u) => self.expr(&u.operand),
            Expr::Lambda(l) => {
                if let Some(p) = &l.parameters {
                    self.params(p);
                }
                let parent = self.cur;
                let child = self.t.push(Kind::Lambda, "<lambda>", Some(parent));
                self.cur = child;
                if let Some(p) = &l.parameters {
                    self.bind_params(p);
                }
                self.expr(&l.body);
                self.cur = parent;
            }
            Expr::If(i) => {
                self.expr(&i.test);
                self.expr(&i.body);
                self.expr(&i.orelse);
            }
            Expr::Dict(d) => {
                for item in &d.items {
                    if let Some(k) = &item.key {
                        self.expr(k);
                    }
                    self.expr(&item.value);
                }
            }
            Expr::Set(s) => {
                for v in &s.elts {
                    self.expr(v);
                }
            }
            Expr::ListComp(c) => self.comprehension(&c.generators, &[&c.elt], "<listcomp>", false),
            Expr::SetComp(c) => self.comprehension(&c.generators, &[&c.elt], "<setcomp>", false),
            Expr::DictComp(c) => {
                let key: &Expr = c.key.as_deref().unwrap_or(&c.value);
                self.comprehension(&c.generators, &[key, &c.value], "<dictcomp>", false)
            }
            Expr::Generator(g) => self.comprehension(&g.generators, &[&g.elt], "<genexpr>", true),
            Expr::Await(a) => {
                self.scope().is_coroutine = true;
                self.expr(&a.value)
            }
            Expr::Yield(y) => {
                self.scope().is_generator = true;
                if let Some(v) = &y.value {
                    self.expr(v);
                }
            }
            Expr::YieldFrom(y) => {
                self.scope().is_generator = true;
                self.expr(&y.value)
            }
            Expr::Compare(c) => {
                self.expr(&c.left);
                for v in c.comparators.iter() {
                    self.expr(v);
                }
            }
            Expr::Call(c) => {
                if let Expr::Name(n) = &*c.func {
                    if n.id.as_str() == "super" && c.arguments.args.is_empty() {
                        self.scope().uses_class_cell = true;
                        self.scope().use_("__class__");
                    }
                }
                self.expr(&c.func);
                for a in c.arguments.args.iter() {
                    self.expr(a);
                }
                for k in c.arguments.keywords.iter() {
                    self.expr(&k.value);
                }
            }
            Expr::FString(f) => {
                for part in f.value.iter() {
                    if let ast::FStringPart::FString(fs) = part {
                        self.interpolations(&fs.elements);
                    }
                }
            }
            Expr::TString(t) => {
                for ts in t.value.iter() {
                    self.interpolations(&ts.elements);
                }
            }
            Expr::Attribute(a) => self.expr(&a.value),
            Expr::Subscript(s) => {
                self.expr(&s.value);
                self.expr(&s.slice);
            }
            Expr::Starred(s) => self.expr(&s.value),
            Expr::Name(n) => {
                let id = n.id.as_str();
                if id == "__class__" {
                    self.scope().uses_class_cell = true;
                }
                self.scope().use_(id);
            }
            Expr::List(l) => {
                for v in &l.elts {
                    self.expr(v);
                }
            }
            Expr::Tuple(t) => {
                for v in &t.elts {
                    self.expr(v);
                }
            }
            Expr::Slice(s) => {
                if let Some(v) = &s.lower {
                    self.expr(v);
                }
                if let Some(v) = &s.upper {
                    self.expr(v);
                }
                if let Some(v) = &s.step {
                    self.expr(v);
                }
            }
            Expr::StringLiteral(_) | Expr::BytesLiteral(_) | Expr::NumberLiteral(_) | Expr::BooleanLiteral(_) | Expr::NoneLiteral(_) | Expr::EllipsisLiteral(_) | Expr::IpyEscapeCommand(_) => {}
        }
    }
    fn interpolations(&mut self, elements: &ast::InterpolatedStringElements) {
        for el in elements.iter() {
            if let ast::InterpolatedStringElement::Interpolation(i) = el {
                self.expr(&i.expression);
                if let Some(spec) = &i.format_spec {
                    self.interpolations(&spec.elements);
                }
            }
        }
    }
}
