mod base_parser;
mod class_parser;
mod cpool;
mod flags;
mod label;
mod parse_attr;
mod parse_class;
mod parse_code;
mod parse_literal;
mod span;
mod string;
mod tokenize;
mod writer;

use typed_arena::Arena;

use crate::lib::disassemble::string::parse_utf8;
use base_parser::BaseParser;
use class_parser::ClassParser;
pub use span::Error;
use tokenize::tokenize;

#[derive(Debug, Clone, Copy)]
pub struct AssemblerOptions {}

pub fn assemble(source: &str, _opts: AssemblerOptions) -> Result<Vec<(Option<String>, Vec<u8>)>, Error> {
    let tokens = tokenize(source)?;
    // for tok in &tokens {
    //     println!("{:?}", tok);
    // }

    let arena = Arena::new();
    let mut base_parser = BaseParser::new(source, tokens);
    let mut results = Vec::new();

    while base_parser.has_tokens_left() {
        let parser = ClassParser::new(base_parser, &arena);
        let (parser, (class_name, data)) = parser.parse()?;
        // let class_name = class_name.and_then(|bs| std::str::from_utf8(bs).ok().map(str::to_owned));
        let class_name = class_name.and_then(parse_utf8);
        results.push((class_name, data));

        base_parser = parser;
        if writer::UNUSED_PH.load(std::sync::atomic::Ordering::Relaxed) {
            panic!("Unused placeholder!");
        }
    }

    Ok(results)
}
