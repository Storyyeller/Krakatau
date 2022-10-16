use lazy_static::lazy_static;
use regex::Regex;
use std::collections::HashMap;
use std::convert::TryFrom;
use std::fmt::Display;
use typed_arena::Arena;

use super::base_parser::BaseParser;
use super::cpool;
use super::cpool::types;
use super::cpool::InlineConst;
use super::cpool::Or;
use super::cpool::Pool;
use super::flags::FlagList;
use super::label::Pos;
use super::parse_literal;
use super::span::Error;
use super::span::Span;
use super::string;
use super::tokenize::Token;
use super::tokenize::TokenType;
use super::writer::Writer;
use crate::lib::assemble::span::Spanned;
use crate::lib::mhtags;
use crate::lib::util::BStr;

/// Shorthand function to convert spanned const ref to non-spanned version
pub fn ns<'a, T, U>(r: Or<T, Spanned<'a, U>>) -> Or<T, U> {
    r.map_b(|c| c.v)
}

pub struct ClassParser<'a> {
    pub parser: BaseParser<'a>,
    arena: &'a Arena<Vec<u8>>,

    pub version: (u16, u16),
    pub pool: cpool::Pool<'a>,
    // Temporary values only set during parsing of Code attributes
    pub labels: HashMap<&'a str, Pos>,
    pub stack_map_table: Option<(u16, Writer<'a>)>,
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
    pub fn new(parser: BaseParser<'a>, arena: &'a Arena<Vec<u8>>) -> Self {
        let pool = Pool::new(*parser);
        Self {
            parser,
            arena,
            version: (49, 0),
            pool,
            labels: HashMap::new(),
            stack_map_table: None,
        }
    }

    pub fn ref_type(&self, span: Span<'a>) -> Result<types::RefType<'a>, Error> {
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
            types::RefType::Raw(ind)
        } else {
            types::RefType::Sym(span.of(s))
        })
    }

    pub fn ref_from<T>(&self, span: Span<'a>) -> Result<cpool::RefOr<'a, T>, Error> {
        Ok(Or::A(self.ref_type(span)?))
    }

    pub fn make_utf_ref(&self, b: &'a [u8], span: Span<'a>) -> Result<types::SymSpanUtf8<'a>, Error> {
        if b.len() > u16::MAX as usize {
            self.err1("Constant strings must be at most 65535 bytes in MUTF8 encoding.", span)
        } else {
            Ok(Or::B(span.of(types::InlineUtf8(BStr(b)))))
        }
    }

    pub fn utf_from(&self, tok: Token<'a>) -> Result<types::SymSpanUtf8<'a>, Error> {
        use TokenType::*;
        match tok.0 {
            Word => self.make_utf_ref(tok.1 .0.as_bytes(), tok.1),
            Ref => self.ref_from(tok.1),
            StringLit => {
                // let bs = string::unescape(tok.1 .0).ok_or_else(|| self.error1("Invalid string literal", tok.1))?;
                let bs = string::unescape(tok.1 .0).map_err(|(msg, s)| self.error1(msg, Span(s)))?;
                let bs = self.arena.alloc(bs);
                self.make_utf_ref(bs, tok.1)
            }
            _ => self.err1("Expected identifier or constant pool ref", tok.1),
        }
    }

    pub fn utf(&mut self) -> Result<types::SymSpanUtf8<'a>, Error> {
        let tok = self.next()?;
        self.utf_from(tok)
    }

    pub fn cls_from(&self, tok: Token<'a>) -> Result<types::SymSpanClass<'a>, Error> {
        match tok.0 {
            TokenType::Ref => self.ref_from(tok.1),
            _ => Ok(Or::B(tok.1.of(types::InlineClass(ns(self.utf_from(tok)?))))),
        }
    }

    pub fn cls(&mut self) -> Result<types::SymSpanClass<'a>, Error> {
        let tok = self.next()?;
        self.cls_from(tok)
    }

    pub fn single(
        &mut self,
        f: fn(types::SymUtf8Ref<'a>) -> types::SymConstInline<'a>,
    ) -> Result<types::SymSpanConst<'a>, Error> {
        let tok = self.next()?;
        match tok.0 {
            TokenType::Ref => self.ref_from(tok.1),
            _ => Ok(Or::B(tok.1.of(f(ns(self.utf_from(tok)?))))),
        }
    }

    pub fn nat(&mut self) -> Result<types::SymSpanNat<'a>, Error> {
        let tok = self.next()?;
        if tok.0 == TokenType::Ref {
            self.ref_from(tok.1)
        } else {
            let name = ns(self.utf_from(tok)?);
            let desc = ns(self.utf()?);
            Ok(Or::B(tok.1.of(types::InlineNat(name, desc))))
        }
    }

    pub fn mhnotref(&mut self, tag_span: Span<'a>) -> Result<types::SymSpanConstInline<'a>, Error> {
        let tag = mhtags::parse(tag_span.0).ok_or_else(|| self.error1("Invalid method handle tag", tag_span))?;
        let body = Box::new(ns(self.ref_or_tagged_const()?));
        Ok(tag_span.of(InlineConst::MethodHandle(tag, body)))
    }

    pub fn bs_args(&mut self, mh: types::SymSpanConst<'a>) -> Result<types::SymBsInline<'a>, Error> {
        let mut bsargs = vec![mh];
        while !self.tryv(":") {
            if bsargs.len() >= 65536 {
                // Can have up to 65536 elements because initial mh doesn't count towards length
                // todo - add test
                let next_span = self.peek()?.1;
                return self.err1("Maximum number of arguments to bootstrap method (65535) exceeded", next_span);
            }
            bsargs.push(self.ref_or_tagged_const()?);
        }

        Ok(types::InlineBs(bsargs))
    }

    pub fn bsref(&mut self) -> Result<types::SymBsRef<'a>, Error> {
        let tok = self.next()?;
        match tok.0 {
            TokenType::BsRef => self.ref_from(tok.1),
            TokenType::Word => {
                let mh = Or::B(self.mhnotref(tok.1)?);
                Ok(Or::B(self.bs_args(mh)?))
            }
            _ => self.err1("Expected methodhandle tag or bootstrap ref", tok.1),
        }
    }

    pub fn float_from(&mut self, span: Span<'a>) -> Result<types::SymConstInline<'a>, Error> {
        let s = span.0.trim_end_matches('f');
        Ok(InlineConst::Float(
            parse_literal::float(s).ok_or_else(|| self.error1("Invalid float literal", span))?,
        ))
    }
    pub fn double_from(&mut self, span: Span<'a>) -> Result<types::SymConstInline<'a>, Error> {
        Ok(InlineConst::Double(
            parse_literal::double(span.0).ok_or_else(|| self.error1("Invalid double literal", span))?,
        ))
    }

    pub fn long_from(&mut self, span: Span<'a>) -> Result<types::SymConstInline<'a>, Error> {
        let s = span.0.trim_end_matches('L');
        let i = parse_literal::int::<i64>(s).ok_or_else(|| self.error1("Invalid long literal", span))?;
        Ok(InlineConst::Long(i as u64))
    }
    pub fn int_from(&mut self, span: Span<'a>) -> Result<types::SymConstInline<'a>, Error> {
        let i = parse_literal::int::<i32>(span.0).ok_or_else(|| self.error1("Invalid integer literal", span))?;
        Ok(InlineConst::Int(i as u32))
    }

    pub fn tagged_const_from(&mut self, span: Span<'a>) -> Result<types::SymConstInline<'a>, Error> {
        use InlineConst::*;

        Ok(match span.0 {
            "Utf8" => {
                let tok = self.next()?;
                Utf8(match self.utf_from(tok)? {
                    Or::A(_) => return self.err1("Expected identifier or string, not ref", span),
                    Or::B(b) => b.v.0,
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

            "Class" => Class(ns(self.utf()?)),
            "String" => Str(ns(self.utf()?)),
            "MethodType" => MethodType(ns(self.utf()?)),
            "Module" => Module(ns(self.utf()?)),
            "Package" => Package(ns(self.utf()?)),

            "Field" => Field(ns(self.cls()?), ns(self.nat()?)),
            "Method" => Method(ns(self.cls()?), ns(self.nat()?)),
            "InterfaceMethod" => InterfaceMethod(ns(self.cls()?), ns(self.nat()?)),

            "NameAndType" => NameAndType(ns(self.utf()?), ns(self.utf()?)),
            "MethodHandle" => {
                let tag_span = self.assert_type(TokenType::Word)?;
                self.mhnotref(tag_span)?.v
            }

            "Dynamic" => Dynamic(self.bsref()?, ns(self.nat()?)),
            "InvokeDynamic" => InvokeDynamic(self.bsref()?, ns(self.nat()?)),

            _ => return self.err1("Unrecognized constant tag", span),
        })
    }

    pub fn ref_or_tagged_const(&mut self) -> Result<types::SymSpanConst<'a>, Error> {
        use TokenType::*;
        let tok = self.next()?;
        match tok.0 {
            Ref => self.ref_from(tok.1),
            Word => Ok(Or::B(tok.1.of(self.tagged_const_from(tok.1)?))),
            _ => self.err1("Expected constant pool tag (Utf8, Int, String, NameAndType, etc.) or reference", tok.1),
        }
    }

    pub fn ref_or_tagged_bootstrap(&mut self) -> Result<types::SymSpanBs<'a>, Error> {
        use TokenType::*;
        let tok = self.next()?;

        match tok.0 {
            BsRef => self.ref_from(tok.1),
            Word => {
                let tag_span = tok.1;
                if tag_span.0 != "Bootstrap" {
                    return self.err1("Expected 'Bootstrap' or bootstrap reference", tok.1);
                }

                let tok = self.next()?;
                let mh = match tok.0 {
                    Ref => self.ref_from(tok.1)?,
                    Word => Or::B(self.mhnotref(tok.1)?),
                    _ => return self.err1("Expected methodhandle tag or ref", tok.1),
                };
                Ok(Or::B(tag_span.of(self.bs_args(mh)?)))
            }
            _ => self.err1("Expected 'Bootstrap' or bootstrap reference", tok.1),
        }
    }

    pub fn ldc_rhs(&mut self) -> Result<types::SymSpanConst<'a>, Error> {
        use TokenType::*;

        let tok = self.next()?;
        match tok.0 {
            IntLit => Ok(Or::B(tok.1.of(self.int_from(tok.1)?))),
            FloatLit => Ok(Or::B(tok.1.of(self.float_from(tok.1)?))),
            LongLit => Ok(Or::B(tok.1.of(self.long_from(tok.1)?))),
            DoubleLit => Ok(Or::B(tok.1.of(self.double_from(tok.1)?))),
            StringLit => Ok(Or::B(tok.1.of(types::InlineConst::Str(ns(self.utf_from(tok)?))))),

            Ref => self.ref_from(tok.1),
            Word => Ok(Or::B(tok.1.of(self.tagged_const_from(tok.1)?))),
            _ => self.err1("Expected constant pool tag (Utf8, Int, String, NameAndType, etc.) or reference", tok.1),
        }
    }

    pub fn static_utf(name: &'static str, span: Span<'a>) -> types::SymSpanUtf8<'a> {
        Or::B(span.of(types::InlineUtf8(BStr(name.as_bytes()))))
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
        if tok.0 != TokenType::Word || !tok.1 .0.starts_with('L') {
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
        self.labels
            .get(span.0)
            .map(|p| span.of(*p))
            .ok_or_else(|| self.error1("Undefined label", span))
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
