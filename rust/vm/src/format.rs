//! Text: Python's `repr` of floats and strings, the format-spec mini-language, `%` formatting.
//! Float printing uses Rust's shortest-round-trip digits and lays them out Python's way.

use crate::object::Obj;
use crate::value::Value;
use crate::vm::{PyResult, Vm};

/// `repr(float)`: shortest digits that round-trip, Python's layout (`1e+16`, `0.0001`, `inf`).
pub fn float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf" } else { "-inf" }.into();
    }
    if f == 0.0 {
        return if f.is_sign_negative() { "-0.0" } else { "0.0" }.into();
    }
    // Shortest digits via `{:e}`: "d.ddddde±x".
    let sci = format!("{:e}", f);
    let (mantissa, exp) = sci.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let neg = mantissa.starts_with('-');
    let digits: String = mantissa.chars().filter(|c| c.is_ascii_digit()).collect();
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    if (-4..16).contains(&exp) {
        if exp >= 0 {
            let e = exp as usize;
            if digits.len() <= e + 1 {
                out.push_str(&digits);
                for _ in digits.len()..=e {
                    out.push('0');
                }
                out.push_str(".0");
            } else {
                out.push_str(&digits[..e + 1]);
                out.push('.');
                out.push_str(&digits[e + 1..]);
            }
        } else {
            out.push_str("0.");
            for _ in 0..(-exp - 1) {
                out.push('0');
            }
            out.push_str(&digits);
        }
    } else {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        out.push(if exp < 0 { '-' } else { '+' });
        out.push_str(&format!("{:02}", exp.abs()));
    }
    out
}

pub fn str_repr(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

pub fn ascii_escape(s: &str) -> String {
    let mut out = String::new();
    for c in s.chars() {
        let n = c as u32;
        if n < 0x80 {
            out.push(c);
        } else if n < 0x100 {
            out.push_str(&format!("\\x{n:02x}"));
        } else if n < 0x10000 {
            out.push_str(&format!("\\u{n:04x}"));
        } else {
            out.push_str(&format!("\\U{n:08x}"));
        }
    }
    out
}

pub fn bytes_repr(b: &[u8], prefix: &str) -> String {
    let quote = if b.contains(&b'\'') && !b.contains(&b'"') { '"' } else { '\'' };
    let mut out = String::from(prefix);
    out.push(quote);
    for &c in b {
        match c {
            b'\\' => out.push_str("\\\\"),
            b'\n' => out.push_str("\\n"),
            b'\r' => out.push_str("\\r"),
            b'\t' => out.push_str("\\t"),
            c if c as char == quote => {
                out.push('\\');
                out.push(c as char);
            }
            0x20..=0x7e => out.push(c as char),
            c => out.push_str(&format!("\\x{c:02x}")),
        }
    }
    out.push(quote);
    out
}

#[derive(Default, Debug)]
pub struct Spec {
    pub fill: Option<char>,
    pub align: Option<char>,
    pub sign: Option<char>,
    pub alt: bool,
    pub zero: bool,
    pub width: Option<usize>,
    pub grouping: Option<char>,
    pub precision: Option<usize>,
    pub ty: Option<char>,
}

pub fn parse_spec(spec: &str) -> Result<Spec, String> {
    let chars: Vec<char> = spec.chars().collect();
    let mut s = Spec::default();
    let mut i = 0;
    if chars.len() >= 2 && matches!(chars[1], '<' | '>' | '^' | '=') {
        s.fill = Some(chars[0]);
        s.align = Some(chars[1]);
        i = 2;
    } else if !chars.is_empty() && matches!(chars[0], '<' | '>' | '^' | '=') {
        s.align = Some(chars[0]);
        i = 1;
    }
    if i < chars.len() && matches!(chars[i], '+' | '-' | ' ') {
        s.sign = Some(chars[i]);
        i += 1;
    }
    if i < chars.len() && chars[i] == '#' {
        s.alt = true;
        i += 1;
    }
    if i < chars.len() && chars[i] == '0' {
        s.zero = true;
        i += 1;
    }
    let start = i;
    while i < chars.len() && chars[i].is_ascii_digit() {
        i += 1;
    }
    if i > start {
        s.width = Some(chars[start..i].iter().collect::<String>().parse().unwrap());
    }
    if i < chars.len() && matches!(chars[i], ',' | '_') {
        s.grouping = Some(chars[i]);
        i += 1;
    }
    if i < chars.len() && chars[i] == '.' {
        i += 1;
        let start = i;
        while i < chars.len() && chars[i].is_ascii_digit() {
            i += 1;
        }
        if i == start {
            return Err("Format specifier missing precision".into());
        }
        s.precision = Some(chars[start..i].iter().collect::<String>().parse().unwrap());
    }
    if i < chars.len() {
        s.ty = Some(chars[i]);
        i += 1;
    }
    if i < chars.len() {
        return Err(format!("Invalid format specifier '{spec}'"));
    }
    Ok(s)
}

fn group(digits: &str, sep: char, every: usize) -> String {
    let bytes: Vec<char> = digits.chars().collect();
    let mut out = String::new();
    for (i, c) in bytes.iter().enumerate() {
        if i > 0 && (bytes.len() - i) % every == 0 {
            out.push(sep);
        }
        out.push(*c);
    }
    out
}

fn pad(body: &str, spec: &Spec, default_align: char, sign_aware: bool) -> String {
    let width = match spec.width {
        Some(w) => w,
        None => return body.to_string(),
    };
    let len = body.chars().count();
    if len >= width {
        return body.to_string();
    }
    let fill = spec.fill.unwrap_or(if spec.zero && sign_aware { '0' } else { ' ' });
    let align = spec.align.unwrap_or(if spec.zero && sign_aware { '=' } else { default_align });
    let padding = width - len;
    match align {
        '<' => format!("{body}{}", fill.to_string().repeat(padding)),
        '^' => {
            let left = padding / 2;
            format!("{}{body}{}", fill.to_string().repeat(left), fill.to_string().repeat(padding - left))
        }
        '=' => {
            let (sign, rest) = if body.starts_with(['-', '+', ' ']) { body.split_at(1) } else { ("", body) };
            format!("{sign}{}{rest}", fill.to_string().repeat(padding))
        }
        _ => format!("{}{body}", fill.to_string().repeat(padding)),
    }
}

fn apply_sign(neg: bool, spec: &Spec) -> &'static str {
    if neg {
        "-"
    } else {
        match spec.sign {
            Some('+') => "+",
            Some(' ') => " ",
            _ => "",
        }
    }
}

pub fn format_int(i: i64, spec: &Spec) -> Result<String, String> {
    let neg = i < 0;
    let mag = i.unsigned_abs();
    let ty = spec.ty.unwrap_or('d');
    let digits = match ty {
        'd' | 'n' => mag.to_string(),
        'b' => format!("{mag:b}"),
        'o' => format!("{mag:o}"),
        'x' => format!("{mag:x}"),
        'X' => format!("{mag:X}"),
        'c' => return Ok(char::from_u32(mag as u32).map(|c| c.to_string()).unwrap_or_default()),
        'e' | 'E' | 'f' | 'F' | 'g' | 'G' | '%' => return format_float(i as f64, spec),
        other => return Err(format!("Unknown format code '{other}' for object of type 'int'")),
    };
    let digits = match spec.grouping {
        Some(sep) => group(&digits, sep, if matches!(ty, 'b' | 'o' | 'x' | 'X') { 4 } else { 3 }),
        None => digits,
    };
    let prefix = if spec.alt {
        match ty {
            'b' => "0b",
            'o' => "0o",
            'x' => "0x",
            'X' => "0X",
            _ => "",
        }
    } else {
        ""
    };
    let body = format!("{}{prefix}{digits}", apply_sign(neg, spec));
    Ok(pad(&body, spec, '>', true))
}

fn fixed(f: f64, prec: usize) -> String {
    format!("{:.*}", prec, f)
}

fn exp_form(f: f64, prec: usize, upper: bool) -> String {
    let s = format!("{:.*e}", prec, f);
    let (m, e) = s.split_once('e').unwrap();
    let e: i32 = e.parse().unwrap();
    let out = format!("{m}e{}{:02}", if e < 0 { '-' } else { '+' }, e.abs());
    if upper {
        out.to_uppercase()
    } else {
        out
    }
}

fn general(f: f64, prec: usize, upper: bool, alt: bool) -> String {
    let p = if prec == 0 { 1 } else { prec };
    if f == 0.0 {
        return if alt { format!("{:.*}", p - 1, 0.0) } else { "0".into() };
    }
    let exp = f.abs().log10().floor() as i32;
    let sci = format!("{:.*e}", p - 1, f);
    let (_, e) = sci.split_once('e').unwrap();
    let exp = e.parse::<i32>().unwrap_or(exp);
    let mut s = if -4 <= exp && exp < p as i32 { format!("{:.*}", (p as i32 - 1 - exp).max(0) as usize, f) } else { exp_form(f, p - 1, upper) };
    if !alt {
        // strip trailing zeros in the mantissa
        if let Some(epos) = s.find(['e', 'E']) {
            let (m, e) = s.split_at(epos);
            let m = if m.contains('.') { m.trim_end_matches('0').trim_end_matches('.') } else { m };
            s = format!("{m}{e}");
        } else if s.contains('.') {
            s = s.trim_end_matches('0').trim_end_matches('.').to_string();
        }
    }
    s
}

pub fn format_float(f: f64, spec: &Spec) -> Result<String, String> {
    let neg = f.is_sign_negative() && !(f == 0.0 && spec.ty.is_none() && false);
    let neg = neg && !f.is_nan();
    let mag = f.abs();
    let ty = spec.ty;
    let body = if mag.is_nan() {
        "nan".to_string()
    } else if mag.is_infinite() {
        "inf".to_string()
    } else {
        match ty {
            Some('f') | Some('F') => fixed(mag, spec.precision.unwrap_or(6)),
            Some('e') => exp_form(mag, spec.precision.unwrap_or(6), false),
            Some('E') => exp_form(mag, spec.precision.unwrap_or(6), true),
            Some('g') => general(mag, spec.precision.unwrap_or(6), false, spec.alt),
            Some('G') => general(mag, spec.precision.unwrap_or(6), true, spec.alt),
            Some('%') => format!("{}%", fixed(mag * 100.0, spec.precision.unwrap_or(6))),
            Some('n') => general(mag, spec.precision.unwrap_or(6), false, spec.alt),
            None => match spec.precision {
                Some(p) => {
                    let g = general(mag, p, false, spec.alt);
                    g
                }
                None => {
                    let r = float_repr(mag);
                    r
                }
            },
            Some(other) => return Err(format!("Unknown format code '{other}' for object of type 'float'")),
        }
    };
    let body = match spec.grouping {
        Some(sep) if !body.contains('e') && !body.contains("inf") && !body.contains("nan") => {
            let (int_part, rest) = match body.find('.') {
                Some(p) => body.split_at(p),
                None => (body.as_str(), ""),
            };
            format!("{}{rest}", group(int_part, sep, 3))
        }
        _ => body,
    };
    let body = format!("{}{body}", apply_sign(neg, spec));
    Ok(pad(&body, spec, '>', true))
}

pub fn format_str(s: &str, spec: &Spec) -> Result<String, String> {
    if let Some(t) = spec.ty {
        if t != 's' {
            return Err(format!("Unknown format code '{t}' for object of type 'str'"));
        }
    }
    let body: String = match spec.precision {
        Some(p) => s.chars().take(p).collect(),
        None => s.to_string(),
    };
    Ok(pad(&body, spec, '<', false))
}

/// `format(v, spec)` for the builtin types.
pub fn format_builtin(vm: &mut Vm, v: Value, spec: &str) -> PyResult<String> {
    let parsed = match parse_spec(spec) {
        Ok(p) => p,
        Err(e) => return Err(vm.value_error(e)),
    };
    let r = if v.is_bool() && spec.is_empty() {
        Ok(if v.as_bool() { "True".into() } else { "False".into() })
    } else if let Some(i) = vm.as_i64(v).filter(|_| !v.is_float()) {
        format_int(i, &parsed)
    } else if let Some(f) = vm.as_f64(v) {
        format_float(f, &parsed)
    } else if let Some(s) = vm.as_str(v) {
        format_str(s, &parsed)
    } else if spec.is_empty() {
        return vm.str_of(v);
    } else {
        let t = vm.type_name(v);
        Err(format!("unsupported format string passed to {t}.__format__"))
    };
    r.map_err(|e| vm.value_error(e))
}

/// `"..." % args`.
pub fn percent_format(vm: &mut Vm, fmt: &str, args: Value) -> PyResult<String> {
    let items: Vec<Value> = if args.is_obj() {
        match vm.heap.get(args) {
            Obj::Tuple(t) => t.clone(),
            _ => vec![args],
        }
    } else {
        vec![args]
    };
    let mapping = args.is_obj() && matches!(vm.heap.get(args), Obj::Dict(_));
    let mut out = String::new();
    let mut next = 0usize;
    let chars: Vec<char> = fmt.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c != '%' {
            out.push(c);
            i += 1;
            continue;
        }
        i += 1;
        if i >= chars.len() {
            return Err(vm.value_error("incomplete format"));
        }
        if chars[i] == '%' {
            out.push('%');
            i += 1;
            continue;
        }
        // %(name)
        let mut key = None;
        if chars[i] == '(' {
            let start = i + 1;
            while i < chars.len() && chars[i] != ')' {
                i += 1;
            }
            key = Some(chars[start..i].iter().collect::<String>());
            i += 1;
        }
        let mut spec = Spec::default();
        let mut flags = String::new();
        while i < chars.len() && matches!(chars[i], '-' | '+' | ' ' | '#' | '0') {
            flags.push(chars[i]);
            i += 1;
        }
        if flags.contains('-') {
            spec.align = Some('<');
        }
        if flags.contains('+') {
            spec.sign = Some('+');
        } else if flags.contains(' ') {
            spec.sign = Some(' ');
        }
        spec.alt = flags.contains('#');
        spec.zero = flags.contains('0') && !flags.contains('-');
        let start = i;
        if i < chars.len() && chars[i] == '*' {
            let w = items.get(next).copied().unwrap_or(Value::int(0));
            next += 1;
            spec.width = vm.as_i64(w).map(|n| n as usize);
            i += 1;
        } else {
            while i < chars.len() && chars[i].is_ascii_digit() {
                i += 1;
            }
            if i > start {
                spec.width = Some(chars[start..i].iter().collect::<String>().parse().unwrap());
            }
        }
        if i < chars.len() && chars[i] == '.' {
            i += 1;
            if i < chars.len() && chars[i] == '*' {
                let p = items.get(next).copied().unwrap_or(Value::int(0));
                next += 1;
                spec.precision = vm.as_i64(p).map(|n| n as usize);
                i += 1;
            } else {
                let start = i;
                while i < chars.len() && chars[i].is_ascii_digit() {
                    i += 1;
                }
                spec.precision = Some(chars[start..i].iter().collect::<String>().parse().unwrap_or(0));
            }
        }
        if i >= chars.len() {
            return Err(vm.value_error("incomplete format"));
        }
        let ty = chars[i];
        i += 1;
        let arg = match key {
            Some(k) => {
                let kv = vm.str(&k);
                match vm.get_item(args, kv) {
                    Ok(v) => v,
                    Err(e) => return Err(e),
                }
            }
            None => {
                if mapping && ty != 's' && ty != 'r' {
                    return Err(vm.type_error("format requires a mapping"));
                }
                match items.get(next) {
                    Some(&v) => {
                        next += 1;
                        v
                    }
                    None => return Err(vm.type_error("not enough arguments for format string")),
                }
            }
        };
        let piece = match ty {
            's' => {
                let s = vm.str_of(arg)?;
                format_str(&s, &Spec { precision: spec.precision, width: spec.width, align: Some(spec.align.unwrap_or('>')), ..Default::default() }).map_err(|e| vm.value_error(e))?
            }
            'r' | 'a' => {
                let s = vm.repr(arg)?;
                let s = if ty == 'a' { ascii_escape(&s) } else { s };
                format_str(&s, &Spec { precision: spec.precision, width: spec.width, align: Some(spec.align.unwrap_or('>')), ..Default::default() }).map_err(|e| vm.value_error(e))?
            }
            'd' | 'i' | 'u' | 'x' | 'X' | 'o' | 'c' => {
                let n = match vm.as_i64(arg) {
                    Some(n) if !arg.is_float() => n,
                    _ => match vm.as_f64(arg) {
                        Some(f) if ty != 'c' => f as i64,
                        _ => {
                            let t = vm.type_name(arg);
                            return Err(vm.type_error(format!("%{ty} format: a real number is required, not {t}")));
                        }
                    },
                };
                spec.ty = Some(if ty == 'i' || ty == 'u' { 'd' } else { ty });
                if ty == 'c' {
                    if let Some(s) = vm.as_str(arg) {
                        s.to_string()
                    } else {
                        format_int(n, &spec).map_err(|e| vm.value_error(e))?
                    }
                } else {
                    format_int(n, &spec).map_err(|e| vm.value_error(e))?
                }
            }
            'f' | 'F' | 'e' | 'E' | 'g' | 'G' => {
                let f = match vm.as_f64(arg) {
                    Some(f) => f,
                    None => {
                        let t = vm.type_name(arg);
                        return Err(vm.type_error(format!("must be real number, not {t}")));
                    }
                };
                spec.ty = Some(ty);
                if spec.precision.is_none() {
                    spec.precision = Some(6);
                }
                format_float(f, &spec).map_err(|e| vm.value_error(e))?
            }
            other => return Err(vm.value_error(format!("unsupported format character '{other}'"))),
        };
        out.push_str(&piece);
    }
    if !mapping && next < items.len() {
        return Err(vm.type_error("not all arguments converted during string formatting"));
    }
    Ok(out)
}

/// `str.format`: `{}`/`{0}`/`{name}`/`{a.b}`/`{a[0]}` with `!r` and `:spec`.
pub fn str_format(vm: &mut Vm, fmt: &str, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult<String> {
    let mut out = String::new();
    let chars: Vec<char> = fmt.chars().collect();
    let mut i = 0;
    let mut auto = 0usize;
    while i < chars.len() {
        let c = chars[i];
        if c == '{' {
            if i + 1 < chars.len() && chars[i + 1] == '{' {
                out.push('{');
                i += 2;
                continue;
            }
            // find the matching close, allowing one level of nesting in the spec
            let start = i + 1;
            let mut depth = 1;
            let mut j = start;
            while j < chars.len() {
                if chars[j] == '{' {
                    depth += 1;
                } else if chars[j] == '}' {
                    depth -= 1;
                    if depth == 0 {
                        break;
                    }
                }
                j += 1;
            }
            if j >= chars.len() {
                return Err(vm.value_error("Single '{' encountered in format string"));
            }
            let field: String = chars[start..j].iter().collect();
            i = j + 1;
            let (name_part, spec_part) = match field.find(':') {
                Some(p) => (&field[..p], Some(&field[p + 1..])),
                None => (field.as_str(), None),
            };
            let (name_part, conv) = match name_part.find('!') {
                Some(p) => (&name_part[..p], Some(&name_part[p + 1..])),
                None => (name_part, None),
            };
            // the field: index/name then .attr / [key] chain
            let mut chain = name_part;
            let head_end = chain.find(['.', '[']).unwrap_or(chain.len());
            let head = &chain[..head_end];
            chain = &chain[head_end..];
            let mut value = if head.is_empty() {
                let v = args.get(auto).copied();
                auto += 1;
                match v {
                    Some(v) => v,
                    None => return Err(vm.index_error("Replacement index out of range for positional args tuple")),
                }
            } else if let Ok(n) = head.parse::<usize>() {
                match args.get(n).copied() {
                    Some(v) => v,
                    None => return Err(vm.index_error("Replacement index out of range for positional args tuple")),
                }
            } else {
                let mut found = None;
                for &(k, v) in kwargs {
                    if vm.as_str(k) == Some(head) {
                        found = Some(v);
                    }
                }
                match found {
                    Some(v) => v,
                    None => {
                        let k = vm.str(head);
                        return Err(vm.key_error(k));
                    }
                }
            };
            while !chain.is_empty() {
                if let Some(rest) = chain.strip_prefix('.') {
                    let end = rest.find(['.', '[']).unwrap_or(rest.len());
                    let attr = vm.intern(&rest[..end]);
                    value = vm.get_attr(value, attr)?;
                    chain = &rest[end..];
                } else if let Some(rest) = chain.strip_prefix('[') {
                    let end = rest.find(']').unwrap_or(rest.len());
                    let key = &rest[..end];
                    let kv = match key.parse::<i32>() {
                        Ok(n) => Value::int(n),
                        Err(_) => vm.str(key),
                    };
                    value = vm.get_item(value, kv)?;
                    chain = &rest[(end + 1).min(rest.len())..];
                } else {
                    break;
                }
            }
            let value = match conv {
                Some("r") => {
                    let s = vm.repr(value)?;
                    vm.string(s)
                }
                Some("s") => {
                    let s = vm.str_of(value)?;
                    vm.string(s)
                }
                Some("a") => {
                    let s = vm.repr(value)?;
                    let s = ascii_escape(&s);
                    vm.string(s)
                }
                _ => value,
            };
            let spec = match spec_part {
                Some(s) if s.contains('{') => str_format(vm, s, args, kwargs)?,
                Some(s) => s.to_string(),
                None => String::new(),
            };
            let piece = vm.format_value(value, &spec)?;
            out.push_str(&piece);
        } else if c == '}' {
            if i + 1 < chars.len() && chars[i + 1] == '}' {
                out.push('}');
                i += 2;
                continue;
            }
            return Err(vm.value_error("Single '}' encountered in format string"));
        } else {
            out.push(c);
            i += 1;
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floats_print_like_python() {
        assert_eq!(float_repr(1.0), "1.0");
        assert_eq!(float_repr(0.1), "0.1");
        assert_eq!(float_repr(1e16), "1e+16");
        assert_eq!(float_repr(1e15), "1000000000000000.0");
        assert_eq!(float_repr(0.0001), "0.0001");
        assert_eq!(float_repr(0.00001), "1e-05");
        assert_eq!(float_repr(-2.5), "-2.5");
        assert_eq!(float_repr(1.0 / 3.0), "0.3333333333333333");
        assert_eq!(float_repr(123456789.123), "123456789.123");
        assert_eq!(float_repr(f64::INFINITY), "inf");
    }

    #[test]
    fn specs() {
        let s = parse_spec(">10.3f").unwrap();
        assert_eq!(format_float(3.14159, &s).unwrap(), "     3.142");
        assert_eq!(format_int(1234567, &parse_spec(",").unwrap()).unwrap(), "1,234,567");
        assert_eq!(format_int(255, &parse_spec("#x").unwrap()).unwrap(), "0xff");
        assert_eq!(format_int(5, &parse_spec("05d").unwrap()).unwrap(), "00005");
        assert_eq!(format_str("abc", &parse_spec("^7").unwrap()).unwrap(), "  abc  ");
        assert_eq!(format_float(0.25, &parse_spec(".1%").unwrap()).unwrap(), "25.0%");
        assert_eq!(format_float(1234.5, &parse_spec(".2e").unwrap()).unwrap(), "1.23e+03");
        assert_eq!(format_float(0.000012345, &parse_spec("g").unwrap()).unwrap(), "1.2345e-05");
        assert_eq!(format_float(100.0, &parse_spec("g").unwrap()).unwrap(), "100");
        assert_eq!(format_float(2.5, &parse_spec(".3g").unwrap()).unwrap(), "2.5");
    }
}
