use std::collections::HashMap;

use super::UnresolvedConst;
use super::interner::*;
use super::raw_const::*;
use super::types::*;
use crate::assemble::span::Error;
use crate::assemble::span::ErrorMaker;
use crate::assemble::span::Span;
use crate::assemble::span::Spanned;

type UnresolvedBs<'a> = FlatBsMeth<RefType<'a>>;

#[derive(Clone, Copy)]
enum State<R> {
    NotStarted,
    InProgress,
    Done(R),
}
struct Entry<'a, T, R> {
    span: Span<'a>,
    val: T,
    state: State<R>,
}
impl<'a, T, R> Entry<'a, T, R> {
    fn new(span: Span<'a>, val: T) -> Self {
        Self {
            span,
            val,
            state: State::NotStarted,
        }
    }
}

// Raw index (Or::A) or index into the unresolved constant or bootstrap table (Or::B)
type AliasTarget = Or<u16, u32>;
type AliasMap<'a> = HashMap<&'a str, Entry<'a, RefType<'a>, AliasTarget>>;

pub(super) struct UnresolvedSymsDefsAndConsts<'a> {
    error_maker: ErrorMaker<'a>,

    // Inline literals - these are not interned prior to sym def resolution, as they're only referenced once
    // and they have to be interned after resolution anyway. The span is used when allocating a slot for
    // a top level constant or bootstrap argument, or for a raw bootstrap def, for error reporting.
    consts: Vec<Entry<'a, UnresolvedConst<'a>, ConstId>>,
    bs_consts: Vec<Entry<'a, UnresolvedBs<'a>, BsId>>,
    sym_defs: AliasMap<'a>,
    bs_sym_defs: AliasMap<'a>,
}
impl<'a> UnresolvedSymsDefsAndConsts<'a> {
    pub(super) fn new(error_maker: ErrorMaker<'a>) -> Self {
        Self {
            error_maker,
            consts: Vec::new(),
            bs_consts: Vec::new(),
            sym_defs: HashMap::new(),
            bs_sym_defs: HashMap::new(),
        }
    }

    pub(super) fn add_inline(&mut self, span: Span<'a>, c: UnresolvedConst<'a>) -> u32 {
        let ind = self.consts.len().try_into().unwrap();
        self.consts.push(Entry::new(span, c));
        ind
    }

    pub(super) fn add_bs_inline(&mut self, span: Span<'a>, mhref: RefType<'a>, args: Vec<RefType<'a>>) -> u32 {
        let ind = self.bs_consts.len().try_into().unwrap();
        self.bs_consts.push(Entry::new(span, FlatBsMeth { mhref, args }));
        ind
    }

    pub(super) fn get_inline(&self, ind: u32) -> UnresolvedConst<'a> {
        self.consts[ind as usize].val
    }

    pub(super) fn const_span(&self, ind: u32) -> Span<'a> {
        self.consts[ind as usize].span
    }

    pub(super) fn bs_span(&self, ind: u32) -> Span<'a> {
        self.bs_consts[ind as usize].span
    }

    fn add_alias(
        error_maker: ErrorMaker<'a>,
        map: &mut AliasMap<'a>,
        name: Spanned<'a, &'a str>,
        r: RefType<'a>,
    ) -> Result<(), Error> {
        if let Some(prev) = map.insert(name.v, Entry::new(name.span, r)) {
            error_maker.err2(
                "Error: Duplicate definition of symbolic ref",
                name.span,
                "Note: Previous definition was here",
                prev.span,
            )
        } else {
            Ok(())
        }
    }

    pub(super) fn add_def(&mut self, name: Spanned<'a, &'a str>, r: RefType<'a>) -> Result<(), Error> {
        Self::add_alias(self.error_maker, &mut self.sym_defs, name, r)
    }

    pub(super) fn add_bs_def(&mut self, name: Spanned<'a, &'a str>, r: RefType<'a>) -> Result<(), Error> {
        Self::add_alias(self.error_maker, &mut self.bs_sym_defs, name, r)
    }

    // Follow a chain of symbolic definitions to the raw ref or inline constant it ultimately refers to.
    // The result is memoized for every name along the chain. Also returns the span of the last name
    // in the chain, for reporting circular definitions.
    fn lookup_alias(
        error_maker: ErrorMaker<'a>,
        map: &mut AliasMap<'a>,
        mut name: Spanned<'a, &'a str>,
    ) -> Result<(AliasTarget, Span<'a>), Error> {
        let mut path = Vec::new();
        let target = loop {
            let Some(e) = map.get_mut(name.v) else {
                return error_maker.err1("Undefined symbolic reference", name.span);
            };
            match e.state {
                State::Done(t) => break t,
                State::InProgress => return error_maker.err1("Circular definition of symbolic reference", name.span),
                State::NotStarted => {
                    e.state = State::InProgress;
                    path.push(name.v);
                    match e.val {
                        RefType::Raw(ind) => break Or::A(ind),
                        RefType::Index(ind) => break Or::B(ind),
                        RefType::Sym(next) => name = next,
                    }
                }
            }
        };

        for name in path {
            map.get_mut(name).unwrap().state = State::Done(target);
        }
        Ok((target, name.span))
    }

    fn resolve_ref(&mut self, interner: &mut Interner<'a>, r: RefType<'a>) -> Result<ConstRef, Error> {
        let (target, span) = match r {
            RefType::Raw(ind) => return Ok(Or::A(ind)),
            RefType::Index(ind) => (Or::B(ind), self.const_span(ind)),
            RefType::Sym(name) => Self::lookup_alias(self.error_maker, &mut self.sym_defs, name)?,
        };
        Ok(match target {
            Or::A(ind) => Or::A(ind),
            Or::B(ind) => Or::B(self.resolve_index(interner, ind, span)?),
        })
    }

    // Resolve a top level constant or bootstrap argument, along with the span to use if it needs to be allocated
    pub(super) fn resolve_spanned(
        &mut self,
        interner: &mut Interner<'a>,
        r: RefType<'a>,
    ) -> Result<SpannedConstRef<'a>, Error> {
        let span = match r {
            RefType::Raw(ind) => return Ok(Or::A(ind)),
            RefType::Index(ind) => self.const_span(ind),
            RefType::Sym(name) => name.span,
        };
        Ok(self.resolve_ref(interner, r)?.map_b(|id| span.of(id)))
    }

    // span is the span of the reference used to reach this entry, for reporting circular definitions
    pub(super) fn resolve_index(&mut self, interner: &mut Interner<'a>, ind: u32, span: Span<'a>) -> Result<ConstId, Error> {
        let e = &mut self.consts[ind as usize];
        match e.state {
            State::Done(id) => return Ok(id),
            State::InProgress => return self.err1("Circular definition of symbolic reference", span),
            State::NotStarted => e.state = State::InProgress,
        }

        let c = e.val.try_map(
            &mut (&mut *self, &mut *interner),
            |(s, i), r| s.resolve_spanned(i, r),
            |(s, i), r| s.resolve_bs_spanned(i, r),
        )?;
        let id = interner.intern_const(c);
        self.consts[ind as usize].state = State::Done(id);
        Ok(id)
    }

    fn resolve_bs_ref(&mut self, interner: &mut Interner<'a>, r: RefType<'a>) -> Result<BsRef, Error> {
        let (target, span) = match r {
            RefType::Raw(ind) => return Ok(Or::A(ind)),
            RefType::Index(ind) => (Or::B(ind), self.bs_span(ind)),
            RefType::Sym(name) => Self::lookup_alias(self.error_maker, &mut self.bs_sym_defs, name)?,
        };
        Ok(match target {
            Or::A(ind) => Or::A(ind),
            Or::B(ind) => Or::B(self.resolve_bs_index(interner, ind, span)?),
        })
    }

    fn resolve_bs_spanned(&mut self, interner: &mut Interner<'a>, r: RefType<'a>) -> Result<SpannedBsRef<'a>, Error> {
        let span = match r {
            RefType::Raw(ind) => return Ok(Or::A(ind)),
            RefType::Index(ind) => self.bs_span(ind),
            RefType::Sym(name) => name.span,
        };
        Ok(self.resolve_bs_ref(interner, r)?.map_b(|id| span.of(id)))
    }

    // span is the span of the reference used to reach this entry, for reporting circular definitions
    pub(super) fn resolve_bs_index(&mut self, interner: &mut Interner<'a>, ind: u32, span: Span<'a>) -> Result<BsId, Error> {
        let e = &mut self.bs_consts[ind as usize];
        match e.state {
            State::Done(id) => return Ok(id),
            State::InProgress => return self.err1("Circular definition of symbolic reference", span),
            State::NotStarted => e.state = State::InProgress,
        }

        let bs = e.val.clone();
        let mhref = self.resolve_spanned(interner, bs.mhref)?;
        let args = bs
            .args
            .into_iter()
            .map(|r| self.resolve_spanned(interner, r))
            .collect::<Result<_, _>>()?;
        let id = interner.intern_bs(FlatBsMeth { mhref, args });
        self.bs_consts[ind as usize].state = State::Done(id);
        Ok(id)
    }
}
impl<'a> std::ops::Deref for UnresolvedSymsDefsAndConsts<'a> {
    type Target = ErrorMaker<'a>;

    fn deref(&self) -> &Self::Target {
        &self.error_maker
    }
}
