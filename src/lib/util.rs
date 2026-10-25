use std::fmt::Debug;

#[allow(non_camel_case_types)]
#[repr(transparent)]
#[derive(PartialEq, Eq, Hash)]
/// A string slice that should be MUTF8 encoded.
pub struct mstr(pub [u8]);
impl mstr {
    pub fn new(b: &[u8]) -> &Self {
        // SAFETY: Self is repr(transparent) over [u8] so the cast is safe.
        unsafe { &*(b as *const [u8] as *const Self) }
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }
}
impl std::fmt::Debug for mstr {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if let Some(s) = std::str::from_utf8(&self.0).ok() {
            write!(f, "{:?}", s)
        } else {
            write!(f, "{:?}", &self.0)
        }
    }
}
impl std::fmt::Display for mstr {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        <Self as Debug>::fmt(self, f)
    }
}

pub type MString = Box<mstr>;
