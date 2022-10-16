mod assemble;
mod classfile;
mod disassemble;
mod mhtags;
mod util;

pub use assemble::assemble;
pub use assemble::AssemblerOptions;
pub use assemble::Error as AssembleError;
pub use classfile::ParserOptions;
pub use disassemble::string::parse_utf8;
pub use disassemble::DisassemblerOptions;

pub fn disassemble(
    data: &[u8],
    parse_opts: ParserOptions,
    opts: DisassemblerOptions,
) -> Result<(Option<String>, Vec<u8>), classfile::ParseError> {
    let parsed = classfile::parse(data, parse_opts)?;

    let name = parsed.cp.clsutf(parsed.this).and_then(parse_utf8);

    let mut out = Vec::with_capacity(1000 + data.len() * 4);
    disassemble::disassemble(&mut out, &parsed, opts).expect("Internal error - please report this!");
    Ok((name, out))
}
