use std::collections::HashMap;
use std::hash::Hash;

use super::raw_const::FlatBsMeth;
use super::raw_const::FlatConst;
use super::types::*;
use crate::assemble::span::Spanned;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(super) struct ConstId(u32);
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(super) struct BsId(u32);

// Or::A is a raw reference (constant pool or bootstrap method index)
pub(super) type ConstRef = Or<u16, ConstId>;
pub(super) type BsRef = Or<u16, BsId>;
pub(super) type InternedConst<'a> = FlatConst<'a, ConstRef, BsRef>;
// Bootstrap arguments keep the span of their first occurrence for error reporting.
// Spanned ignores the span when comparing and hashing, so this doesn't affect deduplication.
pub(super) type InternedBs<'a> = FlatBsMeth<Or<u16, Spanned<'a, ConstId>>>;

// Assigns ids to constants and bootstrap methods. Children are always interned before
// their parents, so equal constants always get equal ids.
struct Table<T> {
    vals: Vec<T>,
    ids: HashMap<T, u32>,
}
impl<T: Clone + Eq + Hash> Table<T> {
    fn intern(&mut self, v: T) -> u32 {
        if let Some(&id) = self.ids.get(&v) {
            return id;
        }
        let id = self.vals.len().try_into().unwrap();
        self.vals.push(v.clone());
        self.ids.insert(v, id);
        id
    }
}
impl<T> Default for Table<T> {
    fn default() -> Self {
        Self {
            vals: Vec::new(),
            ids: HashMap::new(),
        }
    }
}

#[derive(Default)]
pub(super) struct Interner<'a> {
    consts: Table<InternedConst<'a>>,
    bootstraps: Table<InternedBs<'a>>,
}
impl<'a> Interner<'a> {
    pub(super) fn intern_const(&mut self, c: InternedConst<'a>) -> ConstId {
        ConstId(self.consts.intern(c))
    }

    pub(super) fn intern_bs(&mut self, bs: InternedBs<'a>) -> BsId {
        BsId(self.bootstraps.intern(bs))
    }

    pub(super) fn get_const(&self, id: ConstId) -> InternedConst<'a> {
        self.consts.vals[id.0 as usize]
    }

    pub(super) fn get_bs(&self, id: BsId) -> &InternedBs<'a> {
        &self.bootstraps.vals[id.0 as usize]
    }

    // Temporary conversion from nested constants to interned constants, until the resolver produces ids directly
    fn intern_sub(&mut self, r: Or<u16, impl ToConst<'a, u16>>) -> ConstRef {
        r.map_b(|c| self.intern_inline_const(c.to_const()))
    }

    fn intern_bs_sub(&mut self, r: RawSpanConst<'a>) -> Or<u16, Spanned<'a, ConstId>> {
        r.map_b(|c| c.span.of(self.intern_inline_const(c.v)))
    }

    pub(super) fn intern_inline_const(&mut self, c: RawConstInline<'a>) -> ConstId {
        use FlatConst as F;
        use InlineConst as I;
        let c = match c {
            I::Utf8(v) => F::Utf8(v),

            I::Int(v) => F::Int(v),
            I::Float(v) => F::Float(v),
            I::Long(v) => F::Long(v),
            I::Double(v) => F::Double(v),
            I::Class(v) => F::Class(self.intern_sub(v)),
            I::Str(v) => F::Str(self.intern_sub(v)),
            I::Field(cls, nat) => F::Field(self.intern_sub(cls), self.intern_sub(nat)),
            I::Method(cls, nat) => F::Method(self.intern_sub(cls), self.intern_sub(nat)),
            I::InterfaceMethod(cls, nat) => F::InterfaceMethod(self.intern_sub(cls), self.intern_sub(nat)),
            I::NameAndType(u1, u2) => F::NameAndType(self.intern_sub(u1), self.intern_sub(u2)),

            I::MethodHandle(tag, val) => F::MethodHandle(tag, self.intern_sub(*val)),
            I::MethodType(v) => F::MethodType(self.intern_sub(v)),
            I::Dynamic(bs, nat) => F::Dynamic(bs.map_b(|bs| self.intern_inline_bs(bs)), self.intern_sub(nat)),
            I::InvokeDynamic(bs, nat) => F::InvokeDynamic(bs.map_b(|bs| self.intern_inline_bs(bs)), self.intern_sub(nat)),
            I::Module(v) => F::Module(self.intern_sub(v)),
            I::Package(v) => F::Package(self.intern_sub(v)),
        };
        self.intern_const(c)
    }

    pub(super) fn intern_inline_bs(&mut self, bs: RawBsInline<'a>) -> BsId {
        let mut iter = bs.0.into_iter();
        let mhref = self.intern_bs_sub(iter.next().unwrap());
        let args = iter.map(|c| self.intern_bs_sub(c)).collect();
        self.intern_bs(FlatBsMeth { mhref, args })
    }
}
impl ConstId {
    pub(super) fn index(self) -> usize {
        self.0 as usize
    }
}
