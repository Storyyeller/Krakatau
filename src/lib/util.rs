#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct BStr<'a>(pub &'a [u8]);
impl<'a> std::fmt::Debug for BStr<'a> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        String::from_utf8_lossy(self.0).fmt(f)
    }
}
