use super::code;
use super::code::MaybePosSet;
use super::code::Pos;
use super::code::PosSet;
use super::cpool::ConstPool;
use super::reader::ParseError;
use super::reader::Reader;
use crate::lib::util::BStr;

///////////////////////////////////////////////////////////////////////////////
#[derive(Debug)]
pub struct BootstrapMethod {
    pub bsref: u16,
    pub args: Vec<u16>,
}
impl BootstrapMethod {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        Ok(Self {
            bsref: r.u16()?,
            args: r.parse_list(Reader::u16)?,
        })
    }
}
///////////////////////////////////////////////////////////////////////////////
#[derive(Debug)]
pub enum ElementValue {
    Anno(Annotation),
    Array(Vec<ElementValue>),
    Enum(u16, u16),

    Class(u16),
    Str(u16),

    Byte(u16),
    Boolean(u16),
    Char(u16),
    Short(u16),
    Int(u16),
    Float(u16),
    Long(u16),
    Double(u16),
}
impl ElementValue {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        use ElementValue::*;
        Ok(match r.u8()? {
            64 => Anno(Annotation::new(r)?),
            66 => Byte(r.u16()?),
            67 => Char(r.u16()?),
            68 => Double(r.u16()?),
            70 => Float(r.u16()?),
            73 => Int(r.u16()?),
            74 => Long(r.u16()?),
            83 => Short(r.u16()?),
            90 => Boolean(r.u16()?),
            91 => Array(r.parse_list(ElementValue::new)?),
            99 => Class(r.u16()?),
            101 => Enum(r.u16()?, r.u16()?),
            115 => Str(r.u16()?),
            _ => return ParseError::s("Invalid element value tag"),
        })
    }
}

#[derive(Debug)]
pub struct Annotation(pub u16, pub Vec<(u16, ElementValue)>);
impl Annotation {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        let desc = r.u16()?;
        let vals = r.parse_list(|r| Ok((r.u16()?, ElementValue::new(r)?)))?;
        Ok(Self(desc, vals))
    }
}

#[derive(Debug, Clone, Copy)]
pub struct LocalVarTargetInfo {
    pub range: Option<(Pos, Pos)>,
    pub index: u16,
}
impl LocalVarTargetInfo {
    fn new(r: &mut Reader, pset: Option<&PosSet>) -> Result<Self, ParseError> {
        let (start, length, index) = (r.u16()?, r.u16()?, r.u16()?);
        // WTF, Java?
        let range = if start == 0xFFFF && length == 0xFFFF {
            None
        } else {
            let start = pset.make(start)?;
            let end = pset.make_off(start, length)?;
            Some((start, end))
        };
        Ok(Self { range, index })
    }
}

type TargetInfo = (u8, TargetInfoData);
#[derive(Debug)]
pub enum TargetInfoData {
    TypeParam(u8),
    Super(u16),
    TypeParamBound(u8, u8),
    Empty,
    FormalParam(u8),
    Throws(u16),
    LocalVar(Vec<LocalVarTargetInfo>),
    Catch(u16),
    Offset(Pos),
    TypeArgument(Pos, u8),
}
impl TargetInfoData {
    fn new(r: &mut Reader, pset: Option<&PosSet>) -> Result<TargetInfo, ParseError> {
        use TargetInfoData::*;
        let tag = r.u8()?;
        let body = match tag {
            0x00 => TypeParam(r.u8()?),
            0x01 => TypeParam(r.u8()?),
            0x10 => Super(r.u16()?),
            0x11 => TypeParamBound(r.u8()?, r.u8()?),
            0x12 => TypeParamBound(r.u8()?, r.u8()?),
            0x13 => Empty,
            0x14 => Empty,
            0x15 => Empty,
            0x16 => FormalParam(r.u8()?),
            0x17 => Throws(r.u16()?),

            0x40 => LocalVar(r.parse_list(|r| LocalVarTargetInfo::new(r, pset))?),
            0x41 => LocalVar(r.parse_list(|r| LocalVarTargetInfo::new(r, pset))?),
            0x42 => Catch(r.u16()?),
            0x43 => Offset(pset.make(r.u16()?)?),
            0x44 => Offset(pset.make(r.u16()?)?),
            0x45 => Offset(pset.make(r.u16()?)?),
            0x46 => Offset(pset.make(r.u16()?)?),
            0x47 => TypeArgument(pset.make(r.u16()?)?, r.u8()?),
            0x48 => TypeArgument(pset.make(r.u16()?)?, r.u8()?),
            0x49 => TypeArgument(pset.make(r.u16()?)?, r.u8()?),
            0x4A => TypeArgument(pset.make(r.u16()?)?, r.u8()?),
            0x4B => TypeArgument(pset.make(r.u16()?)?, r.u8()?),
            _ => return ParseError::s("Invalid target info tag"),
        };
        Ok((tag, body))
    }
}

#[derive(Debug)]
pub struct ParameterAnnotation(pub Vec<Annotation>);
impl ParameterAnnotation {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        Ok(Self(r.parse_list(Annotation::new)?))
    }
}

#[derive(Debug)]
pub struct TypeAnnotation {
    pub info: TargetInfo,
    pub path: Vec<(u8, u8)>,
    pub anno: Annotation,
}
impl TypeAnnotation {
    fn new(r: &mut Reader, pset: Option<&PosSet>) -> Result<Self, ParseError> {
        let info = TargetInfoData::new(r, pset)?;
        let path = r.parse_list_bytelen(|r| Ok((r.u8()?, r.u8()?)))?;
        let anno = Annotation::new(r)?;
        Ok(Self { info, path, anno })
    }
}

///////////////////////////////////////////////////////////////////////////////
#[derive(Debug)]
pub struct RecordComponent<'a> {
    pub name: u16,
    pub desc: u16,
    pub attrs: Vec<Attribute<'a>>,
}
impl<'a> RecordComponent<'a> {
    fn new(r: &mut Reader<'a>, cp: &ConstPool<'a>, pset: Option<&PosSet>) -> Result<Self, ParseError> {
        let name = r.u16()?;
        let desc = r.u16()?;
        let attrs = Attribute::new_list(r, cp, pset, code::CodeOptions::default())?;
        Ok(Self { name, desc, attrs })
    }
}

///////////////////////////////////////////////////////////////////////////////
#[derive(Debug)]
pub struct Requires {
    pub module: u16,
    pub flags: u16,
    pub version: u16,
}
impl Requires {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        Ok(Self {
            module: r.u16()?,
            flags: r.u16()?,
            version: r.u16()?,
        })
    }
}

#[derive(Debug)]
pub struct ModPackage {
    pub package: u16,
    pub flags: u16,
    pub modules: Vec<u16>,
}
impl ModPackage {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        Ok(Self {
            package: r.u16()?,
            flags: r.u16()?,
            modules: r.parse_list(Reader::u16)?,
        })
    }
}

#[derive(Debug)]
pub struct Provides {
    pub cls: u16,
    pub provides_with: Vec<u16>,
}
impl Provides {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        Ok(Self {
            cls: r.u16()?,
            provides_with: r.parse_list(Reader::u16)?,
        })
    }
}

#[derive(Debug)]
pub struct ModuleAttr {
    pub module: u16,
    pub flags: u16,
    pub version: u16,
    pub requires: Vec<Requires>,
    pub exports: Vec<ModPackage>,
    pub opens: Vec<ModPackage>,
    pub uses: Vec<u16>,
    pub provides: Vec<Provides>,
}
impl ModuleAttr {
    fn new(r: &mut Reader) -> Result<Self, ParseError> {
        Ok(Self {
            module: r.u16()?,
            flags: r.u16()?,
            version: r.u16()?,
            requires: r.parse_list(Requires::new)?,
            exports: r.parse_list(ModPackage::new)?,
            opens: r.parse_list(ModPackage::new)?,
            uses: r.parse_list(Reader::u16)?,
            provides: r.parse_list(Provides::new)?,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub struct LocalVarLine {
    pub start: Pos,
    pub end: Pos,
    pub name: u16,
    pub desc: u16,
    pub ind: u16,
}
impl LocalVarLine {
    fn new(r: &mut Reader, pset: Option<&PosSet>) -> Result<Self, ParseError> {
        let start = pset.make(r.u16()?)?;
        let length = r.u16()?;
        let end = pset.make_off(start, length)?;

        Ok(Self {
            start,
            end,
            name: r.u16()?,
            desc: r.u16()?,
            ind: r.u16()?,
        })
    }
}
///////////////////////////////////////////////////////////////////////////////

#[derive(Debug)]
pub enum AttrBody<'a> {
    AnnotationDefault(Box<ElementValue>),
    BootstrapMethods(Vec<BootstrapMethod>),
    Code((Box<code::Code<'a>>, Option<Box<code::Code<'a>>>)),
    ConstantValue(u16),
    Deprecated,
    EnclosingMethod(u16, u16),
    Exceptions(Vec<u16>),
    InnerClasses(Vec<(u16, u16, u16, u16)>),
    LineNumberTable(Vec<(Pos, u16)>),
    LocalVariableTable(Vec<LocalVarLine>),
    LocalVariableTypeTable(Vec<LocalVarLine>),
    MethodParameters(Vec<(u16, u16)>),
    Module(Box<ModuleAttr>),
    ModuleMainClass(u16),
    ModulePackages(Vec<u16>),
    NestHost(u16),
    NestMembers(Vec<u16>),
    PermittedSubclasses(Vec<u16>),
    Record(Vec<RecordComponent<'a>>),

    RuntimeInvisibleAnnotations(Vec<Annotation>),
    RuntimeInvisibleParameterAnnotations(Vec<ParameterAnnotation>),
    RuntimeInvisibleTypeAnnotations(Vec<TypeAnnotation>),
    RuntimeVisibleAnnotations(Vec<Annotation>),
    RuntimeVisibleParameterAnnotations(Vec<ParameterAnnotation>),
    RuntimeVisibleTypeAnnotations(Vec<TypeAnnotation>),

    Signature(u16),
    SourceDebugExtension(&'a [u8]),
    SourceFile(u16),
    StackMapTable(code::StackMapTable),
    Synthetic,

    Raw(&'a [u8]),
}
impl<'a> AttrBody<'a> {
    pub fn new(
        name: &'a [u8],
        data: &'a [u8],
        cp: &ConstPool<'a>,
        pset: Option<&PosSet>,
        code_opts: code::CodeOptions,
    ) -> Self {
        Self::try_parse(name, data, cp, pset, code_opts).unwrap_or(Self::Raw(data))
        // Self::try_parse(name, data, cp).unwrap()
    }

    fn try_parse(
        name: &'a [u8],
        data: &'a [u8],
        cp: &ConstPool<'a>,
        pset: Option<&PosSet>,
        code_opts: code::CodeOptions,
    ) -> Result<Self, ParseError> {
        use AttrBody::*;
        let mut r = Reader(data);
        let r = &mut r;

        let parsed = match name {
            b"AnnotationDefault" => AnnotationDefault(Box::new(ElementValue::new(r)?)),
            b"BootstrapMethods" => BootstrapMethods(r.parse_list(BootstrapMethod::new)?),
            b"Code" => {
                let c = Code(code::Code::parse(r.clone(), cp, code_opts)?);
                r.0 = &[];
                c
            }
            b"ConstantValue" => ConstantValue(r.u16()?),
            b"Deprecated" => Deprecated,
            b"EnclosingMethod" => EnclosingMethod(r.u16()?, r.u16()?),
            b"Exceptions" => Exceptions(r.parse_list(|r| Ok(r.u16()?))?),
            b"InnerClasses" => InnerClasses(r.parse_list(|r| Ok((r.u16()?, r.u16()?, r.u16()?, r.u16()?)))?),
            b"LineNumberTable" => LineNumberTable(r.parse_list(|r| Ok((pset.make(r.u16()?)?, r.u16()?)))?),
            b"LocalVariableTable" => LocalVariableTable(r.parse_list(|r| LocalVarLine::new(r, pset))?),
            b"LocalVariableTypeTable" => LocalVariableTypeTable(r.parse_list(|r| LocalVarLine::new(r, pset))?),
            b"MethodParameters" => MethodParameters(r.parse_list_bytelen(|r| Ok((r.u16()?, r.u16()?)))?),
            b"Module" => Module(Box::new(ModuleAttr::new(r)?)),
            b"ModuleMainClass" => ModuleMainClass(r.u16()?),
            b"ModulePackages" => ModulePackages(r.parse_list(|r| Ok(r.u16()?))?),
            b"NestHost" => NestHost(r.u16()?),
            b"NestMembers" => NestMembers(r.parse_list(|r| Ok(r.u16()?))?),
            b"PermittedSubclasses" => PermittedSubclasses(r.parse_list(|r| Ok(r.u16()?))?),
            b"Record" => Record(r.parse_list(|r| RecordComponent::new(r, cp, pset))?),

            b"RuntimeInvisibleAnnotations" => RuntimeInvisibleAnnotations(r.parse_list(Annotation::new)?),
            b"RuntimeInvisibleParameterAnnotations" => {
                RuntimeInvisibleParameterAnnotations(r.parse_list_bytelen(ParameterAnnotation::new)?)
            }
            b"RuntimeInvisibleTypeAnnotations" => {
                RuntimeInvisibleTypeAnnotations(r.parse_list(|r| TypeAnnotation::new(r, pset))?)
            }
            b"RuntimeVisibleAnnotations" => RuntimeVisibleAnnotations(r.parse_list(Annotation::new)?),
            b"RuntimeVisibleParameterAnnotations" => {
                RuntimeVisibleParameterAnnotations(r.parse_list_bytelen(ParameterAnnotation::new)?)
            }
            b"RuntimeVisibleTypeAnnotations" => {
                RuntimeVisibleTypeAnnotations(r.parse_list(|r| TypeAnnotation::new(r, pset))?)
            }

            b"Signature" => Signature(r.u16()?),
            b"SourceDebugExtension" => SourceDebugExtension(data),
            b"SourceFile" => SourceFile(r.u16()?),
            b"StackMapTable" => StackMapTable(code::StackMapTable::new(r, pset)?),
            b"Synthetic" => Synthetic,

            _ => Raw(data),
        };
        // assert!(r.0.len() == 0);
        Ok(if r.0.len() > 0 { Raw(data) } else { parsed })
        // Ok(parsed)
    }

    pub fn is_raw(&self) -> bool {
        matches!(self, AttrBody::Raw(_))
    }
}

#[derive(Debug)]
pub struct Attribute<'a> {
    pub name: u16,
    pub length: u32,
    pub actual_length: u32,
    pub name_utf: BStr<'a>,
    pub body: AttrBody<'a>,
}
impl<'a> Attribute<'a> {
    pub(super) fn new(
        r: &mut Reader<'a>,
        cp: &ConstPool<'a>,
        pset: Option<&PosSet>,
        allow_stackmap: bool,
        code_opts: code::CodeOptions,
    ) -> Result<Self, ParseError> {
        let name_ind = r.u16()?;
        let length = r.u32()?;

        let name_utf = cp.utf8(name_ind).ok_or(ParseError("Attribute has invalid name index"))?;

        let actual_length = if name_utf == b"InnerClasses" {
            r.clone().u16()? as u32 * 8 + 2
        } else {
            length
        };

        let data = r.get(actual_length as usize)?;
        let mut body = AttrBody::new(name_utf, data, cp, pset, code_opts);

        if !allow_stackmap {
            if let AttrBody::StackMapTable(..) = body {
                body = AttrBody::Raw(data);
            }
        }

        Ok(Self {
            name: name_ind,
            length,
            actual_length,
            name_utf: BStr(name_utf),
            body,
        })
    }

    pub(super) fn new_list(
        r: &mut Reader<'a>,
        cp: &ConstPool<'a>,
        pset: Option<&PosSet>,
        code_opts: code::CodeOptions,
    ) -> Result<Vec<Self>, ParseError> {
        let mut allow_stackmap = true;
        r.parse_list(|r| {
            let attr = Attribute::new(r, cp, pset, allow_stackmap, code_opts)?;
            if let AttrBody::StackMapTable(..) = attr.body {
                allow_stackmap = false;
            }
            Ok(attr)
        })
    }

    pub(super) fn has_ambiguous_short_code(&self) -> bool {
        if let AttrBody::Code((_, Some(_))) = self.body {
            true
        } else {
            false
        }
    }
}
