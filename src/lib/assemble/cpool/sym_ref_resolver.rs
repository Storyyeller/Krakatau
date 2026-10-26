use std::collections::HashMap;
use std::convert::Infallible;

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

impl<R> State<R> {
    // Mark the entry as in progress if it hasn't been started yet. Returns whether resolution of the entry needs
    // to start, or an error if it is already in progress, i.e. there is a circular definition.
    fn start(&mut self) -> Result<bool, ()> {
        match self {
            State::NotStarted => {
                *self = State::InProgress;
                Ok(true)
            }
            State::InProgress => Err(()),
            State::Done(_) => Ok(false),
        }
    }
}

#[derive(Clone, Copy)]
enum Kind {
    Const,
    Bs,
}
// Used to iteratively simulate the callstack context when resolving constants.
// Resolution is done iteratively rather than with recursion to avoid stack overflows.
enum Item<'a> {
    Enter(Kind, RefType<'a>),
    Exit(Kind, u32),
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

    /// Get a span from self.consts or self.bs_consts based on the kind.
    fn entry_span(&self, kind: Kind, ind: u32) -> Span<'a> {
        match kind {
            Kind::Const => self.const_span(ind),
            Kind::Bs => self.bs_span(ind),
        }
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

    /// Follow a chain of symbolic definitions to the raw ref or inline constant it ultimately refers to.
    /// The result is memoized for every name along the chain. Also returns the span of the last name
    /// in the chain, for reporting circular definitions.
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

    /// Find the raw index or table entry that a ref refers to, following symbolic definitions. For table entries,
    /// also returns the span of the reference used to reach the entry, for reporting circular definitions.
    fn lookup(&mut self, kind: Kind, r: RefType<'a>) -> Result<Or<u16, (u32, Span<'a>)>, Error> {
        let (target, span) = match r {
            RefType::Raw(ind) => return Ok(Or::A(ind)),
            RefType::Index(ind) => (Or::B(ind), self.entry_span(kind, ind)),
            RefType::Sym(name) => {
                let map = match kind {
                    Kind::Const => &mut self.sym_defs,
                    Kind::Bs => &mut self.bs_sym_defs,
                };
                Self::lookup_alias(self.error_maker, map, name)?
            }
        };
        Ok(target.map_b(|ind| (ind, span)))
    }

    /// Resolve and intern every table entry reachable from r. This uses an explicit stack rather than recursion,
    /// since constants can be nested arbitrarily deeply. Children are visited left to right, so errors are
    /// reported in the same order as a recursive traversal would.
    fn resolve(&mut self, interner: &mut Interner<'a>, kind: Kind, r: RefType<'a>) -> Result<(), Error> {
        let mut stack = vec![Item::Enter(kind, r)];
        while let Some(item) = stack.pop() {
            match item {
                Item::Enter(kind, r) => {
                    let Or::B((ind, span)) = self.lookup(kind, r)? else { continue };
                    let started = match kind {
                        Kind::Const => self.consts[ind as usize].state.start(),
                        Kind::Bs => self.bs_consts[ind as usize].state.start(),
                    };
                    match started {
                        Err(()) => return self.err1("Circular definition of symbolic reference", span),
                        Ok(false) => {}
                        Ok(true) => {
                            stack.push(Item::Exit(kind, ind));
                            self.push_children(&mut stack, kind, ind);
                        }
                    }
                }
                Item::Exit(Kind::Const, ind) => {
                    let c = self.consts[ind as usize].val;
                    let c = c.try_map(self, |s, r| s.get_resolved(r), |s, r| s.get_resolved_bs(r))?;
                    self.consts[ind as usize].state = State::Done(interner.intern_const(c));
                }
                Item::Exit(Kind::Bs, ind) => {
                    let bs = self.bs_consts[ind as usize].val.clone();
                    let mhref = self.get_resolved(bs.mhref)?;
                    let args = bs.args.into_iter().map(|r| self.get_resolved(r)).collect::<Result<_, _>>()?;
                    self.bs_consts[ind as usize].state = State::Done(interner.intern_bs(FlatBsMeth { mhref, args }));
                }
            }
        }
        Ok(())
    }

    /// Push Enter items for the children of a table entry, in reverse order so they are visited left to right
    fn push_children(&self, stack: &mut Vec<Item<'a>>, kind: Kind, ind: u32) {
        let start = stack.len();
        match kind {
            Kind::Const => {
                let _ = self.consts[ind as usize].val.try_map(
                    stack,
                    |st, r| Ok::<_, Infallible>(st.push(Item::Enter(Kind::Const, r))),
                    |st, r| Ok(st.push(Item::Enter(Kind::Bs, r))),
                );
            }
            Kind::Bs => {
                let bs = &self.bs_consts[ind as usize].val;
                stack.push(Item::Enter(Kind::Const, bs.mhref));
                stack.extend(bs.args.iter().map(|&r| Item::Enter(Kind::Const, r)));
            }
        }
        stack[start..].reverse(); // Move leftmost children to the top so they get visited first
    }

    /// Get the result for an already resolved constant ref, along with the span to use if it needs to be allocated
    fn get_resolved(&mut self, r: RefType<'a>) -> Result<SpannedConstRef<'a>, Error> {
        let span = match r {
            RefType::Raw(ind) => return Ok(Or::A(ind)),
            RefType::Index(ind) => self.const_span(ind),
            RefType::Sym(name) => name.span,
        };
        Ok(match self.lookup(Kind::Const, r)? {
            Or::A(ind) => Or::A(ind),
            Or::B((ind, _)) => match self.consts[ind as usize].state {
                State::Done(id) => Or::B(span.of(id)),
                _ => unreachable!(),
            },
        })
    }

    fn get_resolved_bs(&mut self, r: RefType<'a>) -> Result<SpannedBsRef<'a>, Error> {
        let span = match r {
            RefType::Raw(ind) => return Ok(Or::A(ind)),
            RefType::Index(ind) => self.bs_span(ind),
            RefType::Sym(name) => name.span,
        };
        Ok(match self.lookup(Kind::Bs, r)? {
            Or::A(ind) => Or::A(ind),
            Or::B((ind, _)) => match self.bs_consts[ind as usize].state {
                State::Done(id) => Or::B(span.of(id)),
                _ => unreachable!(),
            },
        })
    }

    /// Resolve a top level constant or bootstrap argument, along with the span to use if it needs to be allocated
    pub(super) fn resolve_spanned(
        &mut self,
        interner: &mut Interner<'a>,
        r: RefType<'a>,
    ) -> Result<SpannedConstRef<'a>, Error> {
        self.resolve(interner, Kind::Const, r)?;
        self.get_resolved(r)
    }

    pub(super) fn resolve_index(&mut self, interner: &mut Interner<'a>, ind: u32) -> Result<ConstId, Error> {
        self.resolve(interner, Kind::Const, RefType::Index(ind))?;
        match self.consts[ind as usize].state {
            State::Done(id) => Ok(id),
            _ => unreachable!(),
        }
    }

    pub(super) fn resolve_bs_index(&mut self, interner: &mut Interner<'a>, ind: u32) -> Result<BsId, Error> {
        self.resolve(interner, Kind::Bs, RefType::Index(ind))?;
        match self.bs_consts[ind as usize].state {
            State::Done(id) => Ok(id),
            _ => unreachable!(),
        }
    }
}
impl<'a> std::ops::Deref for UnresolvedSymsDefsAndConsts<'a> {
    type Target = ErrorMaker<'a>;

    fn deref(&self) -> &Self::Target {
        &self.error_maker
    }
}
