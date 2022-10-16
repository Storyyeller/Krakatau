use std::collections::HashMap;

use super::types::*;
use crate::lib::assemble::span::Error;
use crate::lib::assemble::span::ErrorMaker;
use crate::lib::assemble::span::Span;
use crate::lib::assemble::span::Spanned;

enum ResolveState<Lazy, Resolved> {
    Unresolved(Option<Lazy>),
    Resolved(Resolved),
}

pub struct PoolSymDefs<'a> {
    error_maker: ErrorMaker<'a>,

    sym_defs: HashMap<&'a str, (Span<'a>, ResolveState<SymConstRef<'a>, RawConstRef<'a>>)>,
    bs_sym_defs: HashMap<&'a str, (Span<'a>, ResolveState<SymBsRef<'a>, RawBsRef<'a>>)>,
}
impl<'a> PoolSymDefs<'a> {
    pub fn new(error_maker: ErrorMaker<'a>) -> Self {
        Self {
            error_maker,
            sym_defs: HashMap::new(),
            bs_sym_defs: HashMap::new(),
        }
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

    pub fn add_def(&mut self, name: Spanned<'a, &'a str>, r: SymConstRef<'a>) -> Result<(), Error> {
        self.add_def_generic(name, r, |this| &mut this.sym_defs)
    }

    pub fn add_bs_def(&mut self, name: Spanned<'a, &'a str>, r: SymBsRef<'a>) -> Result<(), Error> {
        self.add_def_generic(name, r, |this| &mut this.bs_sym_defs)
    }

    fn resolve_sym_generic<Before, After: Clone>(
        &mut self,
        name: Spanned<'_, &str>,
        get_map: fn(&mut Self) -> &mut HashMap<&'a str, (Span<'a>, ResolveState<Before, After>)>,
        resolve: fn(&mut Self, Before) -> Result<After, Error>,
    ) -> Result<After, Error> {
        if let Some((_, v)) = get_map(self).get_mut(name.v) {
            use ResolveState::*;
            let to_resolve = match v {
                Unresolved(r) => r.take(),
                Resolved(r) => return Ok(r.clone()),
            };

            if let Some(r) = to_resolve {
                let r = resolve(self, r)?;
                get_map(self).get_mut(name.v).unwrap().1 = Resolved(r.clone());
                Ok(r)
            } else {
                self.err1("Circular definition of symbolic reference", name.span)
            }
        } else {
            self.err1("Undefined symbolic reference", name.span)
        }
    }

    fn resolve_sym(&mut self, name: Spanned<'_, &str>) -> Result<RawConstRef<'a>, Error> {
        self.resolve_sym_generic(name, |this| &mut this.sym_defs, Self::resolve_ref)
    }

    fn resolve_bs_sym(&mut self, name: Spanned<'_, &str>) -> Result<RawBsRef<'a>, Error> {
        self.resolve_sym_generic(name, |this| &mut this.bs_sym_defs, Self::resolve_bs_ref)
    }

    fn resolve_utf8(&mut self, r: SymUtf8Ref<'a>) -> Result<RawUtf8Ref<'a>, Error> {
        Ok(match r {
            Or::A(RefType::Raw(r)) => Or::A(r),
            Or::A(RefType::Sym(name)) => {
                let resolved = self.resolve_sym(name)?;
                match resolved {
                    Or::A(r) => Or::A(r),
                    Or::B(InlineConst::Utf8(sym)) => Or::B(InlineUtf8(sym)),
                    _ => self.err1("Reference must resolve to raw or Utf8 reference.", name.span)?,
                }
            }
            Or::B(sym) => Or::B(sym),
        })
    }

    fn resolve_class(&mut self, r: SymClassRef<'a>) -> Result<RawClassRef<'a>, Error> {
        Ok(match r {
            Or::A(RefType::Raw(r)) => Or::A(r),
            Or::A(RefType::Sym(name)) => {
                let resolved = self.resolve_sym(name)?;
                match resolved {
                    Or::A(r) => Or::A(r),
                    Or::B(InlineConst::Class(r)) => Or::B(InlineClass(r)),
                    _ => self.err1("Reference must resolve to raw or Class reference.", name.span)?,
                }
            }
            Or::B(InlineClass(u)) => Or::B(InlineClass(self.resolve_utf8(u)?)),
        })
    }

    fn resolve_nat(&mut self, r: SymNatRef<'a>) -> Result<RawNatRef<'a>, Error> {
        Ok(match r {
            Or::A(RefType::Raw(r)) => Or::A(r),
            Or::A(RefType::Sym(name)) => {
                let resolved = self.resolve_sym(name)?;
                match resolved {
                    Or::A(r) => Or::A(r),
                    Or::B(InlineConst::NameAndType(r1, r2)) => Or::B(InlineNat(r1, r2)),
                    _ => self.err1("Reference must resolve to raw or NameAndType reference.", name.span)?,
                }
            }
            Or::B(InlineNat(r1, r2)) => Or::B(InlineNat(self.resolve_utf8(r1)?, self.resolve_utf8(r2)?)),
        })
    }

    pub fn resolve_bsmeth(&mut self, bs: SymBsInline<'a>) -> Result<RawBsInline<'a>, Error> {
        Ok(InlineBs(bs.0.into_iter().map(|r| self.resolve_ref2(r)).collect::<Result<_, _>>()?))
    }

    fn resolve_bs_ref(&mut self, r: SymBsRef<'a>) -> Result<RawBsRef<'a>, Error> {
        Ok(match r {
            Or::A(RefType::Raw(r)) => Or::A(r),
            Or::A(RefType::Sym(name)) => self.resolve_bs_sym(name)?,
            Or::B(bs) => Or::B(self.resolve_bsmeth(bs)?),
        })
    }

    pub fn resolve_const(&mut self, c: SymConstInline<'a>) -> Result<RawConstInline<'a>, Error> {
        use InlineConst::*;

        Ok(match c {
            Utf8(v) => Utf8(v),
            Int(v) => Int(v),
            Float(v) => Float(v),
            Long(v) => Long(v),
            Double(v) => Double(v),

            Class(v) => Class(self.resolve_utf8(v)?),
            Str(v) => Str(self.resolve_utf8(v)?),
            Field(clsr, natr) => Field(self.resolve_class(clsr)?, self.resolve_nat(natr)?),
            Method(clsr, natr) => Method(self.resolve_class(clsr)?, self.resolve_nat(natr)?),
            InterfaceMethod(clsr, natr) => InterfaceMethod(self.resolve_class(clsr)?, self.resolve_nat(natr)?),
            NameAndType(r1, r2) => NameAndType(self.resolve_utf8(r1)?, self.resolve_utf8(r2)?),
            MethodHandle(tag, r) => MethodHandle(tag, Box::new(self.resolve_ref(*r)?)),
            MethodType(v) => MethodType(self.resolve_utf8(v)?),
            Dynamic(dynr, natr) => Dynamic(self.resolve_bs_ref(dynr)?, self.resolve_nat(natr)?),
            InvokeDynamic(dynr, natr) => InvokeDynamic(self.resolve_bs_ref(dynr)?, self.resolve_nat(natr)?),
            Module(v) => Module(self.resolve_utf8(v)?),
            Package(v) => Package(self.resolve_utf8(v)?),
        })
    }

    fn resolve_ref(&mut self, r: SymConstRef<'a>) -> Result<RawConstRef<'a>, Error> {
        Ok(match r {
            Or::A(RefType::Raw(r)) => Or::A(r),
            Or::A(RefType::Sym(name)) => self.resolve_sym(name)?,
            Or::B(c) => Or::B(self.resolve_const(c)?),
        })
    }

    // temp hack
    pub fn resolve_ref2(&mut self, r: SymSpanConst<'a>) -> Result<RawSpanConst<'a>, Error> {
        Ok(match r {
            Or::A(RefType::Raw(r)) => Or::A(r),
            Or::A(RefType::Sym(name)) => self.resolve_sym(name)?.map_b(|c| name.span.of(c)),
            Or::B(c) => Or::B(c.span.of(self.resolve_const(c.v)?)),
        })
    }

    pub fn resolve_bsmeth2(&mut self, bs: SymSpanBsInline<'a>) -> Result<RawSpanBsInline<'a>, Error> {
        Ok(bs.span.of(self.resolve_bsmeth(bs.v)?))
    }

    pub fn resolve_const2(&mut self, c: SymSpanConstInline<'a>) -> Result<RawSpanConstInline<'a>, Error> {
        Ok(c.span.of(self.resolve_const(c.v)?))
    }
}
impl<'a> std::ops::Deref for PoolSymDefs<'a> {
    type Target = ErrorMaker<'a>;

    fn deref(&self) -> &Self::Target {
        &self.error_maker
    }
}
