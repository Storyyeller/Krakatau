// #![allow(unused)]
#![allow(special_module_name)]

mod ass_main;
mod dis_main;
mod file_input_util;
mod file_output_util;
mod lib;

use std::str;
use std::thread;

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
    // Workaround for limited stack size in Rust: Spawn a thread with 256mb stack and run everything there.
    let child = thread::Builder::new().stack_size(256 * 1024 * 1024).spawn(real_main).unwrap();
    std::process::exit(child.join().unwrap());
    // std::process::exit(real_main());
}
