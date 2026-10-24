use std::collections::HashMap;
use std::hash::Hash;

use super::raw_const::FlatBsMeth;
use super::raw_const::FlatConst;
use super::types::Or;
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
}
impl ConstId {
    pub(super) fn index(self) -> usize {
        self.0 as usize
    }
}
