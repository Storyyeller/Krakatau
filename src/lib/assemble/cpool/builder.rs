use std::collections::HashMap;

use super::raw_const::RawBsMeth;
use super::raw_const::RawConst;
use super::types::*;
use crate::lib::assemble::span::Error;
use crate::lib::assemble::span::ErrorMaker;
use crate::lib::assemble::span::Span;
use crate::lib::assemble::span::Spanned;
use crate::lib::assemble::writer::BufWriter;
use crate::lib::util::BStr;

#[derive(Debug)]
struct Range {
    first: u16,
    last: u16,
}
impl Range {
    fn len(&self) -> usize {
        (1 + self.last as usize) - self.first as usize
    }
}

struct ConstSlotAllocator {
    ranges: Vec<Range>,
    // indexes into the ranges array
    odd_ptr: usize,
    wide_ptr: usize,
    ptr: usize,
}
impl ConstSlotAllocator {
    fn new(ranges: Vec<Range>) -> Self {
        Self {
            ranges,
            odd_ptr: 0,
            wide_ptr: 0,
            ptr: 0,
        }
    }

    fn alloc(&mut self, is_ldc: bool) -> Option<u16> {
        while let Some(r) = self.ranges.get_mut(self.odd_ptr) {
            if r.len() % 2 == 0 {
                self.odd_ptr += 1;
            } else if is_ldc && r.first > 255 {
                break;
            } else {
                self.odd_ptr += 1;
                let chosen = r.first;
                r.first += 1;
                return Some(chosen);
            }
        }

        while let Some(r) = self.ranges.get_mut(self.ptr) {
            if is_ldc && r.first > 255 {
                return None;
            }

            if r.len() >= 1 {
                let chosen = r.first;
                r.first += 1;
                return Some(chosen);
            } else {
                self.ptr += 1;
            }
        }

        None
    }

    fn alloc_wide(&mut self) -> Option<u16> {
        while let Some(r) = self.ranges.get_mut(self.wide_ptr) {
            if r.len() >= 2 {
                let chosen = r.first;
                r.first += 2;
                return Some(chosen);
            } else {
                self.wide_ptr += 1;
            }
        }

        None
    }
}

pub enum BsAttrNameNeeded {
    Always,
    IfPresent,
    Never,
}

#[derive(Debug)]
pub struct BsAttrInfo {
    pub buf: Vec<u8>,
    pub num_bs: u16,
    pub name: Option<u16>,
}
impl BsAttrInfo {
    pub fn data_len(&self) -> Option<u32> {
        (2 + self.buf.len() as u64).try_into().ok()
    }
}

pub struct PoolBuilder<'a> {
    error_maker: ErrorMaker<'a>,

    pending: Vec<(u16, Spanned<'a, RawConstInline<'a>>)>,
    allocated: HashMap<RawConstInline<'a>, u16>,
    allocator: ConstSlotAllocator,
    raw_bs_defs: Vec<(u16, Spanned<'a, RawBsInline<'a>>)>,
}
impl<'a> PoolBuilder<'a> {
    pub fn new(
        error_maker: ErrorMaker<'a>,
        mut raw_defs: Vec<(u16, Spanned<'a, RawConstInline<'a>>)>,
        mut raw_bs_defs: Vec<(u16, Spanned<'a, RawBsInline<'a>>)>,
    ) -> Self {
        raw_defs.sort_unstable_by_key(|p| p.0);
        raw_bs_defs.sort_unstable_by_key(|p| !p.0); // use bitwise not to reverse sort order

        let mut ranges = Vec::new();
        let mut first = 1;
        for &(ind, ref c) in &raw_defs {
            if ind > first {
                ranges.push(Range { first, last: ind - 1 });
            }
            first = ind + if c.v.is_long() { 2 } else { 1 };
        }
        if first <= 65534 {
            ranges.push(Range { first, last: 65534 });
        }

        Self {
            error_maker,
            pending: raw_defs,
            allocated: HashMap::new(),
            allocator: ConstSlotAllocator::new(ranges),
            raw_bs_defs,
        }
    }

    pub fn allocate(&mut self, span: Span<'a>, c: RawConstInline<'a>, is_ldc: bool) -> Result<u16, Error> {
        // println!("allocate {} {:?} {}", span.0, c, is_ldc);
        self.allocated
            .get(&c)
            .copied()
            .or_else(|| {
                let slot = if c.is_long() {
                    self.allocator.alloc_wide()
                } else {
                    self.allocator.alloc(is_ldc)
                };
                if let Some(ind) = slot {
                    self.allocated.insert(c.clone(), ind);
                    self.pending.push((ind, span.of(c)));
                }
                slot
            })
            .ok_or_else(|| {
                self.error_maker
                    .error1("Exceeded maximum 65534 constants per class in constant pool", span)
            })
    }

    fn fix(&mut self, span: Span<'a>, r: Or<u16, impl ToConst<'a, u16>>) -> Result<u16, Error> {
        match r {
            Or::A(ind) => Ok(ind),
            Or::B(u) => self.allocate(span, u.to_const(), false),
        }
    }

    fn fix2(&mut self, r: Or<u16, Spanned<'a, impl ToConst<'a, u16>>>) -> Result<u16, Error> {
        match r {
            Or::A(ind) => Ok(ind),
            Or::B(u) => self.allocate(u.span, u.v.to_const(), false),
        }
    }

    fn fix_bs(&mut self, span: Span<'a>, r: RawBsRef<'a>, bs_table: &mut BootstrapBuilder) -> Result<u16, Error> {
        match r {
            Or::A(ind) => Ok(ind),
            Or::B(bs) => {
                let bs = self.resolve_bs_sub_refs(span.of(bs))?;
                bs_table.allocate(bs).ok_or_else(|| {
                    self.error_maker
                        .error1("Exceeded maximum 65535 bootstrap methods per class", span)
                })
            }
        }
    }

    fn resolve_cp_sub_refs(
        &mut self,
        c: Spanned<'a, RawConstInline<'a>>,
        bs_table: &mut BootstrapBuilder,
    ) -> Result<RawConst<'a>, Error> {
        let span = c.span;
        Ok(match c.v {
            InlineConst::Utf8(v) => RawConst::Utf8(v.0),

            InlineConst::Int(v) => RawConst::Int(v),
            InlineConst::Float(v) => RawConst::Float(v),
            InlineConst::Long(v) => RawConst::Long(v),
            InlineConst::Double(v) => RawConst::Double(v),
            InlineConst::Class(v) => RawConst::Class(self.fix(span, v)?),
            InlineConst::Str(v) => RawConst::Str(self.fix(span, v)?),
            InlineConst::Field(cls, nat) => RawConst::Field(self.fix(span, cls)?, self.fix(span, nat)?),
            InlineConst::Method(cls, nat) => RawConst::Method(self.fix(span, cls)?, self.fix(span, nat)?),
            InlineConst::InterfaceMethod(cls, nat) => RawConst::InterfaceMethod(self.fix(span, cls)?, self.fix(span, nat)?),
            InlineConst::NameAndType(u1, u2) => RawConst::NameAndType(self.fix(span, u1)?, self.fix(span, u2)?),

            InlineConst::MethodHandle(tag, val) => RawConst::MethodHandle(tag, self.fix(span, *val)?),
            InlineConst::MethodType(v) => RawConst::MethodType(self.fix(span, v)?),
            InlineConst::Dynamic(bs, nat) => RawConst::Dynamic(self.fix_bs(span, bs, bs_table)?, self.fix(span, nat)?),
            InlineConst::InvokeDynamic(bs, nat) => {
                RawConst::InvokeDynamic(self.fix_bs(span, bs, bs_table)?, self.fix(span, nat)?)
            }
            InlineConst::Module(v) => RawConst::Module(self.fix(span, v)?),
            InlineConst::Package(v) => RawConst::Package(self.fix(span, v)?),
        })
    }

    fn resolve_bs_sub_refs(&mut self, bs: Spanned<'a, RawBsInline<'a>>) -> Result<RawBsMeth, Error> {
        let mut iter = bs.v.0.into_iter();
        let mh = iter.next().unwrap();
        let mhref = self.fix2(mh)?;
        let args = iter.map(|c| self.fix2(c)).collect::<Result<_, _>>()?;
        Ok(RawBsMeth { mhref, args })
    }

    pub fn build(
        mut self,
        cpwriter: &mut BufWriter,
        bs_name_needed: BsAttrNameNeeded,
        class_name_ind: u16,
    ) -> Result<(BsAttrInfo, Option<&'a [u8]>), Error> {
        let raw_bs_defs = std::mem::take(&mut self.raw_bs_defs);
        let resolved_bs_defs = raw_bs_defs
            .into_iter()
            .map(|(ind, bs)| Ok((ind, self.resolve_bs_sub_refs(bs)?)))
            .collect::<Result<_, _>>()?;
        let mut bs_table = BootstrapBuilder::new(resolved_bs_defs);

        // Just choose a span arbitrarily to use for the case where we can't allocate
        // a name for an implicit BootstrapMethods attribute later.
        let bs_name_span = self.pending.last().map(|(_, c)| c.span);

        let filler_const = RawConst::Utf8(b"");
        let mut table = [Some(filler_const); 65535];
        table[0] = None;

        while let Some((ind, c)) = self.pending.pop() {
            let is_long = c.v.is_long();
            assert!(table[ind as usize] == Some(filler_const));
            table[ind as usize] = Some(self.resolve_cp_sub_refs(c, &mut bs_table)?);
            if is_long {
                assert!(table[ind as usize + 1] == Some(filler_const));
                table[ind as usize + 1] = None;
            }
        }

        let (buf, num_bs) = bs_table.finish();
        let name_needed = match bs_name_needed {
            BsAttrNameNeeded::Always => true,
            BsAttrNameNeeded::IfPresent => num_bs > 0,
            BsAttrNameNeeded::Never => false,
        };

        let name = if name_needed {
            let s = b"BootstrapMethods";
            let c = InlineConst::Utf8(BStr(s));
            let slot = self.allocate(bs_name_span.unwrap(), c, false)?;
            table[slot as usize] = Some(RawConst::Utf8(s));
            Some(slot)
        } else {
            None
        };
        let bs_info = BsAttrInfo { buf, num_bs, name };

        let num_consts = if let Some(range) = self.allocator.ranges.last() {
            // todo - test this
            if range.last == 65534 {
                range.first
            } else {
                65535
            }
        } else {
            65535
        };

        let class_name = match table[class_name_ind as usize] {
            Some(RawConst::Class(utf_ind)) => match table[utf_ind as usize] {
                Some(RawConst::Utf8(s)) => Some(s),
                _ => None,
            },
            _ => None,
        };

        let w = cpwriter;
        w.u16(num_consts);
        for c in &table[1..num_consts as usize] {
            // for (i, c) in table[..num_consts as usize].into_iter().enumerate() {
            //     println!("[{}] {:?}", i, c);
            if let Some(c) = c {
                c.write(w);
            }
        }

        Ok((bs_info, class_name))
    }
}

struct BootstrapBuilder {
    w: BufWriter,

    pending_bs_defs: Vec<(u16, RawBsMeth)>,
    next_bs_ind: u16,
    allocated: HashMap<RawBsMeth, u16>,
}
impl BootstrapBuilder {
    fn new(pending_bs_defs: Vec<(u16, RawBsMeth)>) -> Self {
        Self {
            w: BufWriter::default(),
            pending_bs_defs,
            next_bs_ind: 0,
            allocated: HashMap::new(),
        }
    }

    fn allocate(&mut self, bs: RawBsMeth) -> Option<u16> {
        self.allocated.get(&bs).copied().or_else(|| {
            while self.pending_bs_defs.last().map(|&(ind, _)| ind) == Some(self.next_bs_ind) {
                let (_, bs) = self.pending_bs_defs.pop().unwrap();
                bs.write(&mut self.w);
                assert!(self.next_bs_ind < u16::MAX);
                self.next_bs_ind += 1;
            }

            if self.next_bs_ind == u16::MAX {
                return None;
            }
            let slot = self.next_bs_ind;
            bs.write(&mut self.w);
            self.next_bs_ind += 1;
            self.allocated.insert(bs, slot);

            Some(slot)
        })
    }

    fn finish(mut self) -> (Vec<u8>, u16) {
        while let Some((ind, bs)) = self.pending_bs_defs.pop() {
            assert!(ind >= self.next_bs_ind);
            while self.next_bs_ind <= ind {
                bs.write(&mut self.w);
                self.next_bs_ind += 1;
            }
        }

        (self.w.into_buf(), self.next_bs_ind)
    }
}
