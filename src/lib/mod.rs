mod assemble;
mod classfile;
mod disassemble;
mod mhtags;
mod util;

pub use assemble::AssemblerOptions;
pub use assemble::Error as AssemblerError;
pub use assemble::assemble;
pub use classfile::ParseError;
pub use classfile::ParserOptions;
pub use disassemble::DisassemblerOptions;
use disassemble::string::parse_utf8;

pub fn disassemble(
    data: &[u8],
    parse_opts: ParserOptions,
    opts: DisassemblerOptions,
) -> Result<(Option<String>, String), ParseError> {
    let parsed = classfile::parse(data, parse_opts)?;

    let name = parsed.cp.clsutf(parsed.this).and_then(parse_utf8);

    let mut out = String::with_capacity(1000 + data.len() * 4);
    disassemble::disassemble(&mut out, &parsed, opts).expect("Internal error - please report this!");
    Ok((name, out))
}
