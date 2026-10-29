use anyhow::Result;
use anyhow::bail;
use clap::Parser;
use std::path::PathBuf;

use crate::file_input_util;
use crate::file_output_util::Writer;
use krakatau2::AssemblerOptions;
use krakatau2::assemble;

#[derive(Parser)]
pub struct AssemblerCli {
    input: PathBuf,
    #[clap(short, long, parse(from_os_str))]
    out: PathBuf,
}

pub fn assembler_main(cli: AssemblerCli) -> Result<()> {
    let opts = AssemblerOptions {};

    let mut writer = Writer::new(&cli.out)?;
    let mut error_count = 0;
    file_input_util::read_files(&cli.input, "j", |fname, data| {
        let data = match std::str::from_utf8(data) {
            Ok(data) => data,
            Err(_) => {
                eprintln!("{}: Error: .j files must be UTF-8 encoded", fname);
                error_count += 1;
                return Ok(());
            }
        };
        // let classes = assemble(&data, opts)?;
        let res = assemble(&data, opts);
        let classes = match res {
            Ok(classes) => classes,
            Err(err) => {
                eprint!("{}", err.format(fname, data));
                error_count += 1;
                return Ok(());
            }
        };
        println!("got {} classes", classes.len());

        for (name, out) in classes {
            let name = name.map(|name| format!("{}.class", name));
            if let Err(err) = writer.write(name.as_deref(), &out) {
                eprintln!("Error writing output for {}: {:#}", fname, err);
                error_count += 1;
            }
        }
        Ok(())
    })?;
    writer.finish()?;

    if error_count > 0 {
        bail!("Finished with {} errors", error_count);
    }
    Ok(())
}
