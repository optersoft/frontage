//! Signal processing for the browser: an FFT, the windows around it, a Welch power spectral
//! density and a spectrogram.
//!
//! Shaped for the boundary it lives on. The two WebAssembly modules have separate memories, so
//! a list does not cross — it is copied, one element at a time. Everything here therefore works
//! on **one static buffer** the caller fills once (`signal_ptr`), and answers into **one static
//! output buffer** (`out_ptr`) the caller reads. A frame of a spectrogram never crosses on its
//! own.
//!
//! ```text
//! cargo build --release --target wasm32-unknown-unknown
//! ```

// `no_std` in the browser and `std` everywhere else. The tests below check this crate's own
// `cos`, `ln` and `sqrt` against the ones in `std` — which is only possible on a host build,
// and is the reason the attribute is on the target rather than on `test`.
#![cfg_attr(target_arch = "wasm32", no_std)]

use core::f64::consts::PI;

/// The longest signal that fits: 131,072 samples is 1 MB of f64, and about 8 seconds at the
/// 16 kHz a gravitational-wave or audio demo uses.
pub const CAPACITY: usize = 131_072;
/// The largest transform, and so the most a single `bandpass` can cover: 16,384 samples is
/// four seconds at 4 kHz, which is the shape of the signals this is for.
pub const MAX_FFT: usize = 16_384;
/// What one answer may be: 65,536 f64 holds a 512-bin spectrogram 128 frames deep.
pub const OUT: usize = 65_536;

static mut SIGNAL: [f64; CAPACITY] = [0.0; CAPACITY];
static mut RE: [f64; MAX_FFT] = [0.0; MAX_FFT];
static mut IM: [f64; MAX_FFT] = [0.0; MAX_FFT];
static mut WINDOW: [f64; MAX_FFT] = [0.0; MAX_FFT];
static mut RESULT: [f64; OUT] = [0.0; OUT];

#[cfg(target_arch = "wasm32")]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    core::arch::wasm32::unreachable()
}

// -- the boundary ------------------------------------------------------------------------

#[no_mangle]
pub extern "C" fn signal_ptr() -> *const f64 {
    &raw const SIGNAL as *const f64
}

#[no_mangle]
pub extern "C" fn capacity() -> usize {
    CAPACITY
}

#[no_mangle]
pub extern "C" fn out_ptr() -> *const f64 {
    &raw const RESULT as *const f64
}

#[no_mangle]
pub extern "C" fn out_capacity() -> usize {
    OUT
}

// -- the mathematics ---------------------------------------------------------------------

/// `sqrt`, `cos` and `ln` by hand: `no_std` has no libm, and one dependency for three
/// functions is not worth the download.
fn sqrt(x: f64) -> f64 {
    if x <= 0.0 {
        return 0.0;
    }
    let mut guess = x;
    let mut i = 0;
    while i < 40 {
        let next = 0.5 * (guess + x / guess);
        if next == guess {
            break;
        }
        guess = next;
        i += 1;
    }
    guess
}

/// cos over the reduced argument, by its Taylor series: the windows and the twiddles are the
/// only callers, and both stay inside a turn.
fn cos(x: f64) -> f64 {
    let mut x = x % (2.0 * PI);
    if x < 0.0 {
        x = -x;
    }
    if x > PI {
        x = 2.0 * PI - x;
    }
    let (mut term, mut total, x2) = (1.0f64, 1.0f64, x * x);
    let mut n = 1;
    while n < 12 {
        term *= -x2 / (((2 * n - 1) * (2 * n)) as f64);
        total += term;
        n += 1;
    }
    total
}

fn sin(x: f64) -> f64 {
    cos(x - PI / 2.0)
}

/// `ln`, for decibels. `ln(x) = 2 * atanh((x-1)/(x+1))`, which converges quickly once the
/// exponent is taken out.
fn ln(x: f64) -> f64 {
    if x <= 0.0 {
        return f64::NEG_INFINITY;
    }
    let mut value = x;
    let mut exponent = 0i32;
    while value > 2.0 {
        value /= 2.0;
        exponent += 1;
    }
    while value < 0.5 {
        value *= 2.0;
        exponent -= 1;
    }
    let t = (value - 1.0) / (value + 1.0);
    let (t2, mut term, mut total) = (t * t, t, t);
    let mut n = 1;
    while n < 20 {
        term *= t2;
        total += term / ((2 * n + 1) as f64);
        n += 1;
    }
    2.0 * total + (exponent as f64) * core::f64::consts::LN_2
}

/// An in-place radix-2 FFT over `re`/`im`, both `n` long with `n` a power of two.
fn fft(re: &mut [f64], im: &mut [f64], n: usize) {
    // Bit-reversal permutation.
    let mut j = 0usize;
    for i in 1..n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j |= bit;
        if i < j {
            re.swap(i, j);
            im.swap(i, j);
        }
    }
    let mut length = 2;
    while length <= n {
        let angle = -2.0 * PI / length as f64;
        let (wr, wi) = (cos(angle), sin(angle));
        let mut start = 0;
        while start < n {
            let (mut cr, mut ci) = (1.0f64, 0.0f64);
            for k in 0..length / 2 {
                let (a, b) = (start + k, start + k + length / 2);
                let (tr, ti) = (cr * re[b] - ci * im[b], cr * im[b] + ci * re[b]);
                re[b] = re[a] - tr;
                im[b] = im[a] - ti;
                re[a] += tr;
                im[a] += ti;
                let next = (cr * wr - ci * wi, cr * wi + ci * wr);
                cr = next.0;
                ci = next.1;
            }
            start += length;
        }
        length <<= 1;
    }
}

/// A Hann window of `n` points, cached in `WINDOW` because every frame uses the same one.
fn hann(n: usize) -> &'static [f64] {
    let window = unsafe { core::slice::from_raw_parts_mut(&raw mut WINDOW as *mut f64, n) };
    for (i, slot) in window.iter_mut().enumerate() {
        *slot = 0.5 - 0.5 * cos(2.0 * PI * i as f64 / (n - 1) as f64);
    }
    window
}

fn signal(len: usize) -> &'static [f64] {
    let len = if len > CAPACITY { CAPACITY } else { len };
    unsafe { core::slice::from_raw_parts(&raw const SIGNAL as *const f64, len) }
}

fn result(len: usize) -> &'static mut [f64] {
    let len = if len > OUT { OUT } else { len };
    unsafe { core::slice::from_raw_parts_mut(&raw mut RESULT as *mut f64, len) }
}

/// One windowed frame's power, into `RE`/`IM`; leaves `|X|²` in `RE[0..n/2+1]`.
fn frame_power(data: &[f64], n: usize) {
    let window = hann(n);
    let re = unsafe { core::slice::from_raw_parts_mut(&raw mut RE as *mut f64, n) };
    let im = unsafe { core::slice::from_raw_parts_mut(&raw mut IM as *mut f64, n) };
    for i in 0..n {
        re[i] = data.get(i).copied().unwrap_or(0.0) * window[i];
        im[i] = 0.0;
    }
    fft(re, im, n);
    for i in 0..=n / 2 {
        re[i] = re[i] * re[i] + im[i] * im[i];
    }
}

/// The window's power, so a PSD is normalised the way Welch's method asks.
fn window_power(n: usize) -> f64 {
    let window = hann(n);
    let mut total = 0.0;
    for value in &window[..n] {
        total += value * value;
    }
    total
}

// -- what the page calls -----------------------------------------------------------------

/// Welch's power spectral density of the first `len` samples: `n`-point frames, `hop` apart,
/// averaged. Writes `n/2 + 1` values into the output buffer and returns how many.
///
/// `sample_rate` scales the result to power per hertz; pass 1.0 for power per bin.
#[no_mangle]
pub extern "C" fn psd(len: usize, n: usize, hop: usize, sample_rate: f64) -> usize {
    if n < 2 || n > MAX_FFT || n & (n - 1) != 0 || hop == 0 {
        return 0;
    }
    let data = signal(len);
    let bins = n / 2 + 1;
    let out = result(bins);
    for slot in out.iter_mut() {
        *slot = 0.0;
    }
    let mut frames = 0usize;
    let mut start = 0usize;
    while start + n <= data.len() {
        frame_power(&data[start..start + n], n);
        let power = unsafe { core::slice::from_raw_parts(&raw const RE as *const f64, bins) };
        for (slot, value) in out.iter_mut().zip(power) {
            *slot += *value;
        }
        frames += 1;
        start += hop;
    }
    if frames == 0 {
        return bins;
    }
    let scale = 1.0 / (frames as f64 * sample_rate * window_power(n));
    for (i, slot) in out.iter_mut().enumerate() {
        // Every bin but DC and Nyquist stands for a positive and a negative frequency.
        let fold = if i == 0 || i == bins - 1 { 1.0 } else { 2.0 };
        *slot *= scale * fold;
    }
    bins
}

/// A spectrogram: `frames` rows of `n/2 + 1` bins, `hop` apart, in decibels relative to the
/// loudest bin. Writes row-major into the output buffer and returns the number of rows.
#[no_mangle]
pub extern "C" fn spectrogram(len: usize, n: usize, hop: usize, floor_db: f64) -> usize {
    if n < 2 || n > MAX_FFT || n & (n - 1) != 0 || hop == 0 {
        return 0;
    }
    let data = signal(len);
    let bins = n / 2 + 1;
    let rows = if data.len() < n { 0 } else { (data.len() - n) / hop + 1 };
    let rows = if rows * bins > OUT { OUT / bins } else { rows };
    if rows == 0 {
        return 0;
    }
    let out = result(rows * bins);
    let mut peak = 0.0f64;
    for row in 0..rows {
        let start = row * hop;
        frame_power(&data[start..start + n], n);
        let power = unsafe { core::slice::from_raw_parts(&raw const RE as *const f64, bins) };
        for (i, value) in power.iter().enumerate() {
            out[row * bins + i] = *value;
            if *value > peak {
                peak = *value;
            }
        }
    }
    // Decibels against the loudest bin, floored: what a spectrogram is always drawn in, and
    // doing it here keeps `rows * bins` numbers from crossing twice.
    let reference = if peak > 0.0 { peak } else { 1.0 };
    for slot in out.iter_mut() {
        let db = 10.0 * ln(*slot / reference) / core::f64::consts::LN_10;
        *slot = if db < floor_db || !(db == db) { floor_db } else { db };
    }
    rows
}

/// The root mean square of the first `len` samples — the one number that says "how loud",
/// and what a whitening or a normalisation step divides by.
#[no_mangle]
pub extern "C" fn rms(len: usize) -> f64 {
    let data = signal(len);
    if data.is_empty() {
        return 0.0;
    }
    let mut total = 0.0;
    for value in data {
        total += *value * *value;
    }
    sqrt(total / data.len() as f64)
}

/// How many bins a spectrogram row has, so the caller can shape what it read.
#[no_mangle]
pub extern "C" fn bins_for(n: usize) -> usize {
    n / 2 + 1
}

/// Zero every bin outside `[low, high]` hertz and transform back: a brick-wall bandpass, in
/// place, over the first `len` samples.
///
/// Returns the number of samples it actually filtered — the largest power of two that fits,
/// capped at `MAX_FFT`, because the transform needs one. **The caller must treat that as the
/// new length of the signal**, or it will go on measuring samples this never touched, which
/// looks exactly like a filter that does nothing.
#[no_mangle]
pub extern "C" fn bandpass(len: usize, sample_rate: f64, low: f64, high: f64) -> usize {
    let n = MAX_FFT.min(largest_power_of_two(len.min(CAPACITY)));
    if n < 2 {
        return 0;
    }
    let data = unsafe { core::slice::from_raw_parts_mut(&raw mut SIGNAL as *mut f64, n) };
    let re = unsafe { core::slice::from_raw_parts_mut(&raw mut RE as *mut f64, n) };
    let im = unsafe { core::slice::from_raw_parts_mut(&raw mut IM as *mut f64, n) };
    re[..n].copy_from_slice(&data[..n]);
    for slot in im.iter_mut() {
        *slot = 0.0;
    }
    fft(re, im, n);
    let resolution = sample_rate / n as f64;
    for i in 0..n {
        let frequency = if i <= n / 2 { i as f64 } else { (n - i) as f64 } * resolution;
        if frequency < low || frequency > high {
            re[i] = 0.0;
            im[i] = 0.0;
        }
    }
    // The inverse transform is the forward one over the conjugate, scaled.
    for slot in im.iter_mut() {
        *slot = -*slot;
    }
    fft(re, im, n);
    let scale = 1.0 / n as f64;
    for i in 0..n {
        data[i] = re[i] * scale;
    }
    n
}

fn largest_power_of_two(n: usize) -> usize {
    let mut value = 1;
    while value * 2 <= n {
        value *= 2;
    }
    value
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The buffers above are static, which is the whole point of the design and also means two
    /// tests must not be in them at once. Every test that loads a signal takes this first.
    static BUFFERS: std::sync::Mutex<()> = std::sync::Mutex::new(());

    fn load(values: &[f64]) {
        let buffer = unsafe { core::slice::from_raw_parts_mut(&raw mut SIGNAL as *mut f64, values.len()) };
        buffer.copy_from_slice(values);
    }

    fn naive_dft(data: &[f64]) -> Vec<f64> {
        let n = data.len();
        (0..=n / 2)
            .map(|k| {
                let (mut re, mut im) = (0.0f64, 0.0f64);
                for (t, value) in data.iter().enumerate() {
                    let angle = -2.0 * PI * (k * t) as f64 / n as f64;
                    re += value * angle.cos();
                    im += value * angle.sin();
                }
                re * re + im * im
            })
            .collect()
    }

    #[test]
    fn the_fft_agrees_with_a_naive_dft() {
        let n = 64;
        let data: Vec<f64> = (0..n).map(|i| (2.0 * PI * 5.0 * i as f64 / n as f64).sin()).collect();
        let expected = naive_dft(&data);
        let mut re = data.clone();
        let mut im = vec![0.0; n];
        fft(&mut re, &mut im, n);
        for k in 0..=n / 2 {
            let got = re[k] * re[k] + im[k] * im[k];
            assert!((got - expected[k]).abs() < 1e-6 * (1.0 + expected[k]), "bin {k}: {got} vs {}", expected[k]);
        }
    }

    #[test]
    fn cos_sin_ln_and_sqrt_are_good_enough() {
        for i in 0..100 {
            let x = i as f64 * 0.0628;
            assert!((cos(x) - x.cos()).abs() < 1e-9, "cos({x})");
            assert!((sin(x) - x.sin()).abs() < 1e-9, "sin({x})");
        }
        for x in [0.001f64, 0.5, 1.0, 2.0, 10.0, 1e6] {
            assert!((ln(x) - x.ln()).abs() < 1e-9, "ln({x})");
            assert!((sqrt(x) - x.sqrt()).abs() < 1e-9, "sqrt({x})");
        }
    }

    #[test]
    fn a_psd_puts_a_tone_in_the_right_bin() {
        let _held = BUFFERS.lock().unwrap_or_else(|e| e.into_inner());
        let (rate, n) = (1024.0, 256);
        let tone = 64.0;
        let data: Vec<f64> = (0..2048).map(|i| (2.0 * PI * tone * i as f64 / rate).sin()).collect();
        load(&data);
        let bins = psd(data.len(), n, n / 2, rate);
        assert_eq!(bins, n / 2 + 1);
        let out = result(bins);
        let peak = (0..bins).max_by(|a, b| out[*a].partial_cmp(&out[*b]).unwrap()).unwrap();
        assert_eq!(peak, (tone / (rate / n as f64)) as usize);
    }

    #[test]
    fn a_spectrogram_is_decibels_under_zero() {
        let _held = BUFFERS.lock().unwrap_or_else(|e| e.into_inner());
        let data: Vec<f64> = (0..4096).map(|i| (2.0 * PI * 50.0 * i as f64 / 1024.0).sin()).collect();
        load(&data);
        let rows = spectrogram(data.len(), 256, 128, -90.0);
        assert!(rows > 20, "rows {rows}");
        let out = result(rows * 129);
        assert!(out.iter().all(|db| *db <= 0.001 && *db >= -90.0));
        assert!(out.iter().any(|db| *db > -1.0), "nothing near the peak");
    }

    #[test]
    fn a_bandpass_says_how_much_it_filtered() {
        let _held = BUFFERS.lock().unwrap_or_else(|e| e.into_inner());
        let data: Vec<f64> = (0..3000).map(|i| (i as f64 * 0.1).sin()).collect();
        load(&data);
        // The largest power of two that fits, and never more than one transform's worth.
        assert_eq!(bandpass(3000, 1024.0, 0.0, 512.0), 2048);
        load(&std::vec![1.0; 40_000]);
        assert_eq!(bandpass(40_000, 1024.0, 0.0, 512.0), MAX_FFT);
    }

    #[test]
    fn an_empty_band_leaves_nothing() {
        let _held = BUFFERS.lock().unwrap_or_else(|e| e.into_inner());
        let data: Vec<f64> = (0..1024).map(|i| (2.0 * PI * 50.0 * i as f64 / 1024.0).sin()).collect();
        load(&data);
        let kept = bandpass(data.len(), 1024.0, 400.0, 200.0); // high below low: nothing survives
        assert_eq!(kept, 1024);
        assert!(rms(kept) < 1e-9, "rms {}", rms(kept));
    }

    #[test]
    fn rms_is_the_amplitude_of_a_sine_over_root_two() {
        let _held = BUFFERS.lock().unwrap_or_else(|e| e.into_inner());
        let data: Vec<f64> = (0..1024).map(|i| 3.0 * (2.0 * PI * 4.0 * i as f64 / 1024.0).sin()).collect();
        load(&data);
        assert!((rms(data.len()) - 3.0 / 2.0f64.sqrt()).abs() < 1e-9);
    }

    #[test]
    fn a_bandpass_keeps_what_it_is_told_to() {
        let _held = BUFFERS.lock().unwrap_or_else(|e| e.into_inner());
        let rate = 1024.0;
        let data: Vec<f64> = (0..1024)
            .map(|i| {
                let t = i as f64 / rate;
                (2.0 * PI * 50.0 * t).sin() + (2.0 * PI * 300.0 * t).sin()
            })
            .collect();
        load(&data);
        assert_eq!(bandpass(data.len(), rate, 20.0, 100.0), 1024);
        let bins = psd(1024, 256, 128, rate);
        let out = result(bins);
        let resolution = rate / 256.0;
        let kept = out[(50.0 / resolution) as usize];
        let gone = out[(300.0 / resolution) as usize];
        assert!(kept > gone * 1e6, "kept {kept}, gone {gone}");
    }
}
