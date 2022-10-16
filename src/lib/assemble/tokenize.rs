use lazy_static::lazy_static;
use regex::Regex;
use regex::RegexSet;

use super::span::Error;
use super::span::Span;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenType {
    Newlines,
    Colon,
    Equals,
    Directive,
    Word,
    Ref,
    BsRef,
    LabelDef,
    StringLit,
    IntLit,
    LongLit,
    FloatLit,
    DoubleLit,
}

#[derive(Debug, Clone, Copy)]
pub struct Token<'a>(pub TokenType, pub Span<'a>);

pub fn tokenize(source: &str) -> Result<Vec<Token>, Error> {
    use TokenType::*;

    static SET_PATTERNS: &[&str] = &[
        r"\A(?:;.*)?\s+",
        // COLON
        r"\A:($|\s)",
        // EQUALS
        r"\A=($|\s)",
        // DIRECTIVE
        r"\A\.[a-z]+($|\s)",
        // WORD
        r"\A(?-u)(?:[a-zA-Z_$\(<]|\[[A-Z\[])[\w$;/\[\(\)<>*+-]*($|\s)",
        // REF
        r"\A\[[a-z0-9_]+\]($|\s)",
        r"\A\[bs:[a-z0-9_]+\]($|\s)",
        // LABEL_DEF
        r"\AL\w+:($|\s)",
        // STRING_LITERAL
        r#"\Ab?"[^"\n\\]*(?:\\.[^"\n\\]*)*"($|\s)"#,
        r#"\Ab?'[^'\n\\]*(?:\\.[^'\n\\]*)*'($|\s)"#,
        // INT_LITERAL
        r#"\A[+-]?(?:0x[0-9a-fA-F]+|[1-9][0-9]*|0)L?($|\s)"#,
        // FLOAT_LITERAL
        r#"\A[+-]Infinityf?($|\s)"#,
        r#"\A[+-]NaN(?:<0x[0-9a-fA-F]+>)?f?($|\s)"#,
        r#"\A(?-u)[+-]?\d+\.\d+(?:e[+-]?\d+)?f?($|\s)"#, // decimal float
        r#"\A(?-u)[+-]?\d+(?:e[+-]?\d+)f?($|\s)"#,       // decimal float without fraction (exponent mandatory)
        r#"\A(?-u)[+-]?0x[0-9a-fA-F]+(?:\.[0-9a-fA-F]+)?(?:p[+-]?\d+)f?($|\s)"#, // hex float
    ];

    lazy_static! {
        static ref RE_SET: RegexSet = RegexSet::new(SET_PATTERNS).unwrap();
        static ref RE_VEC: Vec<Regex> = SET_PATTERNS.iter().map(|pat| Regex::new(pat).unwrap()).collect();
    }

    let error1 = |msg, tok| Err(Error::new(source, vec![(msg, tok)]));
    let error2 = |msg, tok, msg2, tok2| Err(Error::new(source, vec![(msg, tok), (msg2, tok2)]));

    let mut tokens = Vec::new();
    let mut s = source.trim_end();
    let mut has_newline = true;

    while s.len() > 0 {
        let matches: Vec<_> = RE_SET.matches(s).iter().collect();

        // Invalid token
        if matches.len() == 0 {
            const SUFFIX_LEN: usize = r"($|\s)".len();
            let trimmed_res: Vec<_> = SET_PATTERNS[1..]
                .iter()
                .map(|p| Regex::new(&p[..p.len() - SUFFIX_LEN]).unwrap())
                .collect();

            let best = trimmed_res.into_iter().filter_map(|re| re.find(s)).max_by_key(|m| m.end());
            if let Some(best) = best {
                let size = best.end();
                let tok = Span(&s[..size]);
                let tok2 = Span(&s[size..size]);
                return error2("Error: Invalid token", tok, "Hint: Try adding a space here.", tok2);
            } else if s.starts_with('"') || s.starts_with("'") {
                let tok = Span(&s[..1]);
                return error1("Error: Unclosed string literal", tok);
            } else {
                let tok = Span(s.split_whitespace().next().unwrap());
                return error1("Error: Invalid token", tok);
            }
        }

        assert!(matches.len() == 1);
        let m_i = matches[0];
        let m = RE_VEC[m_i].find(s).unwrap();
        assert!(m.start() == 0);

        let (tok, rest) = s.split_at(m.end());

        if m_i == 0 {
            // whitespace
            if !has_newline && tok.contains('\n') {
                tokens.push(Token(Newlines, Span(tok)));
                has_newline = true;
            }
        } else {
            has_newline = tok.ends_with('\n');
            let tok = tok.trim_end();

            let ty = match m_i {
                1 => Colon,
                2 => Equals,
                3 => Directive,
                4 => Word,
                5 => Ref,
                6 => BsRef,
                7 => LabelDef,
                8..=9 => StringLit,
                10 => {
                    if tok.ends_with('L') {
                        LongLit
                    } else {
                        IntLit
                    }
                }
                11..=15 => {
                    if tok.ends_with('f') {
                        FloatLit
                    } else {
                        DoubleLit
                    }
                }
                _ => panic!("Internal error, please report this"),
            };

            tokens.push(Token(ty, Span(tok)));
            if has_newline {
                tokens.push(Token(Newlines, Span(&s[tok.len()..tok.len() + 1])));
            }
        }
        s = rest;
    }
    if !has_newline {
        tokens.push(Token(Newlines, Span(s)));
    }

    Ok(tokens)
}
