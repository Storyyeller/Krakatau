mod base_parser;
mod class_parser;
mod cpool;
mod flags;
mod label;
mod parse_annot;
mod parse_attr;
mod parse_class;
mod parse_code;
mod parse_literal;
mod span;
mod string;
mod tokenize;
mod writer;

use typed_arena::Arena;

use crate::disassemble::string::parse_utf8;
use base_parser::BaseParser;
use class_parser::ClassParser;
pub use span::Error;
use tokenize::tokenize;

#[derive(Debug, Clone, Copy, Default)]
pub struct AssemblerOptions {}

#[derive(Debug, Clone)]
pub struct AssembledClass {
    pub name: Option<String>,
    pub data: Vec<u8>,
}

pub fn assemble(source: &str, _opts: AssemblerOptions) -> Result<Vec<AssembledClass>, Error> {
    let tokens = tokenize(source)?;
    // for tok in &tokens {
    //     println!("{:?}", tok);
    // }

    let arena = Arena::new();
    let mut base_parser = BaseParser::new(source, tokens);
    let mut results = Vec::new();

    while base_parser.has_tokens_left() {
        let parser = ClassParser::new(base_parser, &arena);
        let (parser, (name, data)) = parser.parse()?;
        let name = name.and_then(parse_utf8);
        results.push(AssembledClass { name, data });

        base_parser = parser;
    }

    Ok(results)
}
