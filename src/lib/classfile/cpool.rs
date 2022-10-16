use super::reader::ParseError;
use super::reader::Reader;
use crate::lib::util::BStr;

#[derive(Debug)]
pub enum Const<'a> {
    Null, // 0 unused
    Utf8(BStr<'a>),
    // 2 unused
    Int(u32),
    Float(u32),
    Long(u64),
    Double(u64),
    Class(u16),
    Str(u16),
    Field(u16, u16),
    Method(u16, u16),
    InterfaceMethod(u16, u16),
    NameAndType(u16, u16),
    // 13 unused
    // 14 unused
    MethodHandle(u8, u16),
    MethodType(u16),
    Dynamic(u16, u16),
    InvokeDynamic(u16, u16),
    Module(u16),
    Package(u16),
}
impl<'a> Const<'a> {
    fn read(r: &mut Reader<'a>) -> Result<(Self, bool), ParseError> {
        use Const::*;
        let tag = r.u8()?;
        Ok((
            match tag {
                1 => {
                    let count = r.u16()?;
                    Utf8(BStr(r.get(count as usize)?))
                }
                3 => Int(r.u32()?),
                4 => Float(r.u32()?),
                5 => Long(r.u64()?),
                6 => Double(r.u64()?),
                7 => Class(r.u16()?),
                8 => Str(r.u16()?),
                9 => Field(r.u16()?, r.u16()?),
                10 => Method(r.u16()?, r.u16()?),
                11 => InterfaceMethod(r.u16()?, r.u16()?),
                12 => NameAndType(r.u16()?, r.u16()?),
                15 => MethodHandle(r.u8()?, r.u16()?),
                16 => MethodType(r.u16()?),
                17 => Dynamic(r.u16()?, r.u16()?),
                18 => InvokeDynamic(r.u16()?, r.u16()?),
                19 => Module(r.u16()?),
                20 => Package(r.u16()?),
                _ => return ParseError::s("Unrecognized constant pool tag"),
            },
            tag == 5 || tag == 6,
        ))
    }
}

#[derive(Debug)]
pub struct ConstPool<'a>(pub Vec<Const<'a>>);
impl<'a> ConstPool<'a> {
    pub(super) fn new(r: &mut Reader<'a>) -> Result<Self, ParseError> {
        let count = r.u16()? as usize;
        let mut cp = Vec::with_capacity(count);
        cp.push(Const::Null);
        while cp.len() < count {
            let (entry, extra) = Const::read(r)?;
            // println!("const[{}] = {:?}", cp.len(), entry);
            cp.push(entry);
            if extra {
                cp.push(Const::Null)
            }
        }
        Ok(Self(cp))
    }

    pub fn utf8(&self, i: u16) -> Option<&'a [u8]> {
        self.0
            .get(i as usize)
            .and_then(|c| if let Const::Utf8(s) = c { Some(s.0) } else { None })
    }

    pub fn clsutf(&self, i: u16) -> Option<&'a [u8]> {
        self.0.get(i as usize).and_then(|c| {
            if let Const::Class(utf_ind) = c {
                self.utf8(*utf_ind)
            } else {
                None
            }
        })
    }
}
