use anyhow::Result;
use anyhow::bail;
use clap::Parser;
use std::path::PathBuf;

use crate::file_input_util;
use crate::file_output_util::Writer;
use krakatau2::DisassemblerOptions;
use krakatau2::ParserOptions;
use krakatau2::disassemble;

#[derive(Parser)]
pub struct DisassemblerCli {
    input: PathBuf,
    #[arg(short, long)]
    out: Option<PathBuf>,

    #[arg(short, long)]
    roundtrip: bool,

    #[arg(long)]
    no_short_code_attr: bool,
}

pub fn disassembler_main(cli: DisassemblerCli) -> Result<()> {
    let opts = DisassemblerOptions {
        roundtrip: cli.roundtrip,
    };
    let parse_opts = ParserOptions {
        no_short_code_attr: cli.no_short_code_attr,
    };

    let mut writer = match &cli.out {
        Some(out) => Writer::new(out)?,
        None => Writer::Stdout(std::io::stdout()),
    };
    let mut error_count = 0;
    file_input_util::read_files(&cli.input, "class", |fname, data| {
        if cli.out.is_some() {
            println!("disassemble {}", fname);
        }
        let (name, out) = match disassemble(&data, parse_opts, opts) {
            Ok(v) => v,
            Err(err) => {
                eprintln!("Parse error in {}: {}", fname, err.0);
                error_count += 1;
                return Ok(());
            }
        };
        let name = name.map(|name| format!("{}.j", name));
        if let Err(err) = writer.write(name.as_deref(), out.as_bytes()) {
            eprintln!("Error writing output for {}: {:#}", fname, err);
            error_count += 1;
        }
        Ok(())
    })?;
    writer.finish()?;

    if error_count > 0 {
        bail!("Finished with {} errors", error_count);
    }
    Ok(())
}
