mod assemble;
mod classfile;
mod disassemble;
mod mhtags;
mod util;

pub use assemble::AssembledClass;
pub use assemble::AssemblerOptions;
pub use assemble::Error as AssemblerError;
pub use assemble::assemble;
pub use classfile::ParseError;
pub use classfile::ParserOptions;
pub use disassemble::DisassemblerOptions;
use disassemble::string::parse_utf8;

#[derive(Debug, Clone)]
pub struct DisassembledClass {
    pub name: Option<String>,
    pub data: String,
}

pub fn disassemble(
    data: &[u8],
    parse_opts: ParserOptions,
    opts: DisassemblerOptions,
) -> Result<DisassembledClass, ParseError> {
    let parsed = classfile::parse(data, parse_opts)?;

    let name = parsed.cp.clsutf(parsed.this).and_then(parse_utf8);

    let mut data = String::with_capacity(1000 + data.len() * 4);
    disassemble::disassemble(&mut data, &parsed, opts).expect("Internal error - please report this!");
    Ok(DisassembledClass { name, data })
}
