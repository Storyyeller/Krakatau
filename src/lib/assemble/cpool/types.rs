use std::fmt::Debug;

use crate::assemble::span::Spanned;

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
}

#[derive(Debug, Clone, Copy)]
pub enum RefType<'a> {
    Raw(u16),
    Index(u32), // index into the unresolved consts or bs_consts table
    Sym(Spanned<'a, &'a str>),
}
