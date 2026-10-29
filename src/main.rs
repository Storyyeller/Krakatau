// #![allow(unused)]

mod ass_main;
mod dis_main;
mod file_input_util;
mod file_output_util;

use std::str;

use clap::{Parser, Subcommand};

use ass_main::AssemblerCli;
use ass_main::assembler_main;
use dis_main::DisassemblerCli;
use dis_main::disassembler_main;

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

fn main() {
    let cli = Cli::parse();
    let res = match cli.command {
        Command::Asm(cli) => assembler_main(cli),
        Command::Dis(cli) => disassembler_main(cli),
    };
    if let Err(err) = res {
        eprintln!("Error: {:?}", err);
        // set exit code 1 if there were errors
        std::process::exit(1);
    }
}
