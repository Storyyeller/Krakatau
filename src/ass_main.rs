use std::path::PathBuf;

use clap::Parser;

use crate::file_input_util;
use crate::file_output_util::Writer;
use crate::lib::assemble;
use crate::lib::AssemblerOptions;

#[derive(Parser)]
pub struct AssemblerCli {
    input: PathBuf,
    #[clap(short, long, parse(from_os_str))]
    out: PathBuf,
}

pub fn assembler_main(cli: AssemblerCli) -> i32 {
    let opts = AssemblerOptions {};

    let mut writer = Writer::new(&cli.out);
    let mut error_count = 0;
    file_input_util::read_files(&cli.input, "j", |fname, data| {
        let data = std::str::from_utf8(data).expect(".j files must be utf8-encoded");
        // let classes = assemble(&data, opts)?;
        let res = assemble(&data, opts);
        let classes = match res {
            Ok(classes) => classes,
            Err(err) => {
                err.display(fname, data);
                error_count += 1;
                return;
            }
        };
        println!("got {} classes", classes.len());

        for (name, out) in classes {
            let name = name.map(|name| format!("{}.class", name));
            writer.write(name.as_deref(), &out);
            println!("Wrote {} bytes to {}", out.len(), name.as_deref().unwrap_or("file"));
        }
    });

    // set exit code 1 if there were errors
    if error_count > 0 {
        1
    } else {
        0
    }
}
