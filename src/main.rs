// #![allow(unused)]

mod ass_main;
mod dis_main;
mod file_input_util;
mod file_output_util;

use std::str;

use clap::{Parser, Subcommand};

use ass_main::assembler_main;
use ass_main::AssemblerCli;
use dis_main::disassembler_main;
use dis_main::DisassemblerCli;

#[derive(Parser)]
#[clap(author, version, about, long_about = None)]
struct Cli {
    #[clap(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Asm(AssemblerCli),
    Dis(DisassemblerCli),
}

fn real_main() -> i32 {
    let cli = Cli::parse();
    let res = match cli.command {
        Command::Asm(cli) => assembler_main(cli),
        Command::Dis(cli) => disassembler_main(cli),
    };
    if let Err(err) = res {
        println!("Error: {:?}", err);
        // set exit code 1 if there were errors
        1
    } else {
        0
    }
}
fn main() {
    // The actual deeply-recursive work (parsing/assembling and disassembling)
    // now runs on an oversized-stack thread inside `krakatau2::assemble`/
    // `krakatau2::disassemble` themselves, so `real_main` no longer needs to
    // be re-run on one here too.
    std::process::exit(real_main());
}
