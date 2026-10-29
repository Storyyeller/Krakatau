use lazy_static::lazy_static;
use regex::Regex;
use std::collections::HashMap;
use std::convert::TryFrom;
use std::fmt::Display;
use typed_arena::Arena;

use super::base_parser::BaseParser;
use super::cpool;
use super::cpool::FlatConst;
use super::cpool::Or;
use super::cpool::Pool;
use super::cpool::RefType;
use super::cpool::UnresolvedConst;
use super::flags::FlagList;
use super::label::Pos;
use super::parse_literal;
use super::span::Error;
use super::span::Span;
use super::string;
use super::tokenize::Token;
use super::tokenize::TokenType;
use super::writer::Writer;
use crate::assemble::span::Spanned;
use crate::mhtags;
use crate::util::mstr;

// The disassembler never nests inline constants more than two deep. Deeper nesting can
// always be written with symbolic references instead, which have no depth limit.
const MAX_CONST_DEPTH: u32 = 8;

pub struct ClassParser<'a> {
    pub parser: BaseParser<'a>,
    arena: &'a Arena<u8>,

    pub version: (u16, u16),
    pub pool: cpool::Pool<'a>,
    // Temporary values only set during parsing of Code attributes
    pub in_code_attr: bool,
    pub labels: HashMap<&'a str, Pos>,
    pub stack_map_table: Option<(u16, Writer<'a>)>,
    // Only set while parsing a Record attribute
    pub in_record_attr: bool,
    // Current nesting depth of inline constants, to avoid stack overflows
    const_depth: u32,
}
impl<'a> std::ops::Deref for ClassParser<'a> {
    type Target = BaseParser<'a>;

    fn deref(&self) -> &Self::Target {
        &self.parser
    }
}
impl<'a> std::ops::DerefMut for ClassParser<'a> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.parser
    }
}
impl<'a> ClassParser<'a> {
    pub fn new(parser: BaseParser<'a>, arena: &'a Arena<u8>) -> Self {
        let pool = Pool::new(*parser);
        Self {
            parser,
            arena,
            version: (49, 0),
            pool,
            in_code_attr: false,
            labels: HashMap::new(),
            stack_map_table: None,
            in_record_attr: false,
            const_depth: 0,
        }
    }

    pub fn ref_type(&self, span: Span<'a>) -> Result<RefType<'a>, Error> {
        lazy_static! {
            static ref DIGITS_RE: Regex = Regex::new(r"\A[0-9]+\z").unwrap();
        }

        let s = span.0;
        let mut s = &s[1..s.len() - 1];
        if s.starts_with("bs:") {
            s = &s[3..];
        }

        Ok(if DIGITS_RE.is_match(s) {
            let ind = s.parse().map_err(|_| self.error1("Invalid numeric reference", span))?;
            RefType::Raw(ind)
        } else {
            RefType::Sym(span.of(s))
        })
    }

    fn make_utf(&self, b: &'a [u8], span: Span<'a>) -> Result<&'a mstr, Error> {
        if b.len() > u16::MAX as usize {
            self.err1("Constant strings must be at most 65535 bytes in MUTF8 encoding.", span)
        } else {
            Ok(mstr::new(b))
        }
    }

    // Parse a utf8 ref or literal without adding the literal to the unresolved constant table or interner.
    // Parsed string literals are still allocated in the string arena.
    fn utf_str_from(&self, tok: Token<'a>) -> Result<Or<RefType<'a>, &'a mstr>, Error> {
        use TokenType::*;
        match tok.0 {
            Word => Ok(Or::B(self.make_utf(tok.1.0.as_bytes(), tok.1)?)),
            Ref => Ok(Or::A(self.ref_type(tok.1)?)),
            StringLit => {
                // let bs = string::unescape(tok.1 .0).ok_or_else(|| self.error1("Invalid string literal", tok.1))?;
                let bs = string::unescape(tok.1.0).map_err(|(msg, s)| self.error1(msg, Span(s)))?;
                let bs = self.arena.alloc_extend(bs);
                Ok(Or::B(self.make_utf(bs, tok.1)?))
            }
            _ => self.err1("Expected identifier or constant pool ref", tok.1),
        }
    }

    pub fn utf_from(&mut self, tok: Token<'a>) -> Result<RefType<'a>, Error> {
        Ok(match self.utf_str_from(tok)? {
            Or::A(r) => r,
            Or::B(s) => self.pool.add_const(tok.1, FlatConst::Utf8(s)),
        })
    }

    pub fn utf(&mut self) -> Result<RefType<'a>, Error> {
        let tok = self.next()?;
        self.utf_from(tok)
    }

    pub fn cls_from(&mut self, tok: Token<'a>) -> Result<RefType<'a>, Error> {
        Ok(match tok.0 {
            TokenType::Ref => self.ref_type(tok.1)?,
            _ => {
                let utf = self.utf_from(tok)?;
                self.pool.add_const(tok.1, FlatConst::Class(utf))
            }
        })
    }

    pub fn cls(&mut self) -> Result<RefType<'a>, Error> {
        let tok = self.next()?;
        self.cls_from(tok)
    }

    pub fn single(&mut self, f: fn(RefType<'a>) -> UnresolvedConst<'a>) -> Result<RefType<'a>, Error> {
        let tok = self.next()?;
        Ok(match tok.0 {
            TokenType::Ref => self.ref_type(tok.1)?,
            _ => {
                let utf = self.utf_from(tok)?;
                self.pool.add_const(tok.1, f(utf))
            }
        })
    }

    pub fn nat(&mut self) -> Result<RefType<'a>, Error> {
        let tok = self.next()?;
        if tok.0 == TokenType::Ref {
            self.ref_type(tok.1)
        } else {
            let name = self.utf_from(tok)?;
            let desc = self.utf()?;
            Ok(self.pool.add_const(tok.1, FlatConst::NameAndType(name, desc)))
        }
    }

    fn mhnotref(&mut self, tag_span: Span<'a>) -> Result<UnresolvedConst<'a>, Error> {
        let tag = mhtags::parse(tag_span.0).ok_or_else(|| self.error1("Invalid method handle tag", tag_span))?;
        let body = self.ref_or_tagged_const()?;
        Ok(FlatConst::MethodHandle(tag, body))
    }

    fn bs_args(&mut self, span: Span<'a>, mhref: RefType<'a>) -> Result<RefType<'a>, Error> {
        let mut args = Vec::new();
        while !self.tryv(":") {
            if args.len() >= 65535 {
                // todo - add test
                let next_span = self.peek()?.1;
                return self.err1("Maximum number of arguments to bootstrap method (65535) exceeded", next_span);
            }
            args.push(self.ref_or_tagged_const()?);
        }

        Ok(self.pool.add_bs(span, mhref, args))
    }

    pub fn bsref(&mut self) -> Result<RefType<'a>, Error> {
        let tok = self.next()?;
        match tok.0 {
            TokenType::BsRef => self.ref_type(tok.1),
            TokenType::Word => {
                let mh = self.mhnotref(tok.1)?;
                let mh = self.pool.add_const(tok.1, mh);
                self.bs_args(tok.1, mh)
            }
            _ => self.err1("Expected methodhandle tag or bootstrap ref", tok.1),
        }
    }

    pub fn float_from(&mut self, span: Span<'a>) -> Result<UnresolvedConst<'a>, Error> {
        let s = span.0.trim_end_matches('f');
        Ok(FlatConst::Float(
            parse_literal::float(s).ok_or_else(|| self.error1("Invalid float literal", span))?,
        ))
    }
    pub fn double_from(&mut self, span: Span<'a>) -> Result<UnresolvedConst<'a>, Error> {
        Ok(FlatConst::Double(
            parse_literal::double(span.0).ok_or_else(|| self.error1("Invalid double literal", span))?,
        ))
    }

    pub fn long_from(&mut self, span: Span<'a>) -> Result<UnresolvedConst<'a>, Error> {
        let s = span.0.trim_end_matches('L');
        let i = parse_literal::int::<i64>(s).ok_or_else(|| self.error1("Invalid long literal", span))?;
        Ok(FlatConst::Long(i as u64))
    }
    pub fn int_from(&mut self, span: Span<'a>) -> Result<UnresolvedConst<'a>, Error> {
        let i = parse_literal::int::<i32>(span.0).ok_or_else(|| self.error1("Invalid integer literal", span))?;
        Ok(FlatConst::Int(i as u32))
    }

    // Every cycle of recursion when parsing nested inline constants passes through here, so this is
    // where the nesting depth is limited.
    pub fn tagged_const_from(&mut self, span: Span<'a>) -> Result<UnresolvedConst<'a>, Error> {
        if self.const_depth >= MAX_CONST_DEPTH {
            let msg = format!(
                "Maximum nesting depth of inline constants ({}) exceeded. Try using a symbolic reference instead.",
                MAX_CONST_DEPTH
            );
            return self.err1str(msg, span);
        }
        self.const_depth += 1;
        let res = self.tagged_const_sub(span);
        self.const_depth -= 1;
        res
    }

    fn tagged_const_sub(&mut self, span: Span<'a>) -> Result<UnresolvedConst<'a>, Error> {
        use FlatConst::*;

        Ok(match span.0 {
            "Utf8" => {
                let tok = self.next()?;
                Utf8(match self.utf_str_from(tok)? {
                    Or::A(_) => return self.err1("Expected identifier or string, not ref", tok.1),
                    Or::B(s) => s,
                })
            }
            "Int" => Int(self.i32()? as u32),
            "Float" => {
                let span = self.assert_type(TokenType::FloatLit)?;
                self.float_from(span)?
            }
            "Long" => {
                let span = self.assert_type(TokenType::LongLit)?;
                self.long_from(span)?
            }
            "Double" => {
                let span = self.assert_type(TokenType::DoubleLit)?;
                self.double_from(span)?
            }

            "Class" => Class(self.utf()?),
            "String" => Str(self.utf()?),
            "MethodType" => MethodType(self.utf()?),
            "Module" => Module(self.utf()?),
            "Package" => Package(self.utf()?),

            "Field" => Field(self.cls()?, self.nat()?),
            "Method" => Method(self.cls()?, self.nat()?),
            "InterfaceMethod" => InterfaceMethod(self.cls()?, self.nat()?),

            "NameAndType" => NameAndType(self.utf()?, self.utf()?),
            "MethodHandle" => {
                let tag_span = self.assert_type(TokenType::Word)?;
                self.mhnotref(tag_span)?
            }

            "Dynamic" => Dynamic(self.bsref()?, self.nat()?),
            "InvokeDynamic" => InvokeDynamic(self.bsref()?, self.nat()?),

            _ => return self.err1("Unrecognized constant tag", span),
        })
    }

    pub fn ref_or_tagged_const(&mut self) -> Result<RefType<'a>, Error> {
        use TokenType::*;
        let tok = self.next()?;
        match tok.0 {
            Ref => self.ref_type(tok.1),
            Word => {
                let c = self.tagged_const_from(tok.1)?;
                Ok(self.pool.add_const(tok.1, c))
            }
            _ => self.err1("Expected constant pool tag (Utf8, Int, String, NameAndType, etc.) or reference", tok.1),
        }
    }

    pub fn ref_or_tagged_bootstrap(&mut self) -> Result<RefType<'a>, Error> {
        use TokenType::*;
        let tok = self.next()?;

        match tok.0 {
            BsRef => self.ref_type(tok.1),
            Word => {
                let tag_span = tok.1;
                if tag_span.0 != "Bootstrap" {
                    return self.err1("Expected 'Bootstrap' or bootstrap reference", tok.1);
                }

                let tok = self.next()?;
                let mh = match tok.0 {
                    Ref => self.ref_type(tok.1)?,
                    Word => {
                        let mh = self.mhnotref(tok.1)?;
                        self.pool.add_const(tok.1, mh)
                    }
                    _ => return self.err1("Expected methodhandle tag or ref", tok.1),
                };
                self.bs_args(tag_span, mh)
            }
            _ => self.err1("Expected 'Bootstrap' or bootstrap reference", tok.1),
        }
    }

    pub fn ldc_rhs(&mut self) -> Result<RefType<'a>, Error> {
        use TokenType::*;

        let tok = self.next()?;
        let c = match tok.0 {
            IntLit => self.int_from(tok.1)?,
            FloatLit => self.float_from(tok.1)?,
            LongLit => self.long_from(tok.1)?,
            DoubleLit => self.double_from(tok.1)?,
            StringLit => FlatConst::Str(self.utf_from(tok)?),

            Ref => return self.ref_type(tok.1),
            Word => self.tagged_const_from(tok.1)?,
            _ => {
                return self.err1("Expected int, float, long, double, or string literal, constant pool tag (Class, String, etc.) or reference", tok.1);
            }
        };
        Ok(self.pool.add_const(tok.1, c))
    }

    pub fn static_utf(&mut self, name: &'static str, span: Span<'a>) -> RefType<'a> {
        self.pool.add_const(span, FlatConst::Utf8(mstr::new(name.as_bytes())))
    }

    pub fn flags(&mut self) -> Result<u16, Error> {
        let mut flags = FlagList::new();
        while self.has_type(TokenType::Word) {
            if flags.push(self.peek()?.1).is_ok() {
                self.next()?;
            } else {
                break;
            }
        }
        Ok(flags.flush())
    }

    /////////////////////////////////////////////////////////////////////////////////////
    pub fn lbl(&mut self) -> Result<Span<'a>, Error> {
        let tok = self.next()?;
        if tok.0 != TokenType::Word || !tok.1.0.starts_with('L') {
            self.err1("Expected label", tok.1)
        } else {
            Ok(tok.1)
        }
    }

    pub fn lbl_to_pos(&self, span: Span<'a>) -> Result<Spanned<'a, Pos>, Error> {
        self.labels
            .get(span.0)
            .map(|p| span.of(*p))
            .ok_or_else(|| self.error1("Undefined label", span))
    }

    pub fn lblpos(&mut self) -> Result<Spanned<'a, Pos>, Error> {
        let span = self.lbl()?;
        self.lbl_to_pos(span)
    }

    fn convert_pos<T: TryFrom<i64> + Display>(&self, span: Span<'a>, v: i64, min: T, max: T) -> Result<T, Error> {
        v.try_into()
            .map_err(|_| self.error1str(format!("Bytecode offset must be {} <= x <= {}, found {}", min, max, v), span))
    }

    pub fn pos_to_u16(&self, pos: Spanned<'a, Pos>) -> Result<u16, Error> {
        self.convert_pos(pos.span, pos.v.0 as i64, u16::MIN, u16::MAX)
    }

    pub fn pos_diff_to_u16(&self, base: Pos, pos: Spanned<'a, Pos>) -> Result<u16, Error> {
        self.convert_pos(pos.span, pos.v.0 as i64 - base.0 as i64, u16::MIN, u16::MAX)
    }
    pub fn pos_diff_to_i16(&self, base: Pos, pos: Spanned<'a, Pos>) -> Result<i16, Error> {
        self.convert_pos(pos.span, pos.v.0 as i64 - base.0 as i64, i16::MIN, i16::MAX)
    }
    pub fn pos_diff_to_i32(&self, base: Pos, pos: Spanned<'a, Pos>) -> Result<i32, Error> {
        self.convert_pos(pos.span, pos.v.0 as i64 - base.0 as i64, i32::MIN, i32::MAX)
    }

    pub fn lbl16(&mut self) -> Result<u16, Error> {
        let pos = self.lblpos()?;
        self.pos_to_u16(pos)
    }
}
