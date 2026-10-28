use std::collections::HashMap;

use super::interner::*;
use super::raw_const::FlatConst;
use super::raw_const::RawBsMeth;
use super::raw_const::RawConst;
use super::types::*;
use crate::assemble::span::Error;
use crate::assemble::span::ErrorMaker;
use crate::assemble::span::Span;
use crate::assemble::writer::BufWriter;
use crate::util::mstr;

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

pub enum BsAttrNameNeeded<'a> {
    Always(Span<'a>),
    IfPresent(Span<'a>),
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

    pub(super) interner: Interner<'a>,
    // Allocated slot for each interned constant, indexed by ConstId
    slots: Vec<Option<u16>>,
    pending: Vec<(u16, Span<'a>, ConstId)>,
    allocator: ConstSlotAllocator,
    raw_bs_defs: Vec<(u16, Span<'a>, BsId)>,
}
impl<'a> PoolBuilder<'a> {
    pub(super) fn new(
        error_maker: ErrorMaker<'a>,
        interner: Interner<'a>,
        mut raw_defs: Vec<(u16, Span<'a>, ConstId)>,
        mut raw_bs_defs: Vec<(u16, Span<'a>, BsId)>,
    ) -> Self {
        raw_defs.sort_unstable_by_key(|p| p.0);
        raw_bs_defs.sort_unstable_by_key(|p| !p.0); // use bitwise not to reverse sort order

        let mut ranges = Vec::new();
        let mut first = 1;
        for &(ind, _, id) in &raw_defs {
            if ind > first {
                ranges.push(Range { first, last: ind - 1 });
            }
            first = ind + if interner.get_const(id).is_long() { 2 } else { 1 };
        }
        if first <= 65534 {
            ranges.push(Range { first, last: 65534 });
        }

        Self {
            error_maker,
            interner,
            slots: Vec::new(),
            // Raw defs are added to pending directly, without recording their index in slots. This means that
            // allocate won't reuse them for equal inline constants, which instead get their own slot.
            // Suppose a class has .const [5] = Utf8 foo and later uses an inline Class foo. The inline
            // Utf8 foo interns to the same ConstId as the raw def's contents. The Or doesn't keep them apart,
            // because both are the identical FlatConst::Utf8(foo). The only thing that keeps them apart is that
            // new puts (5, span, id) in pending without setting slots[id] = Some(5). When the inline constant
            // comes through allocate, the early exit finds nothing, and it gets a fresh slot. If new did
            // record the slot, the inline constant would silently reuse [5].
            pending: raw_defs,
            allocator: ConstSlotAllocator::new(ranges),
            raw_bs_defs,
        }
    }

    pub(super) fn allocate(&mut self, span: Span<'a>, id: ConstId, is_ldc: bool) -> Result<u16, Error> {
        if let Some(&Some(ind)) = self.slots.get(id.index()) {
            return Ok(ind);
        }

        let slot = if self.interner.get_const(id).is_long() {
            self.allocator.alloc_wide()
        } else {
            self.allocator.alloc(is_ldc)
        };
        let ind = slot.ok_or_else(|| {
            self.error_maker
                .error1("Exceeded maximum 65534 constants per class in constant pool", span)
        })?;

        if self.slots.len() <= id.index() {
            self.slots.resize(id.index() + 1, None);
        }
        self.slots[id.index()] = Some(ind);
        self.pending.push((ind, span, id));
        Ok(ind)
    }

    fn fix(&mut self, r: SpannedConstRef<'a>) -> Result<u16, Error> {
        match r {
            Or::A(ind) => Ok(ind),
            Or::B(id) => self.allocate(id.span, id.v, false),
        }
    }

    fn fix_bs(&mut self, r: SpannedBsRef<'a>, bs_table: &mut BootstrapBuilder) -> Result<u16, Error> {
        match r {
            Or::A(ind) => Ok(ind),
            Or::B(id) => {
                let bs = self.resolve_bs_sub_refs(id.v)?;
                bs_table.allocate(bs).ok_or_else(|| {
                    self.error_maker
                        .error1("Exceeded maximum 65535 bootstrap methods per class", id.span)
                })
            }
        }
    }

    fn resolve_cp_sub_refs(&mut self, id: ConstId, bs_table: &mut BootstrapBuilder) -> Result<RawConst<'a>, Error> {
        self.interner.get_const(id).try_map(
            &mut (self, bs_table),
            |(s, _), r| s.fix(r),
            |(s, bs_table), r| s.fix_bs(r, bs_table),
        )
    }

    fn resolve_bs_sub_refs(&mut self, id: BsId) -> Result<RawBsMeth, Error> {
        let bs = self.interner.get_bs(id).clone();
        let mhref = self.fix(bs.mhref)?;
        let args = bs.args.into_iter().map(|r| self.fix(r)).collect::<Result<_, _>>()?;
        Ok(RawBsMeth { mhref, args })
    }

    pub fn build(
        mut self,
        cpwriter: &mut BufWriter,
        bs_name_needed: BsAttrNameNeeded<'a>,
        class_name_ind: u16,
    ) -> Result<(BsAttrInfo, Option<&'a mstr>), Error> {
        let raw_bs_defs = std::mem::take(&mut self.raw_bs_defs);
        let resolved_bs_defs = raw_bs_defs
            .into_iter()
            .map(|(ind, _span, id)| Ok((ind, self.resolve_bs_sub_refs(id)?)))
            .collect::<Result<_, _>>()?;
        let mut bs_table = BootstrapBuilder::new(resolved_bs_defs);

        let filler_const = RawConst::Utf8(mstr::new(b""));
        // This table is fixed size and hence could live on the stack,
        // but put it on the heap instead so the assembler still works
        // when run with a very small stack.
        let mut table = vec![Some(filler_const); 65536];
        table[0] = None;

        while let Some((ind, _span, id)) = self.pending.pop() {
            let is_long = self.interner.get_const(id).is_long();
            assert!(table[ind as usize] == Some(filler_const));
            table[ind as usize] = Some(self.resolve_cp_sub_refs(id, &mut bs_table)?);
            if is_long {
                assert!(table[ind as usize + 1] == Some(filler_const));
                table[ind as usize + 1] = None;
            }
        }

        let (buf, num_bs) = bs_table.finish();
        let name_needed = match bs_name_needed {
            BsAttrNameNeeded::Always(span) => Some(span),
            BsAttrNameNeeded::IfPresent(span) => (num_bs > 0).then_some(span),
            BsAttrNameNeeded::Never => None,
        };

        let name = if let Some(span) = name_needed {
            let s = mstr::new(b"BootstrapMethods");
            let id = self.interner.intern_const(FlatConst::Utf8(s));
            let slot = self.allocate(span, id, false)?;
            table[slot as usize] = Some(RawConst::Utf8(s));
            Some(slot)
        } else {
            None
        };
        let bs_info = BsAttrInfo { buf, num_bs, name };

        let num_consts = if let Some(range) = self.allocator.ranges.last() {
            // todo - test this
            if range.last == 65534 { range.first } else { 65535 }
        } else {
            65535 // if there were no ranges, that means every possible slot was occupied by raw refs
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
