fn mutf8_codepoint(out: &mut Vec<u8>, c: u16) {
    match c {
        1..=127 => out.push(c as u8),
        0 | 0x80..=0x7FF => {
            out.push(0xC0 ^ ((c >> 6) as u8));
            out.push(0x80 ^ ((c & 63) as u8));
        }
        0x800..=0xFFFF => {
            out.push(0xE0 ^ ((c >> 12) as u8));
            out.push(0x80 ^ (((c >> 6) & 63) as u8));
            out.push(0x80 ^ ((c & 63) as u8));
        }
    }
}

fn mutf8_char(out: &mut Vec<u8>, c: char) {
    let c = c as u32;
    if c >= 0x10000 {
        let c = c - 0x10000;
        let high = 0xD800 + ((c >> 10) as u16);
        let low = 0xDC00 + ((c & 0x3FF) as u16);
        mutf8_codepoint(out, high);
        mutf8_codepoint(out, low);
    } else {
        mutf8_codepoint(out, c as u16);
    }
}

pub fn unescape(s: &str) -> Result<Vec<u8>, (&'static str, &str)> {
    let mut out = Vec::with_capacity(s.len() - 2);

    let is_binary = s.starts_with('b');
    let s = s.trim_start_matches('b');
    let mut chars = s.chars();
    let quote = chars.next().unwrap();
    assert!(quote == '"' || quote == '\'');

    while let Some(c) = chars.next() {
        if c == quote {
            break;
        } else if c == '\\' {
            let rest = chars.as_str();

            match chars.next().ok_or(("Premature end of input", rest))? {
                '\\' => out.push('\\' as u8),
                'n' => out.push('\n' as u8),
                'r' => out.push('\r' as u8),
                't' => out.push('\t' as u8),
                '"' => out.push('\"' as u8),
                '\'' => out.push('\'' as u8),
                'u' => {
                    let hex = chars.as_str().get(..4).ok_or(("Illegal unicode escape", rest))?;
                    let c = u16::from_str_radix(hex, 16).map_err(|_| ("Illegal unicode escape", hex))?;
                    mutf8_codepoint(&mut out, c);
                    chars = rest[5..].chars();
                }
                'U' => {
                    let hex = chars.as_str().get(..8).ok_or(("Illegal unicode escape", rest))?;
                    let c = u32::from_str_radix(hex, 16).map_err(|_| ("Illegal unicode escape", hex))?;
                    let c = c.try_into().map_err(|_| ("Illegal unicode code point value", hex))?;
                    mutf8_char(&mut out, c);
                    chars = rest[9..].chars();
                }
                'x' => {
                    let hex = chars.as_str().get(..2).ok_or(("Illegal hex escape", rest))?;
                    let c = u8::from_str_radix(hex, 16).map_err(|_| ("Illegal hex escape", hex))?;
                    if is_binary {
                        out.push(c);
                    } else {
                        // workaround for backwards compat with Krakatau 1
                        mutf8_codepoint(&mut out, c as u16);
                    }
                    chars = rest[3..].chars();
                }
                _ => return Err(("Illegal string escape", rest)),
            }
        } else {
            mutf8_char(&mut out, c);
        }
    }

    Ok(out)
}
