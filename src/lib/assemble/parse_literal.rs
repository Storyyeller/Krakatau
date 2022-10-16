use hexf_parse::parse_hexf32;
use hexf_parse::parse_hexf64;

pub fn int<T>(s: &str) -> Option<T>
where
    T: std::str::FromStr,
    T: TryFrom<i64>,
{
    let s = s.trim_start_matches('+');
    // Hack to support parsing '-0' as unsigned types
    let s = if s == "-0" { "0" } else { s };

    if s.starts_with("-0x") {
        let m = u64::from_str_radix(&s[3..], 16).ok()?;
        if m > 1 << 63 {
            return None;
        }
        let m = (m as i64).wrapping_neg();
        m.try_into().ok()
    } else if s.starts_with("0x") {
        let m = i64::from_str_radix(&s[2..], 16).ok()?;
        m.try_into().ok()
    } else {
        s.parse().ok()
    }
}

pub fn float(s: &str) -> Option<u32> {
    let mut s = s.trim_start_matches('+');
    if s.starts_with("-NaN") {
        s = &s[1..];
    }

    if s.ends_with(">") {
        // todo - test -NaN<...>
        assert!(s.starts_with("NaN<0x"));
        let hex_part = &s[6..s.len() - 1];
        return u32::from_str_radix(hex_part, 16).ok();
    }

    let f = if s.starts_with("0x") || s.starts_with("-0x") {
        parse_hexf32(s, false).ok()
    } else {
        s.parse().ok()
    }?;

    Some(f.to_bits())
}

pub fn double(s: &str) -> Option<u64> {
    let mut s = s.trim_start_matches('+');
    if s.starts_with("-NaN") {
        s = &s[1..];
    }

    if s.ends_with(">") {
        assert!(s.starts_with("NaN<0x"));
        let hex_part = &s[6..s.len() - 1];
        return u64::from_str_radix(hex_part, 16).ok();
    }

    let f = if s.starts_with("0x") || s.starts_with("-0x") {
        parse_hexf64(s, false).ok()
    } else {
        s.parse().ok()
    }?;

    Some(f.to_bits())
}
