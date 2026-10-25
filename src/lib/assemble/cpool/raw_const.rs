use crate::assemble::writer::BufWriter;
use crate::util::mstr;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FlatConst<'a, Ref, BsRef> {
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

    MethodHandle(u8, Ref),
    MethodType(Ref),
    Dynamic(BsRef, Ref),
    InvokeDynamic(BsRef, Ref),
    Module(Ref),
    Package(Ref),
}
impl<'a, Ref, BsRef> FlatConst<'a, Ref, BsRef> {
    pub(super) fn is_long(&self) -> bool {
        matches!(self, FlatConst::Long(_) | FlatConst::Double(_))
    }

    pub(super) fn try_map<C, Ref2, BsRef2, E>(
        self,
        ctx: &mut C,
        mut f1: impl FnMut(&mut C, Ref) -> Result<Ref2, E>,
        mut f2: impl FnMut(&mut C, BsRef) -> Result<BsRef2, E>,
    ) -> Result<FlatConst<'a, Ref2, BsRef2>, E> {
        use FlatConst::*;
        match self {
            Utf8(s) => Ok(Utf8(s)),
            Int(v) => Ok(Int(v)),
            Float(v) => Ok(Float(v)),
            Long(v) => Ok(Long(v)),
            Double(v) => Ok(Double(v)),
            Class(r) => Ok(Class(f1(ctx, r)?)),
            Str(r) => Ok(Str(f1(ctx, r)?)),
            Field(r1, r2) => Ok(Field(f1(ctx, r1)?, f1(ctx, r2)?)),
            Method(r1, r2) => Ok(Method(f1(ctx, r1)?, f1(ctx, r2)?)),
            InterfaceMethod(r1, r2) => Ok(InterfaceMethod(f1(ctx, r1)?, f1(ctx, r2)?)),
            NameAndType(r1, r2) => Ok(NameAndType(f1(ctx, r1)?, f1(ctx, r2)?)),
            MethodHandle(tag, r) => Ok(MethodHandle(tag, f1(ctx, r)?)),
            MethodType(r) => Ok(MethodType(f1(ctx, r)?)),
            Dynamic(r1, r2) => Ok(Dynamic(f2(ctx, r1)?, f1(ctx, r2)?)),
            InvokeDynamic(r1, r2) => Ok(InvokeDynamic(f2(ctx, r1)?, f1(ctx, r2)?)),
            Module(r) => Ok(Module(f1(ctx, r)?)),
            Package(r) => Ok(Package(f1(ctx, r)?)),
        }
    }
}

pub(super) type RawConst<'a> = FlatConst<'a, u16, u16>;
impl FlatConst<'_, u16, u16> {
    pub(super) fn write(self, w: &mut BufWriter) {
        use FlatConst::*;
        match self {
            Utf8(s) => {
                let s = s.as_bytes();
                w.u8(1);
                w.u16(s.len().try_into().unwrap());
                w.write(s);
            }
            Int(v) => {
                w.u8(3);
                w.u32(v);
            }
            Float(v) => {
                w.u8(4);
                w.u32(v);
            }
            Long(v) => {
                w.u8(5);
                w.u64(v);
            }
            Double(v) => {
                w.u8(6);
                w.u64(v);
            }
            Class(v) => {
                w.u8(7);
                w.u16(v);
            }
            Str(v) => {
                w.u8(8);
                w.u16(v);
            }
            Field(cls, nat) => {
                w.u8(9);
                w.u16(cls);
                w.u16(nat);
            }
            Method(cls, nat) => {
                w.u8(10);
                w.u16(cls);
                w.u16(nat);
            }
            InterfaceMethod(cls, nat) => {
                w.u8(11);
                w.u16(cls);
                w.u16(nat);
            }
            NameAndType(n, t) => {
                w.u8(12);
                w.u16(n);
                w.u16(t);
            }
            MethodHandle(tag, val) => {
                w.u8(15);
                w.u8(tag);
                w.u16(val);
            }
            MethodType(v) => {
                w.u8(16);
                w.u16(v);
            }
            Dynamic(bs, nat) => {
                w.u8(17);
                w.u16(bs);
                w.u16(nat);
            }
            InvokeDynamic(bs, nat) => {
                w.u8(18);
                w.u16(bs);
                w.u16(nat);
            }
            Module(v) => {
                w.u8(19);
                w.u16(v);
            }
            Package(v) => {
                w.u8(20);
                w.u16(v);
            }
        }
    }
}

#[derive(Debug, Clone, Hash, PartialEq, Eq)]
pub(super) struct FlatBsMeth<Ref> {
    pub(super) mhref: Ref,
    pub(super) args: Vec<Ref>,
}
pub(super) type RawBsMeth = FlatBsMeth<u16>;
impl FlatBsMeth<u16> {
    pub(super) fn write(&self, w: &mut BufWriter) {
        w.u16(self.mhref);
        w.u16(self.args.len().try_into().unwrap());
        for v in self.args.iter().copied() {
            w.u16(v);
        }
    }
}
