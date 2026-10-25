use std::collections::HashMap;

use super::interner::*;
use super::raw_const::*;
use super::types::*;
use crate::assemble::span::Error;
use crate::assemble::span::ErrorMaker;
use crate::assemble::span::Span;
use crate::assemble::span::Spanned;
use crate::util::mstr;

type UnresolvedConst<'a> = FlatConst<'a, RefType<'a>, RefType<'a>>;
type UnresolvedBs<'a> = FlatBsMeth<RefType<'a>>;

enum ResolveState<Lazy, Resolved> {
    Unresolved(Option<Lazy>),
    Resolved(Resolved),
}

pub(super) struct UnresolvedSymsDefsAndConsts<'a> {
    error_maker: ErrorMaker<'a>,

    // Inline literals - these are not interned prior to sym def resolution, as they're only referenced once
    // and they have to be interned after resolution anyway. The span is used when allocating a slot for
    // a top level constant or bootstrap argument, for error reporting.
    consts: Vec<(Span<'a>, UnresolvedConst<'a>)>,
    bs_consts: Vec<UnresolvedBs<'a>>,
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

    ///////////////////////////////////////////////////////////////////////////
    // Temporary conversion from the parser's nested constants to table entries,
    // until the parser adds constants to the table directly.
    pub(super) fn add_const(&mut self, r: SymSpanConst<'a>) -> RefType<'a> {
        match r {
            Or::A(r) => r,
            Or::B(c) => RefType::Index(self.add_inline(c.span, c.v)),
        }
    }

    // Nested constants don't have their own spans, so use the parent's span
    fn add_sub(&mut self, span: Span<'a>, r: Or<RefType<'a>, impl ToConst<'a, RefType<'a>>>) -> RefType<'a> {
        match r {
            Or::A(r) => r,
            Or::B(c) => RefType::Index(self.add_inline(span, c.to_const())),
        }
    }

    pub(super) fn add_inline(&mut self, span: Span<'a>, c: SymConstInline<'a>) -> u32 {
        use FlatConst as F;
        use InlineConst as I;
        let c = match c {
            I::Utf8(v) => F::Utf8(v),

            I::Int(v) => F::Int(v),
            I::Float(v) => F::Float(v),
            I::Long(v) => F::Long(v),
            I::Double(v) => F::Double(v),
            I::Class(v) => F::Class(v),
            I::Str(v) => F::Str(v),
            I::Field(cls, nat) => F::Field(cls, nat),
            I::Method(cls, nat) => F::Method(cls, nat),
            I::InterfaceMethod(cls, nat) => F::InterfaceMethod(cls, nat),
            I::NameAndType(u1, u2) => F::NameAndType(u1, u2),

            I::MethodHandle(tag, val) => F::MethodHandle(tag, self.add_sub(span, *val)),
            I::MethodType(v) => F::MethodType(v),
            I::Dynamic(bs, nat) => F::Dynamic(self.add_bs(bs), nat),
            I::InvokeDynamic(bs, nat) => F::InvokeDynamic(self.add_bs(bs), nat),
            I::Module(v) => F::Module(v),
            I::Package(v) => F::Package(v),
        };

        let ind = self.consts.len().try_into().unwrap();
        self.consts.push((span, c));
        ind
    }

    fn add_bs(&mut self, r: SymBsRef<'a>) -> RefType<'a> {
        match r {
            Or::A(r) => r,
            Or::B(bs) => RefType::Index(self.add_bs_inline(bs)),
        }
    }

    pub(super) fn add_bs_inline(&mut self, bs: SymBsInline<'a>) -> u32 {
        let mut iter = bs.0.into_iter();
        let mhref = self.add_const(iter.next().unwrap());
        let args = iter.map(|c| self.add_const(c)).collect();

        let ind = self.bs_consts.len().try_into().unwrap();
        self.bs_consts.push(FlatBsMeth { mhref, args });
        ind
    }
    ///////////////////////////////////////////////////////////////////////////

    pub(super) fn inline_utf8(&self, ind: u32) -> Option<&'a mstr> {
        match self.consts[ind as usize].1 {
            FlatConst::Utf8(s) => Some(s),
            _ => None,
        }
    }

    pub(super) fn inline_nat(&self, ind: u32) -> Option<(RefType<'a>, RefType<'a>)> {
        match self.consts[ind as usize].1 {
            FlatConst::NameAndType(name, desc) => Some((name, desc)),
            _ => None,
        }
    }

    pub(super) fn const_span(&self, ind: u32) -> Span<'a> {
        self.consts[ind as usize].0
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

    pub(super) fn add_def(&mut self, name: Spanned<'a, &'a str>, r: SymConstRef<'a>) -> Result<(), Error> {
        let r = self.add_sub(name.span, r);
        self.add_def_generic(name, r, |this| &mut this.sym_defs)
    }

    pub(super) fn add_bs_def(&mut self, name: Spanned<'a, &'a str>, r: SymBsRef<'a>) -> Result<(), Error> {
        let r = self.add_bs(r);
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
        let bs = self.bs_consts[ind as usize].clone();
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
