use std::borrow::Cow;
use std::cell::Cell;
use std::fmt;
use std::fmt::Display;

use super::string::escape;
use super::string::StrLitType;
use crate::lib::classfile::attrs::BootstrapMethod;
use crate::lib::classfile::cpool::Const;
use crate::lib::classfile::cpool::ConstPool;
use crate::lib::mhtags::MHTAGS;

struct UtfData<'a> {
    stype: StrLitType,
    s: Cow<'a, str>,
    use_count: Cell<u8>,
}
impl<'a> UtfData<'a> {
    fn to_lit(&'a self) -> StringLit<'a> {
        let s = self.s.as_ref();
        StringLit { stype: self.stype, s }
    }

    fn ident(&'a self) -> Option<StringLit<'a>> {
        let s = self.s.as_ref();
        if s.len() < 50 {
            Some(self.to_lit())
        } else if s.len() < 300 && self.use_count.get() < 10 {
            self.use_count.set(self.use_count.get() + 1);
            Some(self.to_lit())
        } else {
            None
        }
    }
}

pub(super) struct StringLit<'a> {
    stype: StrLitType,
    s: &'a str,
}
impl Display for StringLit<'_> {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        use StrLitType::*;
        match self.stype {
            Unquoted => f.write_str(self.s),
            Regular => write!(f, "\"{}\"", self.s),
            Binary => write!(f, "b\"{}\"", self.s),
        }
    }
}

pub(super) enum RefOrString<'a> {
    Raw(u16),
    Sym(u16),
    RawBs(u16),
    Str(StringLit<'a>),
}
use RefOrString::*;
impl Display for RefOrString<'_> {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        use RefOrString::*;
        match self {
            Raw(ind) => write!(f, "[{}]", ind),
            Sym(ind) => write!(f, "[_{}]", ind),
            RawBs(ind) => write!(f, "[bs:{}]", ind),
            Str(sl) => sl.fmt(f),
        }
    }
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
pub enum SingleTag {
    Class,
    String,
    MethodType,
    Module,
    Package,
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
enum PrimTag {
    Int,
    Long,
    Float,
    Double,
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
enum FmimTag {
    Field,
    Method,
    InterfaceMethod,
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
enum DynTag {
    Dynamic,
    InvokeDynamic,
}

enum ConstData<'a> {
    Invalid,
    Utf8(UtfData<'a>),
    Prim(PrimTag, String),
    Single(SingleTag, u16),
    Fmim(FmimTag, u16, u16),
    Nat(u16, u16),

    MethodHandle(u8, u16),
    Dyn(DynTag, u16, u16),
}
impl<'a> ConstData<'a> {
    fn new(roundtrip: bool, c: &Const<'a>) -> Self {
        use Const::*;
        match c {
            Null => ConstData::Invalid,
            Utf8(s) => {
                let (stype, s) = escape(s.0);
                ConstData::Utf8(UtfData {
                    stype,
                    s,
                    use_count: Cell::new(0),
                })
            }

            Int(v) => ConstData::Prim(PrimTag::Int, format!("{}", *v as i32)),
            Long(v) => ConstData::Prim(PrimTag::Long, format!("{}L", *v as i64)),
            Float(v) => ConstData::Prim(PrimTag::Float, {
                let f = f32::from_bits(*v);
                if f.is_nan() {
                    if roundtrip {
                        format!("+NaN<0x{:08X}>f", *v)
                    } else {
                        format!("+NaNf")
                    }
                } else if f.is_infinite() {
                    if f > 0.0 { "+Infinityf" } else { "-Infinityf" }.to_string()
                } else {
                    format!("{:e}f", f)
                }
            }),
            Double(v) => ConstData::Prim(PrimTag::Double, {
                let f = f64::from_bits(*v);
                if f.is_nan() {
                    if roundtrip {
                        format!("+NaN<0x{:016X}>", *v)
                    } else {
                        format!("+NaN")
                    }
                } else if f.is_infinite() {
                    if f > 0.0 { "+Infinity" } else { "-Infinity" }.to_string()
                } else {
                    format!("{:e}", f)
                }
            }),

            Class(v) => ConstData::Single(SingleTag::Class, *v),
            Str(v) => ConstData::Single(SingleTag::String, *v),
            MethodType(v) => ConstData::Single(SingleTag::MethodType, *v),
            Module(v) => ConstData::Single(SingleTag::Module, *v),
            Package(v) => ConstData::Single(SingleTag::Package, *v),

            Field(c, nat) => ConstData::Fmim(FmimTag::Field, *c, *nat),
            Method(c, nat) => ConstData::Fmim(FmimTag::Method, *c, *nat),
            InterfaceMethod(c, nat) => ConstData::Fmim(FmimTag::InterfaceMethod, *c, *nat),

            NameAndType(n, t) => ConstData::Nat(*n, *t),
            MethodHandle(tag, t) => ConstData::MethodHandle(*tag, *t),

            Dynamic(r1, r2) => ConstData::Dyn(DynTag::Dynamic, *r1, *r2),
            InvokeDynamic(r1, r2) => ConstData::Dyn(DynTag::InvokeDynamic, *r1, *r2),
        }
    }
}

struct ConstLine<'a> {
    data: ConstData<'a>,
    force_raw: bool,
    is_defined: Cell<bool>, // used during printing at the end
    sym_used: Cell<bool>,
}
impl<'a> ConstLine<'a> {
    fn new(roundtrip: bool, c: &Const<'a>) -> Self {
        Self {
            data: ConstData::new(roundtrip, c),
            force_raw: roundtrip,
            is_defined: Cell::new(false),
            sym_used: Cell::new(false),
        }
    }
}

pub(super) struct RefPrinter<'a> {
    roundtrip: bool,
    cpool: Vec<ConstLine<'a>>,
    bs: &'a [BootstrapMethod],
}
impl<'a> RefPrinter<'a> {
    pub(super) fn new(
        roundtrip: bool,
        cp: &ConstPool<'a>,
        bs: Option<&'a [BootstrapMethod]>,
        inner_classes: Option<&'a [(u16, u16, u16, u16)]>,
    ) -> Self {
        let mut new = Self {
            roundtrip,
            cpool: cp.0.iter().map(|c| ConstLine::new(roundtrip, c)).collect(),
            bs: bs.unwrap_or(&[]),
        };

        // There is one case where exact references are significant due to a bug in old versions of the JVM. In the InnerClasses attribute, specifying the same index for inner and outer class will fail verification, but specifying different indexes which point to identical class entries will pass (at least in old versions of Java). In this case, we force  references to those indexes to be raw, so they don't get merged and potentially break the class.
        for (inner, outer, _, _) in inner_classes.unwrap_or(&[]).iter().copied() {
            if inner == outer {
                continue;
            }

            if let Some(s1) = cp.clsutf(inner) {
                if let Some(s2) = cp.clsutf(outer) {
                    if s1 == s2 {
                        new.cpool[inner as usize].force_raw = true;
                        new.cpool[outer as usize].force_raw = true;
                    }
                }
            }
        }

        new
    }

    fn get(&self, ind: u16) -> Option<&ConstData<'a>> {
        if let Some(ConstLine {
            data, force_raw: false, ..
        }) = self.cpool.get(ind as usize)
        {
            Some(data)
        } else {
            None
        }
    }

    fn ident(&self, ind: u16) -> Option<StringLit> {
        if let Some(ConstData::Utf8(d)) = self.get(ind) {
            d.ident()
        } else {
            None
        }
    }

    fn symref(&self, ind: u16) -> RefOrString {
        self.cpool[ind as usize].sym_used.set(true);
        Sym(ind)
    }

    pub(super) fn cpref(&self, ind: u16) -> RefOrString {
        if let Some(_) = self.get(ind) {
            self.symref(ind)
        } else {
            Raw(ind)
        }
    }

    pub(super) fn utf(&self, ind: u16) -> RefOrString {
        if let Some(ConstData::Utf8(d)) = self.get(ind) {
            if let Some(sl) = d.ident() {
                Str(sl)
            } else {
                self.symref(ind)
            }
        } else {
            Raw(ind)
        }
    }

    pub(super) fn single(&self, ind: u16, expected: SingleTag) -> RefOrString {
        if let Some(ConstData::Single(tag, v)) = self.get(ind) {
            if *tag != expected {
                return Raw(ind);
            }
            if let Some(sl) = self.ident(*v) {
                Str(sl)
            } else {
                self.symref(ind)
            }
        } else {
            Raw(ind)
        }
    }

    pub(super) fn cls(&self, ind: u16) -> RefOrString {
        self.single(ind, SingleTag::Class)
    }

    pub(super) fn nat(&self, ind: u16) -> impl Display + '_ {
        LazyPrint(move |f: &mut fmt::Formatter| {
            if let Some(ConstData::Nat(n, t)) = self.get(ind) {
                if let Some(sl) = self.ident(*n) {
                    write!(f, "{} {}", sl, self.utf(*t))
                } else {
                    self.symref(ind).fmt(f)
                }
            } else {
                Raw(ind).fmt(f)
            }
        })
    }

    pub(super) fn tagged_fmim(&self, ind: u16) -> impl Display + '_ {
        LazyPrint(move |f: &mut fmt::Formatter| {
            if let Some(ConstData::Fmim(tag, c, nat)) = self.get(ind) {
                write!(f, "{:?} {} {}", *tag, self.cls(*c), self.nat(*nat))
            } else {
                Raw(ind).fmt(f)
            }
        })
    }

    fn tagged_const_nomhdyn(&self, f: &mut fmt::Formatter, ind: u16) -> fmt::Result {
        // Like regular tagged_const except that MethodHandle and Dynamic/InvokeDynamic
        // are replaced with symrefs to prevent recursion or indefinite expansion
        if let Some(c) = self.get(ind) {
            use ConstData::*;
            match c {
                MethodHandle(..) | Dyn(..) => self.symref(ind).fmt(f),
                _ => self.tagged_const_sub(f, c),
            }
        } else {
            Raw(ind).fmt(f)
        }
    }

    fn mhnotref(&self, f: &mut fmt::Formatter, mhtag: u8, r: u16) -> fmt::Result {
        let tag_str = MHTAGS.get(mhtag as usize).copied().unwrap_or("INVALID");
        // todo - inline tagged ref consts
        write!(f, "{} ", tag_str)?;
        self.tagged_const_nomhdyn(f, r)
    }

    fn bsnotref(&self, f: &mut fmt::Formatter, bsm: &BootstrapMethod, tagged: bool) -> fmt::Result {
        if tagged {
            write!(f, "Bootstrap {}", Raw(bsm.bsref))?;
        } else if let Some(ConstData::MethodHandle(mhtag, r)) = self.get(bsm.bsref) {
            self.mhnotref(f, *mhtag, *r)?;
        } else {
            Raw(bsm.bsref).fmt(f)?;
        }

        for bsarg in &bsm.args {
            write!(f, " ")?;
            self.tagged_const_nomhdyn(f, *bsarg)?;
        }
        write!(f, " :")
    }

    fn bs(&self, bsind: u16) -> impl Display + '_ {
        LazyPrint(move |f: &mut fmt::Formatter| {
            if !self.roundtrip {
                if let Some(bsm) = self.bs.get(bsind as usize) {
                    return self.bsnotref(f, bsm, false);
                }
            }

            RawBs(bsind).fmt(f)
        })
    }

    fn tagged_const_sub(&self, f: &mut fmt::Formatter, c: &ConstData) -> fmt::Result {
        use ConstData::*;
        match c {
            Invalid => panic!("Internal error: Please report this!"),
            Utf8(ud) => write!(f, "Utf8 {}", ud.to_lit()),
            Prim(tag, s) => write!(f, "{:?} {}", tag, s),
            Single(tag, r) => write!(f, "{:?} {}", tag, self.utf(*r)),
            Fmim(tag, r1, r2) => write!(f, "{:?} {} {}", tag, self.cls(*r1), self.nat(*r2)),
            Nat(r1, r2) => write!(f, "NameAndType {} {}", self.utf(*r1), self.utf(*r2)),
            MethodHandle(mhtag, r) => {
                f.write_str("MethodHandle ")?;
                self.mhnotref(f, *mhtag, *r)
            }
            Dyn(tag, bs, nat) => write!(f, "{:?} {} {}", tag, self.bs(*bs), self.nat(*nat)),
        }
    }

    #[allow(unused)]
    pub(super) fn tagged_const(&self, ind: u16) -> impl Display + '_ {
        LazyPrint(move |f: &mut fmt::Formatter| {
            if let Some(c) = self.get(ind) {
                self.tagged_const_sub(f, c)
            } else {
                Raw(ind).fmt(f)
            }
        })
    }

    fn ldcrhs_sub(&self, f: &mut fmt::Formatter, ind: u16, c: &ConstData) -> fmt::Result {
        use ConstData::*;
        match c {
            Prim(_tag, s) => write!(f, "{}", s),
            Single(SingleTag::String, r) => {
                if let Some(mut sl) = self.ident(*r) {
                    if sl.stype == StrLitType::Unquoted {
                        sl.stype = StrLitType::Regular;
                    }
                    write!(f, "{}", sl)
                } else {
                    write!(f, "{}", self.symref(ind))
                }
            }
            Single(tag, r) => write!(f, "{:?} {}", tag, self.utf(*r)),

            MethodHandle(..) | Dyn(..) => self.tagged_const_sub(f, c),
            Invalid | Utf8(..) | Fmim(..) | Nat(..) => write!(f, "{}", Raw(ind)),
        }
    }

    pub(super) fn ldc(&self, ind: u16) -> impl Display + '_ {
        LazyPrint(move |f: &mut fmt::Formatter| {
            if let Some(c) = self.get(ind) {
                self.ldcrhs_sub(f, ind, c)
            } else {
                Raw(ind).fmt(f)
            }
        })
    }

    fn cp_def_rhs(&'a self, c: &'a ConstData) -> impl Display + 'a {
        LazyPrint(move |f: &mut fmt::Formatter| self.tagged_const_sub(f, c))
    }

    fn bs_def_rhs(&'a self, bsm: &'a BootstrapMethod) -> impl Display + 'a {
        LazyPrint(move |f: &mut fmt::Formatter| self.bsnotref(f, bsm, true))
    }

    pub(super) fn print_const_defs(self, mut w: impl std::io::Write) -> std::io::Result<()> {
        loop {
            let mut done = true;
            for (ind, line) in self.cpool.iter().enumerate() {
                let ind = ind as u16;

                if let ConstData::Invalid = line.data {
                    continue;
                }
                if !line.is_defined.get() && (line.force_raw || line.sym_used.get()) {
                    let lhs = if line.force_raw { Raw(ind) } else { Sym(ind) };
                    writeln!(w, ".const {} = {}", lhs, self.cp_def_rhs(&line.data))?;
                    line.is_defined.set(true);
                    done = false;
                }
            }
            // In non-roundtrip mode, printing symref defs may result in other
            // constant pool entries being referenced for the first time, so we
            // have to repeat the loop until no more entries are printed
            if done || self.roundtrip {
                break;
            }
        }

        // We never create symbolic bs refs in non-roundtrip mode (printing them inline instead)
        // which makes things easy - print the whole table raw in roundtrip mode, do nothing otherwise
        if self.roundtrip {
            for (ind, bsm) in self.bs.iter().enumerate() {
                let ind = ind as u16;
                writeln!(w, ".bootstrap {} = {}", RawBs(ind), self.bs_def_rhs(bsm))?;
            }
        }
        Ok(())
    }
}

struct LazyPrint<F>(F);
impl<F: Fn(&mut fmt::Formatter) -> fmt::Result> Display for LazyPrint<F> {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        self.0(f)
    }
}
