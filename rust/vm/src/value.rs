//! A Python value in 64 bits.
//!
//! NaN-boxing: a float is its own bits, and everything else lives in the quiet-NaN space
//! (`0x7ff8_…`) under a 3-bit tag at bits 48–50 with a 32-bit payload — a small int, a bool,
//! `None`, or an index into the heap. A real NaN is canonicalised to `QNAN` with tag 0, so it
//! still reads as a float. Nothing is allocated for arithmetic, and a value is `Copy`.

use core::fmt;

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Value(pub u64);

const QNAN: u64 = 0x7ff8_0000_0000_0000;
const TAG_MASK: u64 = 0x0007_0000_0000_0000;
const TAG_INT: u64 = 1 << 48;
const TAG_BOOL: u64 = 2 << 48;
const TAG_NONE: u64 = 3 << 48;
const TAG_OBJ: u64 = 4 << 48;
const TAG_UNDEF: u64 = 5 << 48;
const PAYLOAD: u64 = 0xffff_ffff;

impl Value {
    pub const NONE: Value = Value(QNAN | TAG_NONE);
    pub const TRUE: Value = Value(QNAN | TAG_BOOL | 1);
    pub const FALSE: Value = Value(QNAN | TAG_BOOL);
    /// An unbound local, an empty dict slot, a missing default: never visible to Python.
    pub const UNDEF: Value = Value(QNAN | TAG_UNDEF);

    #[inline]
    pub fn int(i: i32) -> Value {
        Value(QNAN | TAG_INT | (i as u32 as u64))
    }
    #[inline]
    pub fn float(f: f64) -> Value {
        if f.is_nan() {
            Value(QNAN)
        } else {
            Value(f.to_bits())
        }
    }
    #[inline]
    pub fn bool(b: bool) -> Value {
        if b {
            Value::TRUE
        } else {
            Value::FALSE
        }
    }
    #[inline]
    pub fn obj(index: u32) -> Value {
        Value(QNAN | TAG_OBJ | index as u64)
    }

    #[inline]
    fn tag(self) -> u64 {
        self.0 & TAG_MASK
    }
    #[inline]
    fn tagged(self) -> bool {
        self.0 & QNAN == QNAN
    }
    #[inline]
    pub fn is_float(self) -> bool {
        !self.tagged() || self.tag() == 0
    }
    #[inline]
    pub fn as_float(self) -> f64 {
        f64::from_bits(self.0)
    }
    #[inline]
    pub fn is_int(self) -> bool {
        self.tagged() && self.tag() == TAG_INT
    }
    #[inline]
    pub fn as_int(self) -> i32 {
        (self.0 & PAYLOAD) as u32 as i32
    }
    #[inline]
    pub fn is_bool(self) -> bool {
        self.tagged() && self.tag() == TAG_BOOL
    }
    #[inline]
    pub fn as_bool(self) -> bool {
        self.0 & 1 == 1
    }
    #[inline]
    pub fn is_none(self) -> bool {
        self == Value::NONE
    }
    #[inline]
    pub fn is_undef(self) -> bool {
        self == Value::UNDEF
    }
    #[inline]
    pub fn is_obj(self) -> bool {
        self.tagged() && self.tag() == TAG_OBJ
    }
    #[inline]
    pub fn as_obj(self) -> u32 {
        (self.0 & PAYLOAD) as u32
    }
    /// The heap index if this is an object, else `None`.
    #[inline]
    pub fn obj_index(self) -> Option<u32> {
        if self.is_obj() {
            Some(self.as_obj())
        } else {
            None
        }
    }
}

impl Default for Value {
    fn default() -> Value {
        Value::UNDEF
    }
}

impl fmt::Debug for Value {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.is_int() {
            write!(f, "int({})", self.as_int())
        } else if self.is_float() {
            write!(f, "float({})", self.as_float())
        } else if self.is_bool() {
            write!(f, "{}", self.as_bool())
        } else if self.is_none() {
            write!(f, "None")
        } else if self.is_undef() {
            write!(f, "<undef>")
        } else {
            write!(f, "obj#{}", self.as_obj())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boxing_round_trips() {
        assert_eq!(Value::int(-7).as_int(), -7);
        assert!(Value::int(0).is_int() && !Value::int(0).is_float());
        assert_eq!(Value::float(2.5).as_float(), 2.5);
        assert!(Value::float(f64::NAN).is_float() && Value::float(f64::NAN).as_float().is_nan());
        assert!(Value::float(-0.0).is_float());
        assert_eq!(Value::obj(12345).as_obj(), 12345);
        assert!(Value::TRUE.as_bool() && !Value::FALSE.as_bool());
        assert!(Value::NONE.is_none() && !Value::NONE.is_float());
    }
}
