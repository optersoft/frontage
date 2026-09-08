//! A library in Rust, compiled to WebAssembly, called from Python in the browser.
//!
//! Deliberately `no_std` and allocator-free: the numbers live in one static buffer that
//! JavaScript writes into and these functions read. That is the whole trick behind the size
//! (this is under a kilobyte) and behind the cost model — one copy in, one number out, rather
//! than a crossing per element.
//!
//!     cargo build --release --target wasm32-unknown-unknown
//!
//! and the file is `target/wasm32-unknown-unknown/release/statlib.wasm`.

#![no_std]

use core::panic::PanicInfo;

/// How many values fit at once. 65,536 f64 is 512 KB of the module's memory; raise it and the
/// module's memory grows with it.
const CAPACITY: usize = 65_536;

static mut VALUES: [f64; CAPACITY] = [0.0; CAPACITY];
/// A histogram writes here, so the caller reads counts without a second buffer to manage.
const BINS: usize = 256;
static mut COUNTS: [u32; BINS] = [0; BINS];

#[panic_handler]
fn panic(_: &PanicInfo) -> ! {
    // `panic = "abort"` and no unwinding: a panic traps, which is what a caller sees.
    core::arch::wasm32::unreachable()
}

/// Where to write the values. The caller copies into `HEAPF64` at this offset.
#[no_mangle]
pub extern "C" fn values_ptr() -> *const f64 {
    &raw const VALUES as *const f64
}

/// How many values fit, so the caller can refuse a longer list rather than write past the end.
#[no_mangle]
pub extern "C" fn capacity() -> usize {
    CAPACITY
}

/// Where the histogram's counts land, and how many there are.
#[no_mangle]
pub extern "C" fn counts_ptr() -> *const u32 {
    &raw const COUNTS as *const u32
}

#[no_mangle]
pub extern "C" fn bins() -> usize {
    BINS
}

fn values(len: usize) -> &'static [f64] {
    let len = if len > CAPACITY { CAPACITY } else { len };
    unsafe { core::slice::from_raw_parts(&raw const VALUES as *const f64, len) }
}

#[no_mangle]
pub extern "C" fn mean(len: usize) -> f64 {
    let data = values(len);
    if data.is_empty() {
        return 0.0;
    }
    let mut total = 0.0;
    for value in data {
        total += *value;
    }
    total / data.len() as f64
}

/// The sample standard deviation, in one pass (Welford), which is the point of doing it here
/// rather than in a Python loop.
#[no_mangle]
pub extern "C" fn stddev(len: usize) -> f64 {
    let data = values(len);
    if data.len() < 2 {
        return 0.0;
    }
    let (mut count, mut average, mut squares) = (0.0f64, 0.0f64, 0.0f64);
    for value in data {
        count += 1.0;
        let delta = *value - average;
        average += delta / count;
        squares += delta * (*value - average);
    }
    sqrt(squares / (count - 1.0))
}

/// `no_std` has no `f64::sqrt` (it is in `std`, over the intrinsic). Newton's method converges
/// in a handful of steps and keeps this crate free of a dependency for one call.
fn sqrt(x: f64) -> f64 {
    if x <= 0.0 {
        return 0.0;
    }
    let mut guess = x;
    let mut i = 0;
    while i < 32 {
        let next = 0.5 * (guess + x / guess);
        if next == guess {
            break;
        }
        guess = next;
        i += 1;
    }
    guess
}

#[no_mangle]
pub extern "C" fn minimum(len: usize) -> f64 {
    let data = values(len);
    let mut lowest = f64::INFINITY;
    for value in data {
        if *value < lowest {
            lowest = *value;
        }
    }
    lowest
}

#[no_mangle]
pub extern "C" fn maximum(len: usize) -> f64 {
    let data = values(len);
    let mut highest = f64::NEG_INFINITY;
    for value in data {
        if *value > highest {
            highest = *value;
        }
    }
    highest
}

/// Counts into `COUNTS[0..count]`, over `[low, high)`. Returns how many bins were written.
#[no_mangle]
pub extern "C" fn histogram(len: usize, count: usize, low: f64, high: f64) -> usize {
    let count = if count == 0 || count > BINS { BINS } else { count };
    let counts = unsafe { core::slice::from_raw_parts_mut(&raw mut COUNTS as *mut u32, count) };
    for slot in counts.iter_mut() {
        *slot = 0;
    }
    if high <= low {
        return count;
    }
    let width = (high - low) / count as f64;
    for value in values(len) {
        if *value < low || *value > high {
            continue;
        }
        let mut index = ((*value - low) / width) as usize;
        if index >= count {
            index = count - 1; // the top edge belongs to the last bin
        }
        counts[index] += 1;
    }
    count
}
