mod builder;
mod interner;
mod raw_const;
mod sym_ref_resolver;
pub mod types;
use std::collections::HashMap;

use crate::assemble::span::Error;
use crate::assemble::span::ErrorMaker;
use crate::assemble::span::Span;
use crate::assemble::span::Spanned;
pub use builder::BsAttrNameNeeded;
use builder::PoolBuilder;
use interner::Interner;
pub use raw_const::FlatConst;
use sym_ref_resolver::UnresolvedSymsDefsAndConsts;
pub use types::*;

// Constants as produced by the parser, prior to symbolic reference resolution
pub type UnresolvedConst<'a> = FlatConst<'a, RefType<'a>, RefType<'a>>;

pub struct Pool<'a> {
    sym_defs: UnresolvedSymsDefsAndConsts<'a>,
    interner: Interner<'a>,
    // Indexes into the unresolved constant table
    raw_defs: HashMap<u16, (Span<'a>, Option<u32>)>,
    bs_raw_defs: HashMap<u16, (Span<'a>, u32)>,
}
// Real instance methods
impl<'a> Pool<'a> {
    pub fn new(error_maker: ErrorMaker<'a>) -> Self {
        Self {
            sym_defs: UnresolvedSymsDefsAndConsts::new(error_maker),
            interner: Interner::default(),
            raw_defs: HashMap::new(),
            bs_raw_defs: HashMap::new(),
        }
    }

    pub fn add_const(&mut self, span: Span<'a>, c: UnresolvedConst<'a>) -> RefType<'a> {
        RefType::Index(self.sym_defs.add_inline(span, c))
    }

    pub fn add_bs(&mut self, span: Span<'a>, mhref: RefType<'a>, args: Vec<RefType<'a>>) -> RefType<'a> {
        RefType::Index(self.sym_defs.add_bs_inline(span, mhref, args))
    }

    // Returns the contents of r if it is an inline constant
    pub fn get_inline(&self, r: RefType<'a>) -> Option<UnresolvedConst<'a>> {
        match r {
            RefType::Index(ind) => Some(self.sym_defs.get_inline(ind)),
            _ => None,
        }
    }

    pub fn add_sym_def(&mut self, name: Spanned<'a, &'a str>, r: RefType<'a>) -> Result<(), Error> {
        self.sym_defs.add_def(name, r)
    }

    pub fn add_bs_sym_def(&mut self, name: Spanned<'a, &'a str>, r: RefType<'a>) -> Result<(), Error> {
        self.sym_defs.add_bs_def(name, r)
    }

    // r is an index into the unresolved constant table
    pub fn add_raw_def(&mut self, ind: u16, new_span: Span<'a>, r: u32) -> Result<(), Error> {
        let is_long = self.sym_defs.get_inline(r).is_long();

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

    // r is an index into the unresolved bootstrap method table
    pub fn add_bs_raw_def(&mut self, ind: u16, new_span: Span<'a>, r: u32) -> Result<(), Error> {
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
            .filter_map(|(ind, (_span, slot))| {
                slot.map(|c| {
                    let span = self.sym_defs.const_span(c);
                    Ok((ind, span, self.sym_defs.resolve_index(&mut self.interner, c)?))
                })
            })
            .collect::<Result<_, _>>()?;
        let bs_raw_defs = self
            .bs_raw_defs
            .into_iter()
            .map(|(ind, (_span, bs))| {
                let span = self.sym_defs.bs_span(bs);
                Ok((ind, span, self.sym_defs.resolve_bs_index(&mut self.interner, bs)?))
            })
            .collect::<Result<_, _>>()?;

        Ok(PoolResolver {
            sym_defs: self.sym_defs,
            builder: PoolBuilder::new(error_maker, self.interner, raw_defs, bs_raw_defs),
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
    sym_defs: UnresolvedSymsDefsAndConsts<'a>,
    builder: PoolBuilder<'a>,
}
impl<'a> PoolResolver<'a> {
    pub fn resolve(&mut self, c: RefType<'a>) -> Result<u16, Error> {
        match self.sym_defs.resolve_spanned(&mut self.builder.interner, c)? {
            Or::A(ind) => Ok(ind),
            Or::B(id) => self.builder.allocate(id.span, id.v, false),
        }
    }

    pub fn resolve_ldc(&mut self, c: RefType<'a>, span: Span<'a>) -> Result<u8, Error> {
        let ind = match self.sym_defs.resolve_spanned(&mut self.builder.interner, c)? {
            Or::A(ind) => ind,
            Or::B(id) => self.builder.allocate(id.span, id.v, true)?,
        };

        ind.try_into().map_err(|_| {
            self.sym_defs
                .error1("ldc constant index must be <= 255. Try using ldc_w instead.", span)
        })
    }

    pub fn end(self) -> PoolBuilder<'a> {
        self.builder
    }
}
