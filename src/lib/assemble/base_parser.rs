use super::parse_literal;
use super::span::Error;
use super::span::ErrorMaker;
use super::span::Span;
use super::tokenize::Token;
use super::tokenize::TokenType;

type Iter<'a> = std::iter::Peekable<std::vec::IntoIter<Token<'a>>>;

macro_rules! define_int_parse {
    ($t:ident) => {
        pub fn $t(&mut self) -> Result<$t, Error> {
            let tok = self.int()?;
            parse_literal::int(tok.1 .0).ok_or_else(|| {
                self.error1(&format!("Value must be in range {} <= {} <= {}", $t::MIN, tok.1 .0, $t::MAX), tok.1)
            })
        }
    };
}

pub struct BaseParser<'a> {
    error_maker: ErrorMaker<'a>,
    source: &'a str,
    tokens: Iter<'a>,
}
impl<'a> BaseParser<'a> {
    pub fn new(source: &'a str, tokens: Vec<Token<'a>>) -> Self {
        Self {
            error_maker: ErrorMaker::new(source),
            source,
            tokens: tokens.into_iter().peekable(),
        }
    }

    pub fn has_tokens_left(&mut self) -> bool {
        self.tokens.peek().is_some()
    }

    pub fn next(&mut self) -> Result<Token<'a>, Error> {
        self.tokens.next().ok_or_else(|| {
            let tok = Token(TokenType::Newlines, Span(&self.source[self.source.len()..]));
            self.error1("Error: Unexpected end of file", tok.1)
        })
    }

    pub fn peek(&mut self) -> Result<Token<'a>, Error> {
        self.tokens.peek().copied().ok_or_else(|| {
            let tok = Token(TokenType::Newlines, Span(&self.source[self.source.len()..]));
            self.error1("Error: Unexpected end of file", tok.1)
        })
    }

    pub fn fail<T>(&mut self) -> Result<T, Error> {
        let tok = self.next()?;
        self.err1("Error: Unexpected token", tok.1)
    }

    pub fn tryv(&mut self, v: &str) -> bool {
        self.tokens.next_if(|tok| tok.1 .0 == v).is_some()
    }

    pub fn tryv2(&mut self, v: &str) -> Option<Span<'a>> {
        self.tokens.next_if(|tok| tok.1 .0 == v).map(|tok| tok.1)
    }

    pub fn has_type(&mut self, ty: TokenType) -> bool {
        if let Some(tok) = self.tokens.peek() {
            tok.0 == ty
        } else {
            false
        }
    }

    pub fn val(&mut self, v: &str) -> Result<(), Error> {
        if self.tryv(v) {
            Ok(())
        } else {
            let span = self.next()?.1;
            self.err1str(format!("Expected {}", v), span)
        }
    }

    pub fn assert_type(&mut self, ty: TokenType) -> Result<Span<'a>, Error> {
        let tok = self.next()?;
        if tok.0 == ty {
            Ok(tok.1)
        } else {
            self.fail()
        }
    }

    pub fn eol(&mut self) -> Result<(), Error> {
        let tok = self.next()?;
        if tok.0 == TokenType::Newlines {
            Ok(())
        } else {
            self.err1("Error: Expected end of line", tok.1)
        }
    }

    ///////////////////////////////////////////////////////////////////////////
    pub fn int(&mut self) -> Result<Token<'a>, Error> {
        let tok = self.next()?;
        if tok.0 != TokenType::IntLit {
            self.err1("Expected integer", tok.1)
        } else {
            Ok(tok)
        }
    }

    define_int_parse!(u8);
    define_int_parse!(u16);
    define_int_parse!(u32);

    define_int_parse!(i8);
    define_int_parse!(i16);
    define_int_parse!(i32);
    // define_int_parse!(i64);
    ///////////////////////////////////////////////////////////////////////////
}
impl<'a> std::ops::Deref for BaseParser<'a> {
    type Target = ErrorMaker<'a>;

    fn deref(&self) -> &Self::Target {
        &self.error_maker
    }
}
