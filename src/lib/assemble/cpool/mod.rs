mod builder;
mod raw_const;
mod sym_ref_resolver;
pub mod types;
use std::collections::HashMap;

use crate::lib::assemble::span::Error;
use crate::lib::assemble::span::ErrorMaker;
use crate::lib::assemble::span::Span;
use crate::lib::assemble::span::Spanned;
pub use builder::BsAttrNameNeeded;
use builder::PoolBuilder;
use sym_ref_resolver::PoolSymDefs;
pub use types::*;

pub type RefOr<'a, T> = Or<RefType<'a>, T>;

pub struct Pool<'a> {
    sym_defs: PoolSymDefs<'a>,
    raw_defs: HashMap<u16, (Span<'a>, Option<SymSpanConstInline<'a>>)>,
    bs_raw_defs: HashMap<u16, (Span<'a>, SymSpanBsInline<'a>)>,
}
// Real instance methods
impl<'a> Pool<'a> {
    pub fn new(error_maker: ErrorMaker<'a>) -> Self {
        Self {
            sym_defs: PoolSymDefs::new(error_maker),
            raw_defs: HashMap::new(),
            bs_raw_defs: HashMap::new(),
        }
    }

    pub fn add_sym_def(&mut self, name: Spanned<'a, &'a str>, r: SymConstRef<'a>) -> Result<(), Error> {
        self.sym_defs.add_def(name, r)
    }

    pub fn add_bs_sym_def(&mut self, name: Spanned<'a, &'a str>, r: SymBsRef<'a>) -> Result<(), Error> {
        self.sym_defs.add_bs_def(name, r)
    }

    pub fn add_raw_def(&mut self, ind: u16, new_span: Span<'a>, r: SymSpanConstInline<'a>) -> Result<(), Error> {
        let is_long = r.v.is_long();

        if ind == 0 || ind == 0xFFFF || (is_long && ind == 0xFFFE) {
            return self.err1("Invalid constant pool index", new_span);
        }

        if is_long {
            if let Some((old_span, _old)) = self.raw_defs.insert(ind + 1, (new_span, None)) {
                return self.err2(
                    "Conflicting raw const definition",
                    old_span,
                    "Note: Conflicts with wide const definition here",
                    new_span,
                );
            }
        }

        if let Some((old_span, old)) = self.raw_defs.insert(ind, (new_span, Some(r))) {
            if old.is_some() {
                self.err2("Duplicate raw const definition", new_span, "Note: Previously defined here", old_span)
            } else {
                self.err2(
                    "Conflicting raw const definition",
                    new_span,
                    "Note: Conflicts with wide const definition here",
                    old_span,
                )
            }
        } else {
            Ok(())
        }
    }

    pub fn add_bs_raw_def(&mut self, ind: u16, new_span: Span<'a>, r: SymSpanBsInline<'a>) -> Result<(), Error> {
        if ind == 0xFFFF {
            return self.err1("Bootstrap method index must be <= 65534.", new_span);
        }

        if let Some((old_span, _)) = self.bs_raw_defs.insert(ind, (new_span, r)) {
            self.err2("Duplicate raw bootstrap definition", new_span, "Note: Previously defined here", old_span)
        } else {
            Ok(())
        }
    }

    pub fn finish_defs(mut self) -> Result<PoolResolver<'a>, Error> {
        let error_maker = *self;
        let raw_defs = self
            .raw_defs
            .into_iter()
            .filter_map(|(ind, (_span, slot))| slot.map(|c| Ok((ind, self.sym_defs.resolve_const2(c)?))))
            .collect::<Result<_, _>>()?;
        let bs_raw_defs = self
            .bs_raw_defs
            .into_iter()
            .map(|(ind, (_span, bs))| Ok((ind, self.sym_defs.resolve_bsmeth2(bs)?)))
            .collect::<Result<_, _>>()?;

        Ok(PoolResolver {
            sym_defs: self.sym_defs,
            builder: PoolBuilder::new(error_maker, raw_defs, bs_raw_defs),
        })
    }
}
impl<'a> std::ops::Deref for Pool<'a> {
    type Target = ErrorMaker<'a>;

    fn deref(&self) -> &Self::Target {
        &self.sym_defs
    }
}

pub struct PoolResolver<'a> {
    sym_defs: PoolSymDefs<'a>,
    builder: PoolBuilder<'a>,
}
impl<'a> PoolResolver<'a> {
    pub fn resolve(&mut self, c: SymSpanConst<'a>) -> Result<u16, Error> {
        let c = self.sym_defs.resolve_ref2(c)?;
        match c {
            Or::A(ind) => Ok(ind),
            Or::B(c) => self.builder.allocate(c.span, c.v, false),
        }
    }

    pub fn resolve_ldc(&mut self, c: SymSpanConst<'a>, span: Span<'a>) -> Result<u8, Error> {
        let c = self.sym_defs.resolve_ref2(c)?;
        let ind = match c {
            Or::A(ind) => Ok(ind),
            Or::B(c) => self.builder.allocate(c.span, c.v, true),
        }?;

        ind.try_into().map_err(|_| {
            self.sym_defs
                .error1("ldc constant index must be <= 255. Try using ldc_w instead.", span)
        })
    }

    pub fn end(self) -> PoolBuilder<'a> {
        self.builder
    }
}
