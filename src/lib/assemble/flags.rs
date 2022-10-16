// use std::collections::HashMap;

use super::span::Span;

const FLAG_PAIRS: [(&str, u16); 24] = [
    ("abstract", 0x0400),
    ("annotation", 0x2000),
    ("bridge", 0x0040),
    ("enum", 0x4000),
    ("final", 0x0010),
    ("interface", 0x0200),
    ("mandated", 0x8000),
    ("module", 0x8000),
    ("native", 0x0100),
    ("open", 0x0020),
    ("private", 0x0002),
    ("protected", 0x0004),
    ("public", 0x0001),
    ("static", 0x0008),
    ("static_phase", 0x0040),
    ("strict", 0x0800),
    ("strictfp", 0x0800),
    ("super", 0x0020),
    ("synchronized", 0x0020),
    ("synthetic", 0x1000),
    ("transient", 0x0080),
    ("transitive", 0x0020),
    ("varargs", 0x0080),
    ("volatile", 0x0040),
];

// fn parse_flag(s: &str) -> Option<u16> {
//     lazy_static! {
//         static ref FLAG_MAP: HashMap<&'static str, u16> = FLAG_PAIRS.iter().copied().collect();
//     }
//     FLAG_MAP.get(s).copied()
// }

/// Accumulate a bitset of flags while holding on to the last token in case it was meant to not be a flag
pub struct FlagList {
    flags: u16,
}
impl FlagList {
    pub fn new() -> Self {
        Self { flags: 0 }
    }

    pub fn push<'a>(&mut self, span: Span<'a>) -> Result<(), ()> {
        let ind = FLAG_PAIRS.binary_search_by_key(&span.0, |t| t.0).map_err(|_| ())?;
        let flag = FLAG_PAIRS[ind].1;
        self.flags |= flag;
        Ok(())
    }

    pub fn flush(self) -> u16 {
        self.flags
    }
}
