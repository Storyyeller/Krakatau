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

enum ResolveState<Lazy, Resolved> {
    Unresolved(Option<Lazy>),
    Resolved(Resolved),
}

pub(super) struct UnresolvedSymsDefsAndConsts<'a> {
    error_maker: ErrorMaker<'a>,

    // Inline literals - these are not interned prior to sym def resolution, as they're only referenced once
    // and they have to be interned after resolution anyway. The span is used when allocating a slot for
    // a top level constant or bootstrap argument, or for a raw bootstrap def, for error reporting.
    consts: Vec<(Span<'a>, UnresolvedConst<'a>)>,
    bs_consts: Vec<(Span<'a>, UnresolvedBs<'a>)>,
    sym_defs: HashMap<&'a str, (Span<'a>, ResolveState<RefType<'a>, ConstRef>)>,
    bs_sym_defs: HashMap<&'a str, (Span<'a>, ResolveState<RefType<'a>, BsRef>)>,
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
        self.consts.push((span, c));
        ind
    }

    pub(super) fn add_bs_inline(&mut self, span: Span<'a>, mhref: RefType<'a>, args: Vec<RefType<'a>>) -> u32 {
        let ind = self.bs_consts.len().try_into().unwrap();
        self.bs_consts.push((span, FlatBsMeth { mhref, args }));
        ind
    }

    pub(super) fn get_inline(&self, ind: u32) -> UnresolvedConst<'a> {
        self.consts[ind as usize].1
    }

    pub(super) fn const_span(&self, ind: u32) -> Span<'a> {
        self.consts[ind as usize].0
    }

    pub(super) fn bs_span(&self, ind: u32) -> Span<'a> {
        self.bs_consts[ind as usize].0
    }

    fn add_def_generic<Before, After>(
        &mut self,
        name: Spanned<'a, &'a str>,
        r: Before,
        get_map: fn(&mut Self) -> &mut HashMap<&'a str, (Span<'a>, ResolveState<Before, After>)>,
    ) -> Result<(), Error> {
        let new_val = (name.span, ResolveState::Unresolved(Some(r)));
        if let Some((prev_span, _)) = get_map(self).insert(name.v, new_val) {
            self.err2(
                "Error: Duplicate definition of symbolic ref",
                name.span,
                "Note: Previous definition was here",
                prev_span,
            )
        } else {
            Ok(())
        }
    }

    pub(super) fn add_def(&mut self, name: Spanned<'a, &'a str>, r: RefType<'a>) -> Result<(), Error> {
        self.add_def_generic(name, r, |this| &mut this.sym_defs)
    }

    pub(super) fn add_bs_def(&mut self, name: Spanned<'a, &'a str>, r: RefType<'a>) -> Result<(), Error> {
        self.add_def_generic(name, r, |this| &mut this.bs_sym_defs)
    }

    fn resolve_sym_generic<Before, After: Copy>(
        &mut self,
        interner: &mut Interner<'a>,
        name: Spanned<'_, &str>,
        get_map: fn(&mut Self) -> &mut HashMap<&'a str, (Span<'a>, ResolveState<Before, After>)>,
        resolve: fn(&mut Self, &mut Interner<'a>, Before) -> Result<After, Error>,
    ) -> Result<After, Error> {
        if let Some((_, v)) = get_map(self).get_mut(name.v) {
            use ResolveState::*;
            let to_resolve = match v {
                Unresolved(r) => r.take(),
                Resolved(r) => return Ok(*r),
            };

            if let Some(r) = to_resolve {
                let r = resolve(self, interner, r)?;
                get_map(self).get_mut(name.v).unwrap().1 = Resolved(r);
                Ok(r)
            } else {
                self.err1("Circular definition of symbolic reference", name.span)
            }
        } else {
            self.err1("Undefined symbolic reference", name.span)
        }
    }

    pub(super) fn resolve_ref(&mut self, interner: &mut Interner<'a>, r: RefType<'a>) -> Result<ConstRef, Error> {
        Ok(match r {
            RefType::Raw(ind) => Or::A(ind),
            RefType::Index(ind) => Or::B(self.resolve_index(interner, ind)?),
            RefType::Sym(name) => self.resolve_sym_generic(interner, name, |this| &mut this.sym_defs, Self::resolve_ref)?,
        })
    }

    // Resolve a top level constant or bootstrap argument, along with the span to use if it needs to be allocated
    pub(super) fn resolve_spanned(
        &mut self,
        interner: &mut Interner<'a>,
        r: RefType<'a>,
    ) -> Result<Or<u16, Spanned<'a, ConstId>>, Error> {
        let span = match r {
            RefType::Raw(ind) => return Ok(Or::A(ind)),
            RefType::Index(ind) => self.const_span(ind),
            RefType::Sym(name) => name.span,
        };
        Ok(self.resolve_ref(interner, r)?.map_b(|id| span.of(id)))
    }

    pub(super) fn resolve_index(&mut self, interner: &mut Interner<'a>, ind: u32) -> Result<ConstId, Error> {
        let (_, c) = self.consts[ind as usize];
        let c = c.try_map(
            &mut (self, &mut *interner),
            |(s, i), r| s.resolve_ref(i, r),
            |(s, i), r| s.resolve_bs_ref(i, r),
        )?;
        Ok(interner.intern_const(c))
    }

    fn resolve_bs_ref(&mut self, interner: &mut Interner<'a>, r: RefType<'a>) -> Result<BsRef, Error> {
        Ok(match r {
            RefType::Raw(ind) => Or::A(ind),
            RefType::Index(ind) => Or::B(self.resolve_bs_index(interner, ind)?),
            RefType::Sym(name) => {
                self.resolve_sym_generic(interner, name, |this| &mut this.bs_sym_defs, Self::resolve_bs_ref)?
            }
        })
    }

    pub(super) fn resolve_bs_index(&mut self, interner: &mut Interner<'a>, ind: u32) -> Result<BsId, Error> {
        let bs = self.bs_consts[ind as usize].1.clone();
        let mhref = self.resolve_spanned(interner, bs.mhref)?;
        let args = bs
            .args
            .into_iter()
            .map(|r| self.resolve_spanned(interner, r))
            .collect::<Result<_, _>>()?;
        Ok(interner.intern_bs(FlatBsMeth { mhref, args }))
    }
}
impl<'a> std::ops::Deref for UnresolvedSymsDefsAndConsts<'a> {
    type Target = ErrorMaker<'a>;

    fn deref(&self) -> &Self::Target {
        &self.error_maker
    }
}
