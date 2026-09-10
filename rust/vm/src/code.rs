//! Bytecode: the instruction set, and a code object.
//!
//! A stack machine with fixed-size instructions (an opcode and a 32-bit argument). Exception
//! handlers are a table on the code object (`Handler`), not a block stack: raising looks the
//! current `pc` up in the table, truncates the value stack to the handler's depth, pushes the
//! exception and jumps. The compiler in `frontage-compile` is the only writer.

use crate::value::Value;
use std::rc::Rc;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum Op {
    Nop,
    Pop,
    Dup,
    Dup2,
    Rot2,
    Rot3,
    /// Push `consts[arg]`.
    LoadConst,
    LoadFast,
    StoreFast,
    DeleteFast,
    /// Cells: `arg` indexes the frame's cells (cellvars first, then freevars).
    LoadDeref,
    StoreDeref,
    /// Push the cell object itself (for a closure tuple).
    LoadClosure,
    LoadGlobal,
    StoreGlobal,
    DeleteGlobal,
    /// Module and class bodies: the frame's namespace dict, then globals, then builtins.
    LoadName,
    StoreName,
    DeleteName,
    LoadAttr,
    StoreAttr,
    DeleteAttr,
    LoadSubscr,
    StoreSubscr,
    DeleteSubscr,
    /// `arg` is a `BinOp`.
    BinaryOp,
    InplaceOp,
    /// `arg` is a `UnOp`.
    UnaryOp,
    /// `arg` is a `CmpOp`.
    CompareOp,
    /// `arg` 1 negates (`is not`).
    IsOp,
    /// `arg` 1 negates (`not in`).
    ContainsOp,
    Jump,
    JumpIfFalse,
    JumpIfTrue,
    JumpIfFalseOrPop,
    JumpIfTrueOrPop,
    GetIter,
    /// Push the next item, or pop the iterator and jump to `arg`.
    ForIter,
    /// `arg` positional arguments above the callee.
    Call,
    /// Like `Call`, with a tuple of keyword names on top; `arg` counts positional + keyword values.
    CallKw,
    /// Callee, an args tuple, and (if `arg` is 1) a kwargs dict.
    CallEx,
    /// Stack (bottom to top): [defaults tuple] [kwdefaults dict] [closure tuple] code-const name-const.
    /// `arg` flags: 1 defaults, 2 kwdefaults, 4 closure.
    MakeFunction,
    /// Stack: body function, name, then `arg` bases → a class.
    MakeClass,
    BuildTuple,
    BuildList,
    BuildSet,
    /// `arg` pairs.
    BuildDict,
    /// `arg` is 2 or 3.
    BuildSlice,
    /// Join `arg` strings.
    BuildString,
    /// Append to the list `arg` slots below the top (comprehensions).
    ListAppend,
    SetAdd,
    /// Key then value on top; the dict `arg` below.
    MapAdd,
    ListExtend,
    SetUpdate,
    DictUpdate,
    ListToTuple,
    UnpackSequence,
    /// `arg` = before | after << 16.
    UnpackEx,
    /// `arg` = conversion (0 none, 1 str, 2 repr, 3 ascii) | has_spec << 2.
    FormatValue,
    /// Same flags as `FormatValue`; the expression text const sits below the value.
    BuildInterpolation,
    /// Strings tuple below `arg` interpolations.
    BuildTemplate,
    Return,
    /// `arg` 0: re-raise the handled exception; 1: raise TOS; 2: raise TOS1 from TOS.
    Raise,
    Reraise,
    /// Leave an `except` block: drop the handled exception.
    PopExcept,
    /// Stack: exc, type → exc, bool.
    CheckExcMatch,
    /// Stack: exit-callable, exc → calls `exit(type, exc, tb)`; truthy → drop the exception and
    /// jump to `arg`; else re-raise.
    WithExcept,
    /// Stack: level, fromlist → module. `arg` names the module.
    ImportName,
    ImportFrom,
    ImportStar,
    Yield,
    /// Delegate to a sub-iterator (also `await`).
    YieldFrom,
    GetAwaitable,
    GetAIter,
    GetANext,
    /// Push the code object's `__class__` cell reference for zero-argument `super()`.
    LoadBuildClass,
    /// `obj.name` for a call: pushes [method, obj] when `name` resolves to a plain function
    /// on the type, else [attribute, UNDEF]. Paired with `CallMethod`.
    LoadMethod,
    /// `arg` positional arguments above the pair `LoadMethod` pushed.
    CallMethod,
    /// Boolean guard for `assert`: `arg` 1 with a message on the stack.
    RaiseAssert,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    TrueDiv,
    FloorDiv,
    Mod,
    Pow,
    LShift,
    RShift,
    And,
    Or,
    Xor,
    MatMul,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum UnOp {
    Neg,
    Pos,
    Not,
    Invert,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum CmpOp {
    Lt,
    Le,
    Eq,
    Ne,
    Gt,
    Ge,
}

impl BinOp {
    pub fn from_u32(n: u32) -> BinOp {
        // Safe: the compiler only emits values of this enum.
        unsafe { core::mem::transmute(n as u8) }
    }
    pub fn symbol(self) -> &'static str {
        match self {
            BinOp::Add => "+",
            BinOp::Sub => "-",
            BinOp::Mul => "*",
            BinOp::TrueDiv => "/",
            BinOp::FloorDiv => "//",
            BinOp::Mod => "%",
            BinOp::Pow => "**",
            BinOp::LShift => "<<",
            BinOp::RShift => ">>",
            BinOp::And => "&",
            BinOp::Or => "|",
            BinOp::Xor => "^",
            BinOp::MatMul => "@",
        }
    }
}
impl UnOp {
    pub fn from_u32(n: u32) -> UnOp {
        unsafe { core::mem::transmute(n as u8) }
    }
}
impl CmpOp {
    pub fn from_u32(n: u32) -> CmpOp {
        unsafe { core::mem::transmute(n as u8) }
    }
    pub fn symbol(self) -> &'static str {
        match self {
            CmpOp::Lt => "<",
            CmpOp::Le => "<=",
            CmpOp::Eq => "==",
            CmpOp::Ne => "!=",
            CmpOp::Gt => ">",
            CmpOp::Ge => ">=",
        }
    }
    pub fn swapped(self) -> CmpOp {
        match self {
            CmpOp::Lt => CmpOp::Gt,
            CmpOp::Le => CmpOp::Ge,
            CmpOp::Gt => CmpOp::Lt,
            CmpOp::Ge => CmpOp::Le,
            other => other,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Instr {
    pub op: Op,
    pub arg: u32,
}

#[derive(Clone, Copy, Debug)]
pub struct Handler {
    /// Instruction range `[start, end)` this handler covers.
    pub start: u32,
    pub end: u32,
    pub target: u32,
    /// Value-stack depth to restore before pushing the exception.
    pub depth: u32,
    /// How many exceptions were being handled when the `try` began (the `handling` depth).
    pub hdepth: u32,
}

pub const FLAG_VARARGS: u32 = 1;
pub const FLAG_VARKW: u32 = 2;
pub const FLAG_GENERATOR: u32 = 4;
pub const FLAG_COROUTINE: u32 = 8;
/// Module and class bodies: names go through the frame's namespace dict.
pub const FLAG_NAMESPACE: u32 = 16;
pub const FLAG_ASYNC_GENERATOR: u32 = 32;
/// `consts[0]` is this code object's docstring. A flag rather than "the first constant is a
/// string", which is what the disabled first attempt at `__doc__` tried and could not tell
/// apart from a function that merely opens with a string literal. It is a bit in a varint
/// field, so a `.fbc` written before it existed still loads.
pub const FLAG_DOCSTRING: u32 = 64;

#[derive(Debug, Default)]
pub struct Code {
    pub name: String,
    pub qualname: String,
    pub filename: Rc<str>,
    pub firstline: u32,
    pub instrs: Vec<Instr>,
    /// `(pc, line)` pairs, ascending by pc.
    pub lines: Vec<(u32, u32)>,
    pub consts: Vec<Value>,
    /// Interned strings.
    pub names: Vec<Value>,
    /// Fast locals, parameters first.
    pub varnames: Vec<Value>,
    pub cellvars: Vec<Value>,
    pub freevars: Vec<Value>,
    /// Locals that are also cells: `(local index, cell index)`, copied in at frame setup.
    pub cell_of_local: Vec<(u32, u32)>,
    pub argcount: u32,
    pub posonlyargcount: u32,
    pub kwonlyargcount: u32,
    pub flags: u32,
    pub handlers: Vec<Handler>,
    pub nested: Vec<Rc<Code>>,
    /// Per-instruction caches for `LoadGlobal`: `(globals version, builtins version, value)`,
    /// allocated on first use.
    pub gcache: core::cell::RefCell<Vec<(u32, u32, Value)>>,
}

impl Code {
    pub fn nlocals(&self) -> usize {
        self.varnames.len()
    }
    pub fn line_at(&self, pc: u32) -> u32 {
        let mut line = self.firstline;
        for &(at, l) in &self.lines {
            if at > pc {
                break;
            }
            line = l;
        }
        line
    }
    pub fn handler_for(&self, pc: u32) -> Option<&Handler> {
        // Innermost wins: the compiler emits inner handlers first.
        self.handlers.iter().find(|h| pc >= h.start && pc < h.end)
    }
    pub fn is_generator(&self) -> bool {
        self.flags & (FLAG_GENERATOR | FLAG_COROUTINE | FLAG_ASYNC_GENERATOR) != 0
    }
}
