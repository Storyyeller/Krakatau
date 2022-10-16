use super::attrs::Attribute;
use super::code::CodeOptions;
use super::cpool::ConstPool;
use super::reader::ParseError;
use super::reader::Reader;

#[derive(Debug, Clone, Copy)]
pub struct ParserOptions {
    pub no_short_code_attr: bool,
}

#[derive(Debug)]
pub struct Field<'a> {
    pub access: u16,
    pub name: u16,
    pub desc: u16,
    pub attrs: Vec<Attribute<'a>>,
}
impl<'a> Field<'a> {
    fn new(r: &mut Reader<'a>, cp: &ConstPool<'a>, code_opts: CodeOptions) -> Result<Self, ParseError> {
        let access = r.u16()?;
        let name = r.u16()?;
        let desc = r.u16()?;
        let attrs = Attribute::new_list(r, cp, None, code_opts)?;

        Ok(Self {
            access,
            name,
            desc,
            attrs,
        })
    }
}

#[derive(Debug)]
pub struct Class<'a> {
    pub version: (u16, u16),
    pub cp: ConstPool<'a>,
    pub access: u16,
    pub this: u16,
    pub super_: u16,

    pub interfaces: Vec<u16>,
    pub fields: Vec<Field<'a>>,
    pub methods: Vec<Field<'a>>,
    pub attrs: Vec<Attribute<'a>>,

    pub has_ambiguous_short_code: bool,
}
impl<'a> Class<'a> {
    fn new(r: &mut Reader<'a>, opts: ParserOptions) -> Result<Self, ParseError> {
        if r.u32()? != 0xCAFEBABE {
            return ParseError::s("Classfile does not start with magic bytes. Are you sure you passed in a classfile?");
        }

        let minor = r.u16()?;
        let major = r.u16()?;
        let version = (major, minor);

        let code_opts = CodeOptions {
            allow_short: version <= (45, 2) && !opts.no_short_code_attr,
        };

        let cp = ConstPool::new(r)?;

        let access = r.u16()?;
        let this = r.u16()?;
        let super_ = r.u16()?;

        let interfaces = r.parse_list(|r| r.u16())?;
        let fields = r.parse_list(|r| Field::new(r, &cp, code_opts))?;
        let methods = r.parse_list(|r| Field::new(r, &cp, code_opts))?;
        let attrs = Attribute::new_list(r, &cp, None, code_opts)?;

        let has_ambiguous_short_code = code_opts.allow_short
            && methods.len() > 0
            && methods
                .iter()
                .all(|m| m.attrs.iter().all(Attribute::has_ambiguous_short_code));

        if r.0.len() > 0 {
            return ParseError::s("Extra data at end of classfile");
        }

        Ok(Class {
            version,
            cp,
            access,
            this,
            super_,
            interfaces,
            fields,
            methods,
            attrs,
            has_ambiguous_short_code,
        })
    }
}

pub fn parse(data: &[u8], opts: ParserOptions) -> Result<Class, ParseError> {
    let mut r = Reader(data);
    Class::new(&mut r, opts)
}
