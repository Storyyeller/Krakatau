use super::attrs::Attribute;
use super::cpool::ConstPool;
use super::reader::ParseError;
use super::reader::Reader;
use std::collections::HashSet;
use std::fmt;
use std::fmt::Display;

#[derive(Clone, Copy, Debug, Default)]
pub struct CodeOptions {
    pub allow_short: bool,
}

#[derive(PartialEq, Eq, PartialOrd, Ord, Clone, Copy, Debug)]
pub struct Pos(u32);
impl Pos {
    fn off_sub(self, off: i32) -> Result<Self, ParseError> {
        match (self.0 as i64)
            .checked_add(off as i64)
            .map(u32::try_from)
            .and_then(|r| r.ok())
        {
            Some(v) => Ok(Self(v)),
            None => ParseError::s("Bytecode offset overflow"),
        }
    }

    fn off(self, off: impl Into<i32>) -> Result<Self, ParseError> {
        self.off_sub(off.into())
    }

    pub fn is_start(self) -> bool {
        self.0 == 0
    }
}
impl Display for Pos {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "L{}", self.0)
    }
}

pub struct PosSet([u64; 1 << 10], HashSet<u32>);
impl PosSet {
    fn new() -> Self {
        Self([0; 1 << 10], HashSet::new())
    }

    fn add(&mut self, v: Pos) {
        if v.0 <= 0xFFFF {
            self.0[(v.0 >> 6) as usize] |= 1 << (v.0 % 64);
        } else {
            self.1.insert(v.0);
        }
    }

    fn contains(&self, v: Pos) -> bool {
        if v.0 <= 0xFFFF {
            self.0[(v.0 >> 6) as usize] & (1 << (v.0 % 64)) != 0
        } else {
            self.1.contains(&v.0)
        }
    }
}

pub trait MaybePosSet {
    fn check(&self, v: Pos) -> Result<Pos, ParseError>;
    fn validate(&self, v: Pos) -> Result<(), ParseError> {
        self.check(v).map(|_| ())
    }

    fn make(&self, v: u16) -> Result<Pos, ParseError> {
        self.check(Pos(v as u32))
    }
    fn make_off(&self, v: Pos, off: u16) -> Result<Pos, ParseError> {
        self.check(v.off(off)?)
    }
}
impl MaybePosSet for PosSet {
    fn check(&self, v: Pos) -> Result<Pos, ParseError> {
        if self.contains(v) {
            Ok(v)
        } else {
            ParseError::s("Invalid bytecode offset")
        }
    }
}
impl MaybePosSet for Option<&'_ PosSet> {
    fn check(&self, v: Pos) -> Result<Pos, ParseError> {
        if let Some(set) = self {
            set.check(v)
        } else {
            ParseError::s("Invalid bytecode offset outside of Code attribute")
        }
    }
}

#[derive(Debug)]
pub struct SwitchTable {
    pub default: Pos,
    pub low: i32,
    pub table: Vec<Pos>,
}
impl SwitchTable {
    fn new(r: &mut Reader, pos: Pos) -> Result<Self, ParseError> {
        let padding = 3 - (pos.0 as usize % 4);
        // JVM requires padding bytes to be 0, so we don't have to preserve them even in roundtrip mode
        r.get(padding)?;

        let default = pos.off(r.i32()?)?;
        let low = r.i32()?;
        let high = r.i32()?;
        let count = (high - low + 1) as usize;

        let mut table = Vec::with_capacity(count);
        for _ in 0..count {
            table.push(pos.off(r.i32()?)?);
        }

        Ok(Self { default, low, table })
    }
}

#[derive(Debug)]
pub struct SwitchMap {
    pub default: Pos,
    pub table: Vec<(i32, Pos)>,
}
impl SwitchMap {
    fn new(r: &mut Reader, pos: Pos) -> Result<Self, ParseError> {
        let padding = 3 - (pos.0 as usize % 4);
        // JVM requires padding bytes to be 0, so we don't have to preserve them even in roundtrip mode
        r.get(padding)?;

        let default = pos.off(r.i32()?)?;
        let count = r.i32()? as usize;

        let mut table = Vec::with_capacity(count);
        for _ in 0..count {
            table.push((r.i32()?, pos.off(r.i32()?)?));
        }

        Ok(Self { default, table })
    }
}

#[derive(Debug, Default)]
pub struct SwitchArena {
    pub tables: Vec<SwitchTable>,
    pub maps: Vec<SwitchMap>,
}
impl SwitchArena {
    fn alloc_table(&mut self, v: SwitchTable) -> u32 {
        let i = self.tables.len();
        self.tables.push(v);
        i.try_into().unwrap()
    }

    pub fn table(&self, i: u32) -> &SwitchTable {
        &self.tables[i as usize]
    }

    fn alloc_map(&mut self, v: SwitchMap) -> u32 {
        let i = self.maps.len();
        self.maps.push(v);
        i.try_into().unwrap()
    }

    pub fn map(&self, i: u32) -> &SwitchMap {
        &self.maps[i as usize]
    }
}

#[derive(Clone, Copy, Debug)]
pub enum NewArrayTag {
    Boolean,
    Char,
    Float,
    Double,
    Byte,
    Short,
    Int,
    Long,
}
impl NewArrayTag {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        use NewArrayTag::*;
        Ok(match r.u8()? {
            4 => Boolean,
            5 => Char,
            6 => Float,
            7 => Double,
            8 => Byte,
            9 => Short,
            10 => Int,
            11 => Long,
            _ => return ParseError::s("Invalid newarray tag"),
        })
    }
}
impl Display for NewArrayTag {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        use NewArrayTag::*;
        let s = match self {
            Boolean => "boolean",
            Char => "char",
            Float => "float",
            Double => "double",
            Byte => "byte",
            Short => "short",
            Int => "int",
            Long => "long",
        };
        write!(f, "{}", s)
    }
}

#[derive(Debug)]
pub enum WideInstr {
    Iload(u16),
    Lload(u16),
    Fload(u16),
    Dload(u16),
    Aload(u16),
    Istore(u16),
    Lstore(u16),
    Fstore(u16),
    Dstore(u16),
    Astore(u16),
    Iinc(u16, i16),
    Ret(u16),
}
impl WideInstr {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        use WideInstr::*;

        Ok(match r.u8()? {
            0x15 => Iload(r.u16()?),
            0x16 => Lload(r.u16()?),
            0x17 => Fload(r.u16()?),
            0x18 => Dload(r.u16()?),
            0x19 => Aload(r.u16()?),
            0x36 => Istore(r.u16()?),
            0x37 => Lstore(r.u16()?),
            0x38 => Fstore(r.u16()?),
            0x39 => Dstore(r.u16()?),
            0x3A => Astore(r.u16()?),
            0x84 => Iinc(r.u16()?, r.i16()?),
            0xA9 => Ret(r.u16()?),

            _ => return ParseError::s("Invalid wide instr opcode"),
        })
    }
}

#[derive(Debug)]
pub enum Instr {
    Nop,
    AconstNull,
    IconstM1,
    Iconst0,
    Iconst1,
    Iconst2,
    Iconst3,
    Iconst4,
    Iconst5,
    Lconst0,
    Lconst1,
    Fconst0,
    Fconst1,
    Fconst2,
    Dconst0,
    Dconst1,
    Bipush(i8),
    Sipush(i16),
    Ldc(u8),
    LdcW(u16),
    Ldc2W(u16),
    Iload(u8),
    Lload(u8),
    Fload(u8),
    Dload(u8),
    Aload(u8),
    Iload0,
    Iload1,
    Iload2,
    Iload3,
    Lload0,
    Lload1,
    Lload2,
    Lload3,
    Fload0,
    Fload1,
    Fload2,
    Fload3,
    Dload0,
    Dload1,
    Dload2,
    Dload3,
    Aload0,
    Aload1,
    Aload2,
    Aload3,
    Iaload,
    Laload,
    Faload,
    Daload,
    Aaload,
    Baload,
    Caload,
    Saload,
    Istore(u8),
    Lstore(u8),
    Fstore(u8),
    Dstore(u8),
    Astore(u8),
    Istore0,
    Istore1,
    Istore2,
    Istore3,
    Lstore0,
    Lstore1,
    Lstore2,
    Lstore3,
    Fstore0,
    Fstore1,
    Fstore2,
    Fstore3,
    Dstore0,
    Dstore1,
    Dstore2,
    Dstore3,
    Astore0,
    Astore1,
    Astore2,
    Astore3,
    Iastore,
    Lastore,
    Fastore,
    Dastore,
    Aastore,
    Bastore,
    Castore,
    Sastore,
    Pop,
    Pop2,
    Dup,
    DupX1,
    DupX2,
    Dup2,
    Dup2X1,
    Dup2X2,
    Swap,
    Iadd,
    Ladd,
    Fadd,
    Dadd,
    Isub,
    Lsub,
    Fsub,
    Dsub,
    Imul,
    Lmul,
    Fmul,
    Dmul,
    Idiv,
    Ldiv,
    Fdiv,
    Ddiv,
    Irem,
    Lrem,
    Frem,
    Drem,
    Ineg,
    Lneg,
    Fneg,
    Dneg,
    Ishl,
    Lshl,
    Ishr,
    Lshr,
    Iushr,
    Lushr,
    Iand,
    Land,
    Ior,
    Lor,
    Ixor,
    Lxor,
    Iinc(u8, i8),
    I2l,
    I2f,
    I2d,
    L2i,
    L2f,
    L2d,
    F2i,
    F2l,
    F2d,
    D2i,
    D2l,
    D2f,
    I2b,
    I2c,
    I2s,
    Lcmp,
    Fcmpl,
    Fcmpg,
    Dcmpl,
    Dcmpg,
    Ifeq(Pos),
    Ifne(Pos),
    Iflt(Pos),
    Ifge(Pos),
    Ifgt(Pos),
    Ifle(Pos),
    IfIcmpeq(Pos),
    IfIcmpne(Pos),
    IfIcmplt(Pos),
    IfIcmpge(Pos),
    IfIcmpgt(Pos),
    IfIcmple(Pos),
    IfAcmpeq(Pos),
    IfAcmpne(Pos),
    Goto(Pos),
    Jsr(Pos),
    Ret(u8),
    Tableswitch(u32),
    Lookupswitch(u32),
    Ireturn,
    Lreturn,
    Freturn,
    Dreturn,
    Areturn,
    Return,
    Getstatic(u16),
    Putstatic(u16),
    Getfield(u16),
    Putfield(u16),
    Invokevirtual(u16),
    Invokespecial(u16),
    Invokestatic(u16),
    Invokeinterface(u16, u8),
    Invokedynamic(u16),
    New(u16),
    Newarray(NewArrayTag),
    Anewarray(u16),
    Arraylength,
    Athrow,
    Checkcast(u16),
    Instanceof(u16),
    Monitorenter,
    Monitorexit,
    Wide(WideInstr),
    Multianewarray(u16, u8),
    Ifnull(Pos),
    Ifnonnull(Pos),
    GotoW(Pos),
    JsrW(Pos),
}
impl Instr {
    fn new(r: &mut Reader, pos: Pos, switches: &mut SwitchArena) -> Result<Self, ParseError> {
        use Instr::*;

        Ok(match r.u8()? {
            0x00 => Nop,
            0x01 => AconstNull,
            0x02 => IconstM1,
            0x03 => Iconst0,
            0x04 => Iconst1,
            0x05 => Iconst2,
            0x06 => Iconst3,
            0x07 => Iconst4,
            0x08 => Iconst5,
            0x09 => Lconst0,
            0x0A => Lconst1,
            0x0B => Fconst0,
            0x0C => Fconst1,
            0x0D => Fconst2,
            0x0E => Dconst0,
            0x0F => Dconst1,
            0x10 => Bipush(r.i8()?),
            0x11 => Sipush(r.i16()?),
            0x12 => Ldc(r.u8()?),
            0x13 => LdcW(r.u16()?),
            0x14 => Ldc2W(r.u16()?),
            0x15 => Iload(r.u8()?),
            0x16 => Lload(r.u8()?),
            0x17 => Fload(r.u8()?),
            0x18 => Dload(r.u8()?),
            0x19 => Aload(r.u8()?),
            0x1A => Iload0,
            0x1B => Iload1,
            0x1C => Iload2,
            0x1D => Iload3,
            0x1E => Lload0,
            0x1F => Lload1,
            0x20 => Lload2,
            0x21 => Lload3,
            0x22 => Fload0,
            0x23 => Fload1,
            0x24 => Fload2,
            0x25 => Fload3,
            0x26 => Dload0,
            0x27 => Dload1,
            0x28 => Dload2,
            0x29 => Dload3,
            0x2A => Aload0,
            0x2B => Aload1,
            0x2C => Aload2,
            0x2D => Aload3,
            0x2E => Iaload,
            0x2F => Laload,
            0x30 => Faload,
            0x31 => Daload,
            0x32 => Aaload,
            0x33 => Baload,
            0x34 => Caload,
            0x35 => Saload,
            0x36 => Istore(r.u8()?),
            0x37 => Lstore(r.u8()?),
            0x38 => Fstore(r.u8()?),
            0x39 => Dstore(r.u8()?),
            0x3A => Astore(r.u8()?),
            0x3B => Istore0,
            0x3C => Istore1,
            0x3D => Istore2,
            0x3E => Istore3,
            0x3F => Lstore0,
            0x40 => Lstore1,
            0x41 => Lstore2,
            0x42 => Lstore3,
            0x43 => Fstore0,
            0x44 => Fstore1,
            0x45 => Fstore2,
            0x46 => Fstore3,
            0x47 => Dstore0,
            0x48 => Dstore1,
            0x49 => Dstore2,
            0x4A => Dstore3,
            0x4B => Astore0,
            0x4C => Astore1,
            0x4D => Astore2,
            0x4E => Astore3,
            0x4F => Iastore,
            0x50 => Lastore,
            0x51 => Fastore,
            0x52 => Dastore,
            0x53 => Aastore,
            0x54 => Bastore,
            0x55 => Castore,
            0x56 => Sastore,
            0x57 => Pop,
            0x58 => Pop2,
            0x59 => Dup,
            0x5A => DupX1,
            0x5B => DupX2,
            0x5C => Dup2,
            0x5D => Dup2X1,
            0x5E => Dup2X2,
            0x5F => Swap,
            0x60 => Iadd,
            0x61 => Ladd,
            0x62 => Fadd,
            0x63 => Dadd,
            0x64 => Isub,
            0x65 => Lsub,
            0x66 => Fsub,
            0x67 => Dsub,
            0x68 => Imul,
            0x69 => Lmul,
            0x6A => Fmul,
            0x6B => Dmul,
            0x6C => Idiv,
            0x6D => Ldiv,
            0x6E => Fdiv,
            0x6F => Ddiv,
            0x70 => Irem,
            0x71 => Lrem,
            0x72 => Frem,
            0x73 => Drem,
            0x74 => Ineg,
            0x75 => Lneg,
            0x76 => Fneg,
            0x77 => Dneg,
            0x78 => Ishl,
            0x79 => Lshl,
            0x7A => Ishr,
            0x7B => Lshr,
            0x7C => Iushr,
            0x7D => Lushr,
            0x7E => Iand,
            0x7F => Land,
            0x80 => Ior,
            0x81 => Lor,
            0x82 => Ixor,
            0x83 => Lxor,
            0x84 => Iinc(r.u8()?, r.i8()?),
            0x85 => I2l,
            0x86 => I2f,
            0x87 => I2d,
            0x88 => L2i,
            0x89 => L2f,
            0x8A => L2d,
            0x8B => F2i,
            0x8C => F2l,
            0x8D => F2d,
            0x8E => D2i,
            0x8F => D2l,
            0x90 => D2f,
            0x91 => I2b,
            0x92 => I2c,
            0x93 => I2s,
            0x94 => Lcmp,
            0x95 => Fcmpl,
            0x96 => Fcmpg,
            0x97 => Dcmpl,
            0x98 => Dcmpg,
            0x99 => Ifeq(pos.off(r.i16()?)?),
            0x9A => Ifne(pos.off(r.i16()?)?),
            0x9B => Iflt(pos.off(r.i16()?)?),
            0x9C => Ifge(pos.off(r.i16()?)?),
            0x9D => Ifgt(pos.off(r.i16()?)?),
            0x9E => Ifle(pos.off(r.i16()?)?),
            0x9F => IfIcmpeq(pos.off(r.i16()?)?),
            0xA0 => IfIcmpne(pos.off(r.i16()?)?),
            0xA1 => IfIcmplt(pos.off(r.i16()?)?),
            0xA2 => IfIcmpge(pos.off(r.i16()?)?),
            0xA3 => IfIcmpgt(pos.off(r.i16()?)?),
            0xA4 => IfIcmple(pos.off(r.i16()?)?),
            0xA5 => IfAcmpeq(pos.off(r.i16()?)?),
            0xA6 => IfAcmpne(pos.off(r.i16()?)?),
            0xA7 => Goto(pos.off(r.i16()?)?),
            0xA8 => Jsr(pos.off(r.i16()?)?),
            0xA9 => Ret(r.u8()?),
            0xAA => Tableswitch(switches.alloc_table(SwitchTable::new(r, pos)?)),
            0xAB => Lookupswitch(switches.alloc_map(SwitchMap::new(r, pos)?)),
            0xAC => Ireturn,
            0xAD => Lreturn,
            0xAE => Freturn,
            0xAF => Dreturn,
            0xB0 => Areturn,
            0xB1 => Return,
            0xB2 => Getstatic(r.u16()?),
            0xB3 => Putstatic(r.u16()?),
            0xB4 => Getfield(r.u16()?),
            0xB5 => Putfield(r.u16()?),
            0xB6 => Invokevirtual(r.u16()?),
            0xB7 => Invokespecial(r.u16()?),
            0xB8 => Invokestatic(r.u16()?),
            0xB9 => (Invokeinterface(r.u16()?, r.u8()?), r.u8()?).0,
            0xBA => (Invokedynamic(r.u16()?), r.u16()?).0,
            0xBB => New(r.u16()?),
            0xBC => Newarray(NewArrayTag::new(r)?),
            0xBD => Anewarray(r.u16()?),
            0xBE => Arraylength,
            0xBF => Athrow,
            0xC0 => Checkcast(r.u16()?),
            0xC1 => Instanceof(r.u16()?),
            0xC2 => Monitorenter,
            0xC3 => Monitorexit,
            0xC4 => Wide(WideInstr::new(r)?),
            0xC5 => Multianewarray(r.u16()?, r.u8()?),
            0xC6 => Ifnull(pos.off(r.i16()?)?),
            0xC7 => Ifnonnull(pos.off(r.i16()?)?),
            0xC8 => GotoW(pos.off(r.i32()?)?),
            0xC9 => JsrW(pos.off(r.i32()?)?),

            _ => return ParseError::s("Invalid opcode"),
        })
    }

    fn validate(&self, pset: &PosSet, switches: &SwitchArena) -> Result<(), ParseError> {
        use Instr::*;
        match self {
            Ifeq(p) => pset.validate(*p)?,
            Ifne(p) => pset.validate(*p)?,
            Iflt(p) => pset.validate(*p)?,
            Ifge(p) => pset.validate(*p)?,
            Ifgt(p) => pset.validate(*p)?,
            Ifle(p) => pset.validate(*p)?,
            IfIcmpeq(p) => pset.validate(*p)?,
            IfIcmpne(p) => pset.validate(*p)?,
            IfIcmplt(p) => pset.validate(*p)?,
            IfIcmpge(p) => pset.validate(*p)?,
            IfIcmpgt(p) => pset.validate(*p)?,
            IfIcmple(p) => pset.validate(*p)?,
            IfAcmpeq(p) => pset.validate(*p)?,
            IfAcmpne(p) => pset.validate(*p)?,
            Goto(p) => pset.validate(*p)?,
            Jsr(p) => pset.validate(*p)?,
            Tableswitch(i) => {
                let table = switches.table(*i);
                for p in table.table.iter() {
                    pset.validate(*p)?;
                }
                pset.validate(table.default)?
            }
            Lookupswitch(i) => {
                let table = switches.map(*i);
                for (_, p) in table.table.iter() {
                    pset.validate(*p)?;
                }
                pset.validate(table.default)?
            }
            Ifnull(p) => pset.validate(*p)?,
            Ifnonnull(p) => pset.validate(*p)?,
            GotoW(p) => pset.validate(*p)?,
            JsrW(p) => pset.validate(*p)?,
            _ => {}
        };
        Ok(())
    }
}

#[derive(Debug)]
pub struct Bytecode(pub Vec<(Pos, Instr)>, pub Pos, pub SwitchArena);
impl Bytecode {
    fn new(r: &mut Reader) -> Result<(Self, PosSet), ParseError> {
        let len = r.0.len();
        if len > 0xFFFFFFFF {
            return ParseError::s("Bytecode length > 0xFFFFFFFF bytes");
        }

        let mut switches = SwitchArena::default();
        let mut instrs = Vec::new();
        while r.0.len() > 0 {
            let pos = Pos((len - r.0.len()) as u32);
            instrs.push((pos, Instr::new(r, pos, &mut switches)?));
        }
        let endpos = Pos(len as u32);

        // Now that all bytecode is parsed, create set of offsets and check them
        let mut pset = PosSet::new();
        for (p, _) in &instrs {
            pset.add(*p);
        }
        pset.add(endpos);

        for (_, instr) in &instrs {
            instr.validate(&pset, &switches)?;
        }

        Ok((Self(instrs, endpos, switches), pset))
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Except {
    pub start: Pos,
    pub end: Pos,
    pub handler: Pos,
    pub ctype: u16,
}
impl Except {
    fn new(r: &mut Reader, pset: &PosSet) -> Result<Self, ParseError> {
        Ok(Self {
            start: pset.make(r.u16()?)?,
            end: pset.make(r.u16()?)?,
            handler: pset.make(r.u16()?)?,
            ctype: r.u16()?,
        })
    }
}

#[derive(Debug)]
pub struct Code<'a> {
    pub is_short: bool,
    pub stack: u16,
    pub locals: u16,
    pub bytecode: Bytecode,
    pub exceptions: Vec<Except>,
    pub attrs: Vec<Attribute<'a>>,
}
impl<'a> Code<'a> {
    fn new(r: &mut Reader<'a>, cp: &ConstPool<'a>, opts: CodeOptions) -> Result<Self, ParseError> {
        let is_short = opts.allow_short;
        let stack = if is_short { r.u8()? as u16 } else { r.u16()? };
        let locals = if is_short { r.u8()? as u16 } else { r.u16()? };
        let bclen = if is_short { r.u16()? as usize } else { r.u32()? as usize };

        let (bytecode, pset) = Bytecode::new(&mut Reader(r.get(bclen)?))?;

        let exceptions = r.parse_list(|r| Except::new(r, &pset))?;
        let attrs = Attribute::new_list(r, cp, Some(&pset), opts)?;

        if r.0.len() > 0 {
            return ParseError::s("Extra data at end of Code attribute");
        }

        Ok(Self {
            is_short,
            stack,
            locals,
            bytecode,
            exceptions,
            attrs,
        })
    }

    pub(super) fn parse(
        mut r: Reader<'a>,
        cp: &ConstPool<'a>,
        opts: CodeOptions,
    ) -> Result<(Box<Self>, Option<Box<Self>>), ParseError> {
        if opts.allow_short {
            let short = Self::new(&mut r.clone(), cp, opts);
            let long = Self::new(&mut r, cp, CodeOptions { allow_short: false });

            if let Ok(short) = short {
                if let Ok(long) = long {
                    Ok((Box::new(short), Some(Box::new(long))))
                } else {
                    Ok((Box::new(short), None))
                }
            } else {
                Ok((Box::new(long?), None))
            }
        } else {
            let long = Self::new(&mut r, cp, opts);
            Ok((Box::new(long?), None))
        }
    }
}

///////////////////////////////////////////////////////////////////////////////
#[derive(Debug, Clone, Copy)]
pub enum VType {
    Top,
    Int,
    Float,
    Long,
    Double,
    Null,
    UninitThis,
    Object(u16),
    UninitObj(Pos),
}
impl VType {
    fn new(r: &mut Reader, pset: &PosSet) -> Result<Self, ParseError> {
        use VType::*;
        Ok(match r.u8()? {
            0 => Top,
            1 => Int,
            2 => Float,
            3 => Double,
            4 => Long,
            5 => Null,
            6 => UninitThis,
            7 => Object(r.u16()?),
            8 => UninitObj(pset.make(r.u16()?)?),
            _ => return ParseError::s("Invalid verification type"),
        })
    }
}

#[derive(Debug)]
pub enum Frame {
    Same,
    Stack1(VType),
    Stack1Ex(VType),
    Chop(u8),
    SameEx,
    Append(Vec<VType>),
    Full(Vec<VType>, Vec<VType>),
}
impl Frame {
    fn new(r: &mut Reader, pset: &PosSet) -> Result<(Self, u16), ParseError> {
        use Frame::*;
        let tag = r.u8()?;
        let delta = if tag <= 127 { tag as u16 % 64 } else { r.u16()? };

        Ok((
            match tag {
                0..=63 => Same,
                64..=127 => Stack1(VType::new(r, pset)?),
                128..=246 => return ParseError::s("Invalid frame tag"),
                247 => Stack1Ex(VType::new(r, pset)?),
                248..=250 => Chop(251 - tag),
                251 => SameEx,
                252..=254 => {
                    let count = (tag - 251) as usize;
                    let mut vals = Vec::with_capacity(count);
                    for _ in 0..count {
                        vals.push(VType::new(r, pset)?);
                    }
                    Append(vals)
                }
                255 => Full(r.parse_list(|r| VType::new(r, pset))?, r.parse_list(|r| VType::new(r, pset))?),
            },
            delta,
        ))
    }
}

#[derive(Debug)]
pub struct StackMapTable(pub Vec<(Pos, Frame)>);
impl StackMapTable {
    pub(super) fn new(r: &mut Reader, pset: Option<&PosSet>) -> Result<Self, ParseError> {
        let pset = pset.ok_or(ParseError("StackMapTable outside Code attribute"))?;

        let mut pos = Pos(0);
        let mut first = true;

        Ok(Self(r.parse_list(|r| {
            let (frame, delta) = Frame::new(r, pset)?;
            pos = pos.off(delta)?;
            if first {
                first = false;
            } else {
                pos = pos.off(1)?;
            }
            Ok((pset.check(pos)?, frame))
        })?))
    }
}
