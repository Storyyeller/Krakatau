use std::fmt::Debug;

use crate::lib::assemble::span::Spanned;
use crate::lib::util::BStr;

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
        if let Or::B(v) = self {
            Some(v)
        } else {
            None
        }
    }
}

pub type Utf8<'a, Ref> = Or<Ref, InlineUtf8<'a>>;
#[derive(Debug, PartialEq, Eq, Hash, Clone)]
pub struct InlineUtf8<'a>(pub BStr<'a>);

pub type Class<'a, Ref> = Or<Ref, InlineClass<'a, Ref>>;
#[derive(Debug, PartialEq, Eq, Hash, Clone)]
pub struct InlineClass<'a, Ref>(pub Utf8<'a, Ref>);

pub type Nat<'a, Ref> = Or<Ref, InlineNat<'a, Ref>>;
#[derive(Debug, PartialEq, Eq, Hash, Clone)]
pub struct InlineNat<'a, Ref>(pub Utf8<'a, Ref>, pub Utf8<'a, Ref>);

pub type Bs<'a, Ref> = Or<Ref, InlineBs<'a, Ref>>;
#[derive(Debug, PartialEq, Eq, Hash, Clone)]
pub struct InlineBs<'a, Ref>(pub Vec<SpanConst<'a, Ref>>);

pub type Const<'a, Ref> = Or<Ref, InlineConst<'a, Ref>>;
pub type SpanConst<'a, Ref> = Or<Ref, Spanned<'a, InlineConst<'a, Ref>>>;

#[derive(Debug, PartialEq, Eq, Hash, Clone)]
pub enum InlineConst<'a, Ref> {
    Utf8(BStr<'a>),

    Int(u32),
    Float(u32),
    Long(u64),
    Double(u64),
    Class(Utf8<'a, Ref>),
    Str(Utf8<'a, Ref>),
    Field(Class<'a, Ref>, Nat<'a, Ref>),
    Method(Class<'a, Ref>, Nat<'a, Ref>),
    InterfaceMethod(Class<'a, Ref>, Nat<'a, Ref>),
    NameAndType(Utf8<'a, Ref>, Utf8<'a, Ref>),

    MethodHandle(u8, Box<Const<'a, Ref>>),
    MethodType(Utf8<'a, Ref>),
    Dynamic(Bs<'a, Ref>, Nat<'a, Ref>),
    InvokeDynamic(Bs<'a, Ref>, Nat<'a, Ref>),
    Module(Utf8<'a, Ref>),
    Package(Utf8<'a, Ref>),
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
impl<'a, Ref> ToConst<'a, Ref> for InlineUtf8<'a> {
    fn to_const(self) -> InlineConst<'a, Ref> {
        InlineConst::Utf8(self.0)
    }
}
impl<'a, Ref> ToConst<'a, Ref> for InlineClass<'a, Ref> {
    fn to_const(self) -> InlineConst<'a, Ref> {
        InlineConst::Class(self.0)
    }
}
impl<'a, Ref> ToConst<'a, Ref> for InlineNat<'a, Ref> {
    fn to_const(self) -> InlineConst<'a, Ref> {
        InlineConst::NameAndType(self.0, self.1)
    }
}
impl<'a, Ref> ToConst<'a, Ref> for InlineConst<'a, Ref> {
    fn to_const(self) -> InlineConst<'a, Ref> {
        self
    }
}

#[derive(Debug)]
pub enum RefType<'a> {
    Raw(u16),
    Sym(Spanned<'a, &'a str>),
}

pub type SymUtf8Ref<'a> = Utf8<'a, RefType<'a>>;
pub type SymSpanUtf8<'a> = Or<RefType<'a>, Spanned<'a, InlineUtf8<'a>>>;
pub type RawUtf8Ref<'a> = Utf8<'a, u16>;

pub type SymClassRef<'a> = Class<'a, RefType<'a>>;
pub type SymSpanClass<'a> = Or<RefType<'a>, Spanned<'a, InlineClass<'a, RefType<'a>>>>;
// pub type SymClassInline<'a> = InlineClass<'a, RefType<'a>>;
pub type RawClassRef<'a> = Class<'a, u16>;
// pub type RawClassInline<'a> = InlineClass<'a, u16>;

pub type SymNatRef<'a> = Nat<'a, RefType<'a>>;
pub type SymSpanNat<'a> = Or<RefType<'a>, Spanned<'a, InlineNat<'a, RefType<'a>>>>;
// pub type SymNatInline<'a> = InlineNat<'a, RefType<'a>>;
pub type RawNatRef<'a> = Nat<'a, u16>;
// pub type RawNatInline<'a> = InlineNat<'a, u16>;

pub type SymConstRef<'a> = Const<'a, RefType<'a>>;
pub type SymSpanConst<'a> = Or<RefType<'a>, Spanned<'a, InlineConst<'a, RefType<'a>>>>;
pub type SymConstInline<'a> = InlineConst<'a, RefType<'a>>;
pub type SymSpanConstInline<'a> = Spanned<'a, InlineConst<'a, RefType<'a>>>;
pub type RawConstRef<'a> = Const<'a, u16>;
pub type RawSpanConst<'a> = Or<u16, Spanned<'a, InlineConst<'a, u16>>>;
pub type RawConstInline<'a> = InlineConst<'a, u16>;
pub type RawSpanConstInline<'a> = Spanned<'a, InlineConst<'a, u16>>;

pub type SymBsRef<'a> = Bs<'a, RefType<'a>>;
pub type SymSpanBs<'a> = Or<RefType<'a>, Spanned<'a, InlineBs<'a, RefType<'a>>>>;
pub type SymBsInline<'a> = InlineBs<'a, RefType<'a>>;
pub type SymSpanBsInline<'a> = Spanned<'a, InlineBs<'a, RefType<'a>>>;
pub type RawBsRef<'a> = Bs<'a, u16>;
pub type RawBsInline<'a> = InlineBs<'a, u16>;
pub type RawSpanBsInline<'a> = Spanned<'a, InlineBs<'a, u16>>;
