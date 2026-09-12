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
// structure, and can blow a small thread stack on real-world class files.
// `assemble`/`disassemble` run directly on the caller's own thread and make
// no assumption about how much stack that thread has -- see the CLI's own
// `main.rs` for how much it actually needs there (256MB has been enough for
// every input encountered so far). A caller who wants that same protection,
// or a different amount, can use the `*_with_stack` variants below,
// which run the real work on a freshly spawned worker thread instead.

fn run_on_stack<T: Send>(stack_size: usize, f: impl FnOnce() -> T + Send) -> T {
    std::thread::scope(|scope| {
        std::thread::Builder::new()
            .stack_size(stack_size)
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
    assemble::assemble(source, opts)
}

/// Same as [`assemble`], but runs on a freshly spawned worker thread with
/// exactly `stack_size` bytes of stack, rather than whatever the caller's own
/// thread happens to have.
pub fn assemble_with_stack(
    source: &str,
    opts: AssemblerOptions,
    stack_size: usize,
) -> Result<Vec<(Option<String>, Vec<u8>)>, assemble::Error> {
    run_on_stack(stack_size, || assemble::assemble(source, opts))
}

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

/// Same as [`disassemble`], but runs on a freshly spawned worker thread with
/// exactly `stack_size` bytes of stack, rather than whatever the caller's own
/// thread happens to have.
pub fn disassemble_with_stack(
    data: &[u8],
    parse_opts: ParserOptions,
    opts: DisassemblerOptions,
    stack_size: usize,
) -> Result<(Option<String>, Vec<u8>), classfile::ParseError> {
    run_on_stack(stack_size, || disassemble(data, parse_opts, opts))
}
