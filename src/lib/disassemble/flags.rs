use std::fmt;
static CLASS: [&str; 16] = [
    "public",
    "private",
    "protected",
    "static",
    "final",
    "super",
    "volatile",
    "transient",
    "native",
    "interface",
    "abstract",
    "strict",
    "synthetic",
    "annotation",
    "enum",
    "module",
];
static FIELD: [&str; 16] = [
    "public",
    "private",
    "protected",
    "static",
    "final",
    "super",
    "volatile",
    "transient",
    "native",
    "interface",
    "abstract",
    "strict",
    "synthetic",
    "annotation",
    "enum",
    "module",
];
static METHOD: [&str; 16] = [
    "public",
    "private",
    "protected",
    "static",
    "final",
    "synchronized",
    "bridge",
    "varargs",
    "native",
    "interface",
    "abstract",
    "strict",
    "synthetic",
    "annotation",
    "enum",
    "module",
];
static MOD_REQUIRES: [&str; 16] = [
    "public",
    "private",
    "protected",
    "static",
    "final",
    "transitive",
    "static_phase",
    "transient",
    "native",
    "interface",
    "abstract",
    "strict",
    "synthetic",
    "annotation",
    "enum",
    "mandated",
];
static MOD_OTHER: [&str; 16] = [
    "public",
    "private",
    "protected",
    "static",
    "final",
    "open",
    "volatile",
    "transient",
    "native",
    "interface",
    "abstract",
    "strict",
    "synthetic",
    "annotation",
    "enum",
    "mandated",
];
pub static ALL_FLAGS: [&str; 24] = [
    "abstract",
    "annotation",
    "bridge",
    "enum",
    "final",
    "interface",
    "mandated",
    "module",
    "native",
    "open",
    "private",
    "protected",
    "public",
    "static",
    "static_phase",
    "strict",
    "strictfp",
    "super",
    "synchronized",
    "synthetic",
    "transient",
    "transitive",
    "varargs",
    "volatile",
];

pub(super) struct Flags(&'static [&'static str; 16], u16);
impl fmt::Display for Flags {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        for i in 0..16 {
            if self.1 & (1 << i) != 0 {
                f.write_str(" ")?;
                f.write_str(self.0[i])?;
            }
        }
        Ok(())
    }
}
impl Flags {
    pub(super) fn class(v: u16) -> Flags {
        Flags(&CLASS, v)
    }
    pub(super) fn field(v: u16) -> Flags {
        Flags(&FIELD, v)
    }
    pub(super) fn method(v: u16) -> Flags {
        Flags(&METHOD, v)
    }
    pub(super) fn mod_requires(v: u16) -> Flags {
        Flags(&MOD_REQUIRES, v)
    }
    pub(super) fn mod_other(v: u16) -> Flags {
        Flags(&MOD_OTHER, v)
    }
}
