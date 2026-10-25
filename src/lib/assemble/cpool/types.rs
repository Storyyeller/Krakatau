use std::fmt::Debug;

use crate::assemble::span::Spanned;
use crate::util::mstr;

#[derive(Hash, PartialEq, Eq, Clone, Copy)]
pub enum Or<A, B> {
    A(A),
    B(B),
}
impl<A: Debug, B: Debug> Debug for Or<A, B> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Or::A(v) => v.fmt(f),
            Or::B(v) => v.fmt(f),
        }
    }
}
impl<A, B> Or<A, B> {
    pub fn map_b<B2>(self, f: impl FnOnce(B) -> B2) -> Or<A, B2> {
        match self {
            Or::A(v) => Or::A(v),
            Or::B(v) => Or::B(f(v)),
        }
    }

    // pub fn try_map_b<B2, E>(self, f: impl FnOnce(B) -> Result<B2, E>) -> Result<Or<A, B2>, E> {
    //     Ok(match self {
    //         Or::A(v) => Or::A(v),
    //         Or::B(v) => Or::B(f(v)?),
    //     })
    // }

    pub fn as_b(&self) -> Option<&B> {
        if let Or::B(v) = self { Some(v) } else { None }
    }
}

pub type Bs<'a, Ref> = Or<Ref, InlineBs<'a, Ref>>;
#[derive(Debug, PartialEq, Eq, Hash, Clone)]
pub struct InlineBs<'a, Ref>(pub Vec<SpanConst<'a, Ref>>);

pub type Const<'a, Ref> = Or<Ref, InlineConst<'a, Ref>>;
pub type SpanConst<'a, Ref> = Or<Ref, Spanned<'a, InlineConst<'a, Ref>>>;

#[derive(Debug, PartialEq, Eq, Hash, Clone)]
pub enum InlineConst<'a, Ref> {
    Utf8(&'a mstr),

    Int(u32),
    Float(u32),
    Long(u64),
    Double(u64),
    Class(Ref),
    Str(Ref),
    Field(Ref, Ref),
    Method(Ref, Ref),
    InterfaceMethod(Ref, Ref),
    NameAndType(Ref, Ref),

    MethodHandle(u8, Box<Const<'a, Ref>>),
    MethodType(Ref),
    Dynamic(Bs<'a, Ref>, Ref),
    InvokeDynamic(Bs<'a, Ref>, Ref),
    Module(Ref),
    Package(Ref),
}
impl<'a, Ref> InlineConst<'a, Ref> {
    pub fn is_long(&self) -> bool {
        match self {
            InlineConst::Long(_) | InlineConst::Double(_) => true,
            _ => false,
        }
    }
}

pub trait ToConst<'a, Ref> {
    fn to_const(self) -> InlineConst<'a, Ref>;
}
impl<'a, Ref> ToConst<'a, Ref> for InlineConst<'a, Ref> {
    fn to_const(self) -> InlineConst<'a, Ref> {
        self
    }
}

// Temporary conversion for Writer::cp, until all constants are added to the table during parsing
pub trait ToSpanConst<'a> {
    fn to_span_const(self) -> SymSpanConst<'a>;
}
impl<'a> ToSpanConst<'a> for RefType<'a> {
    fn to_span_const(self) -> SymSpanConst<'a> {
        Or::A(self)
    }
}
impl<'a, T: ToConst<'a, RefType<'a>>> ToSpanConst<'a> for Or<RefType<'a>, Spanned<'a, T>> {
    fn to_span_const(self) -> SymSpanConst<'a> {
        self.map_b(|c| c.span.of(c.v.to_const()))
    }
}

#[derive(Debug, Clone, Copy)]
pub enum RefType<'a> {
    Raw(u16),
    Index(u32), // index into the unresolved consts or bs_consts table
    Sym(Spanned<'a, &'a str>),
}

pub type SymConstRef<'a> = Const<'a, RefType<'a>>;
pub type SymSpanConst<'a> = Or<RefType<'a>, Spanned<'a, InlineConst<'a, RefType<'a>>>>;
pub type SymConstInline<'a> = InlineConst<'a, RefType<'a>>;
pub type SymSpanConstInline<'a> = Spanned<'a, InlineConst<'a, RefType<'a>>>;

pub type SymBsRef<'a> = Bs<'a, RefType<'a>>;
pub type SymSpanBs<'a> = Or<RefType<'a>, Spanned<'a, InlineBs<'a, RefType<'a>>>>;
pub type SymBsInline<'a> = InlineBs<'a, RefType<'a>>;
pub type SymSpanBsInline<'a> = Spanned<'a, InlineBs<'a, RefType<'a>>>;
