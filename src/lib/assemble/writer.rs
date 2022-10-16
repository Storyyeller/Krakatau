use std::fmt::Debug;
use std::sync::atomic::AtomicBool;

use super::cpool::types;
use super::cpool::Or;
use crate::lib::assemble::span::Span;
use crate::lib::assemble::span::Spanned;

#[derive(Debug)]
pub struct Placeholder<const N: usize>(usize);
impl<const N: usize> Placeholder<N> {
    fn new(off: usize) -> Self {
        Self(off)
    }

    fn increment(mut self, off: usize) -> Self {
        self.0 += off;
        self
    }

    fn into_range(self) -> std::ops::Range<usize> {
        let off = self.0;
        std::mem::forget(self); // avoid drop check
        off..(off + N)
    }
}
// temporary debug check to make sure placeholders are all used
pub static UNUSED_PH: AtomicBool = AtomicBool::new(false);
impl<const N: usize> Drop for Placeholder<N> {
    fn drop(&mut self) {
        UNUSED_PH.store(true, std::sync::atomic::Ordering::Relaxed);
    }
}
fn assert_zero(buf: &mut [u8]) -> &mut [u8] {
    assert!(buf.into_iter().all(|b| *b == 0));
    buf
}

#[derive(Default)]
pub struct BufWriter {
    buf: Vec<u8>,
}
impl BufWriter {
    pub fn into_buf(self) -> Vec<u8> {
        self.buf
    }

    pub fn len(&self) -> usize {
        self.buf.len()
    }

    // pub fn len(&self) -> usize {self.buf.len()}
    pub fn extend(&mut self, v: &BufWriter) {
        self.buf.extend_from_slice(&v.buf)
    }
    pub fn write(&mut self, v: &[u8]) {
        self.buf.extend_from_slice(v)
    }
    pub fn u8(&mut self, v: u8) {
        self.buf.push(v)
    }
    pub fn u16(&mut self, v: u16) {
        self.write(&v.to_be_bytes())
    }
    pub fn u32(&mut self, v: u32) {
        self.write(&v.to_be_bytes())
    }
    pub fn u64(&mut self, v: u64) {
        self.write(&v.to_be_bytes())
    }
    ///////////////////////////////////////////////////////////////////////////
    pub fn ph(&mut self) -> Placeholder<2> {
        let i = self.buf.len();
        self.u16(0);
        Placeholder::new(i)
    }

    pub fn ph8(&mut self) -> Placeholder<1> {
        let i = self.buf.len();
        self.u8(0);
        Placeholder::new(i)
    }

    pub fn ph32(&mut self) -> Placeholder<4> {
        let i = self.buf.len();
        self.u32(0);
        Placeholder::new(i)
    }

    pub fn fill(&mut self, ph: Placeholder<2>, v: u16) {
        assert_zero(&mut self.buf[ph.into_range()]).copy_from_slice(&v.to_be_bytes());
    }

    pub fn fill8(&mut self, ph: Placeholder<1>, v: u8) {
        assert_zero(&mut self.buf[ph.into_range()]).copy_from_slice(&v.to_be_bytes());
    }

    pub fn fill32(&mut self, ph: Placeholder<4>, v: u32) {
        assert_zero(&mut self.buf[ph.into_range()]).copy_from_slice(&v.to_be_bytes());
    }

    ///////////////////////////////////////////////////////////////////////////
    pub fn read_u16(&self, ind: usize) -> u16 {
        u16::from_be_bytes(self.buf[ind..ind + 2].try_into().unwrap())
    }
}
impl Debug for BufWriter {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // self.buf.fmt(f)
        f.write_fmt(format_args!("{:02X?}", self.buf))
    }
}

#[derive(Debug, Default)]
pub struct Writer<'a> {
    w: BufWriter,
    ldc_refs: Vec<(Placeholder<1>, types::SymSpanConst<'a>, Span<'a>)>,
    refs: Vec<(Placeholder<2>, types::SymSpanConst<'a>)>,
}
impl<'a> Writer<'a> {
    pub fn cp(&mut self, r: Or<types::RefType<'a>, Spanned<'a, impl types::ToConst<'a, types::RefType<'a>>>>) {
        let ph = self.ph();
        // self.refs.push((ph, r.map_b(types::ToConst::to_const)));
        self.refs.push((ph, r.map_b(|c| c.span.of(c.v.to_const()))));
    }

    pub fn cp_ldc(&mut self, r: types::SymSpanConst<'a>, ldc_span: Span<'a>) {
        let ph = self.ph8();
        self.ldc_refs.push((ph, r, ldc_span));
    }

    pub fn resolve_ldc_refs<E>(
        &mut self,
        mut f: impl FnMut(types::SymSpanConst<'a>, Span<'a>) -> Result<u8, E>,
    ) -> Result<(), E> {
        for (ph, r, ldc_span) in self.ldc_refs.drain(..) {
            self.w.fill8(ph, f(r, ldc_span)?);
        }
        Ok(())
    }

    pub fn resolve_refs<E>(mut self, mut f: impl FnMut(types::SymSpanConst<'a>) -> Result<u16, E>) -> Result<BufWriter, E> {
        assert!(self.ldc_refs.is_empty());
        for (ph, r) in self.refs.drain(..) {
            self.w.fill(ph, f(r)?);
        }
        Ok(self.w)
    }

    pub fn extend_from_writer(&mut self, w: Writer<'a>) {
        let off = self.len();
        self.buf.extend_from_slice(&w.buf);
        self.ldc_refs
            .extend(w.ldc_refs.into_iter().map(|(ph, cp, span)| (ph.increment(off), cp, span)));
        self.refs.extend(w.refs.into_iter().map(|(ph, cp)| (ph.increment(off), cp)));
    }
}
impl<'a> std::ops::Deref for Writer<'a> {
    type Target = BufWriter;

    fn deref(&self) -> &Self::Target {
        &self.w
    }
}
impl<'a> std::ops::DerefMut for Writer<'a> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.w
    }
}
