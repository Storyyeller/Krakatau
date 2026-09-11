mod assemble;
mod classfile;
mod disassemble;
mod mhtags;
mod util;

pub use assemble::AssemblerOptions;
pub use classfile::ParserOptions;
pub use disassemble::string::parse_utf8;
pub use disassemble::DisassemblerOptions;

// The parser and disassembler are both deeply recursive over nested class
// structure, and can blow the default thread stack (8MB on Linux, as little
// as ~1MB for a Windows main thread) on real-world class files. The CLI used
// to work around this itself by re-running `main` on a thread it spawned
// with a 256MB stack; that workaround lived only in `krak2`'s `main.rs`; a
// library caller invoking `assemble`/`disassemble` directly got whatever
// stack their own thread happened to have, and would see a bare stack
// overflow instead of a normal error. It now lives here instead, so every
// caller -- the CLI included -- gets it for free, with `*_with_stack_size`
// variants for a caller who wants a different size than the default (a
// harness that already knows its inputs are small, say, or one that has
// hit a real input needing more than 256MB).
const DEFAULT_WORKER_STACK_SIZE: usize = 256 * 1024 * 1024;

fn run_with_big_stack<T: Send>(stack_size: Option<usize>, f: impl FnOnce() -> T + Send) -> T {
    std::thread::scope(|scope| {
        std::thread::Builder::new()
            .stack_size(stack_size.unwrap_or(DEFAULT_WORKER_STACK_SIZE))
            .spawn_scoped(scope, f)
            .expect("failed to spawn worker thread")
            .join()
            .unwrap_or_else(|payload| std::panic::resume_unwind(payload))
    })
}

pub fn assemble(
    source: &str,
    opts: AssemblerOptions,
) -> Result<Vec<(Option<String>, Vec<u8>)>, assemble::Error> {
    assemble_with_stack_size(source, opts, None)
}

/// Same as [`assemble`], but on a worker thread with `stack_size` bytes of
/// stack instead of the default 256MB (`None` here means the same default
/// [`assemble`] itself uses).
pub fn assemble_with_stack_size(
    source: &str,
    opts: AssemblerOptions,
    stack_size: Option<usize>,
) -> Result<Vec<(Option<String>, Vec<u8>)>, assemble::Error> {
    run_with_big_stack(stack_size, || assemble::assemble(source, opts))
}

pub fn disassemble(
    data: &[u8],
    parse_opts: ParserOptions,
    opts: DisassemblerOptions,
) -> Result<(Option<String>, Vec<u8>), classfile::ParseError> {
    disassemble_with_stack_size(data, parse_opts, opts, None)
}

/// Same as [`disassemble`], but on a worker thread with `stack_size` bytes of
/// stack instead of the default 256MB (`None` here means the same default
/// [`disassemble`] itself uses).
pub fn disassemble_with_stack_size(
    data: &[u8],
    parse_opts: ParserOptions,
    opts: DisassemblerOptions,
    stack_size: Option<usize>,
) -> Result<(Option<String>, Vec<u8>), classfile::ParseError> {
    run_with_big_stack(stack_size, || {
        let parsed = classfile::parse(data, parse_opts)?;

        let name = parsed.cp.clsutf(parsed.this).and_then(parse_utf8);

        let mut out = Vec::with_capacity(1000 + data.len() * 4);
        disassemble::disassemble(&mut out, &parsed, opts)
            .expect("Internal error - please report this!");
        Ok((name, out))
    })
}
