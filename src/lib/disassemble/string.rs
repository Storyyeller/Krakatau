use super::flags::ALL_FLAGS;
use lazy_static::lazy_static;
use regex::Regex;
use std::borrow::Cow;
use std::fmt::Write;
use std::str;

lazy_static! {
    static ref WORD_RE: Regex = Regex::new(r"\A(?:[a-zA-Z_$\(<]|\[[A-Z\[])[a-zA-Z0-9_$;/\[\(\)<>*+-]*\z").unwrap();
}

fn decode(mut iter: impl Iterator<Item = u8>, mut cb: impl FnMut(u16)) -> bool {
    while let Some(b) = iter.next() {
        match b {
            0b00000001..=0b01111111 => cb(b as u16),
            0b11000000..=0b11011111 => {
                let val = (b as u16) & 31;
                if let Some(b) = iter.next() {
                    let val = (val << 6) ^ (b as u16) & 63;
                    cb(val);
                }
            }
            0b11100000..=0b11101111 => {
                let val = (b as u16) & 15;
                if let Some(b) = iter.next() {
                    let val = (val << 6) ^ (b as u16) & 63;
                    if let Some(b) = iter.next() {
                        let val = (val << 6) ^ (b as u16) & 63;
                        cb(val);
                    }
                }
            }
            _ => return false, // return false to indicate invalid MUTF8
        }
    }
    true
}

fn escape_sub(s: &[u8]) -> (StrLitType, String) {
    let mut out = String::with_capacity(s.len());
    if decode(s.iter().copied(), |c| {
        match c {
            // 0..=7 => write!(&mut out, "\\{}", c),
            34 => write!(&mut out, "\\\""),
            92 => write!(&mut out, "\\\\"),
            32..=126 => write!(&mut out, "{}", char::from_u32(c.into()).unwrap()),
            _ => write!(&mut out, "\\u{:04X}", c),
        }
        .unwrap();
    }) {
        (StrLitType::Regular, out)
    } else {
        (StrLitType::Binary, escape_byte_string(s))
    }
}

fn is_word(s: &str) -> bool {
    WORD_RE.is_match(s) && !ALL_FLAGS.contains(&s)
}

#[derive(PartialEq, Eq, Clone, Copy)]
pub enum StrLitType {
    Unquoted,
    Regular,
    Binary,
}

pub(super) fn escape(s: &[u8]) -> (StrLitType, Cow<str>) {
    if let Ok(s) = str::from_utf8(s) {
        if is_word(s) {
            return (StrLitType::Unquoted, Cow::from(s));
        }
    }

    let (ty, s) = escape_sub(s);
    (ty, Cow::from(s))
}

pub(super) fn escape_byte_string(s: &[u8]) -> String {
    let mut buf = String::with_capacity(s.len() * 4);
    for b in s {
        write!(buf, "\\x{:02X}", b).unwrap();
    }
    buf
}

pub fn parse_utf8(s: &[u8]) -> Option<String> {
    if let Ok(s) = str::from_utf8(s) {
        return Some(s.to_owned());
    }

    let mut u16s = Vec::with_capacity(s.len());
    if !decode(s.iter().copied(), |c16| {
        u16s.push(c16);
    }) {
        return None;
    }

    std::char::decode_utf16(u16s.into_iter()).collect::<Result<String, _>>().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_word() {
        assert!(is_word("hello"));
        assert!(is_word("[Lhello/world;"));
        assert!(is_word("[[[Z"));
        assert!(is_word("<main>"));
        assert!(is_word("(ZZ)[LFoo;"));
        assert!(is_word("foo2"));
        assert!(!is_word(""));
        assert!(!is_word("[42]"));
        assert!(!is_word("0"));
        assert!(!is_word("\n"));
        assert!(!is_word("hello\n"));
        assert!(!is_word("a b"));
        assert!(!is_word("a.b"));
    }

    #[test]
    fn test_escape() {
        assert_eq!(escape(b"hello").1.as_ref(), "hello");
        assert_eq!(escape(b"[42]").1.as_ref(), "[42]");
        assert_eq!(escape(b"s = \"42\";").1.as_ref(), r#"s = \"42\";"#);
        assert_eq!(escape(b"\xC0\x80").1.as_ref(), r#"\u0000"#);
        assert_eq!(escape(b"\xdf\xbf\xef\xbf\xbf").1.as_ref(), r#"\u07FF\uFFFF"#);
        assert_eq!(
            escape(b"\xed\xaf\xbf\xed\xbf\xbf\xed\xaf\x80\xed\xb0\x81").1.as_ref(),
            r#"\uDBFF\uDFFF\uDBC0\uDC01"#
        );
        assert_eq!(
            escape(b"\x3B\x0C\x3D\x06\x34\x01\x25\x04\x34\x16").1.as_ref(),
            r#";\u000C=\u00064\u0001%\u00044\u0016"#
        );
    }

    #[test]
    fn test_escape_byte_string() {
        assert_eq!(escape_byte_string(b"\x00\xAB"), r"\x00\xAB");
    }
}
