pub static MHTAGS: [&str; 10] = [
    "INVALID",
    "getField",
    "getStatic",
    "putField",
    "putStatic",
    "invokeVirtual",
    "invokeStatic",
    "invokeSpecial",
    "newInvokeSpecial",
    "invokeInterface",
];

pub fn parse(s: &str) -> Option<u8> {
    MHTAGS.into_iter().position(|v| v == s).map(|i| i as u8)
}
