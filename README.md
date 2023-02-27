Krakatau provides an assembler and disassembler for Java bytecode, which allows you to convert binary classfiles to a human readable text format, make changes, and convert it back to a classfile, even for obfuscated code. You can also create your own classfiles from scratch by writing bytecode manually, and can examine and compare low level details of Java binaries. Unlike `javap`, the Krakatau disassembler can handle even highly obfuscated code, and the disassembled output can be reassembled into a classfile.

Krakatau's assembler syntax is mostly a superset of Jasmin syntax with some minor incompatibilities, but unlike Jasmin, Krakatau has full support for the Java 19 bytecode specification and even supports some undocumented features found in old versions of the JVM. For an overview of the assembler syntax, see the [tutorial](docs/assembly_tutorial.md) or [complete specification](docs/assembly_specification.md).

## Installation

First, you will need [to install Rust and Cargo](https://www.rust-lang.org/tools/install). Then clone this repo and run `cargo build --release`. This will produce a binary in `target/release/krak2`, which you can call directly, add to PATH, symlink, etc.


## Disassembly

The disassembler has two modes: default and roundtrip. The default mode is optimized for readability and ease of modification of the resulting assembly files. When the output is reassembled, it will result in classfiles that are equivalent in behavior to the original from the perspective of the JVM specification, but not necessarily bit for bit identical (for example, the constant pool entries may be reordered). Roundtrip mode produces output that will reassemble into classfiles that are bit for bit identical to the original, but this means that the assembly files preserve low level encoding information that makes them harder to read, such as the exact order of constant pool entries. **It is recommended to use roundtrip mode when working with code that relies on non-standard attributes, such as CLDC code or Scala code**.

Example usage:

    krak2 dis --out temp RecordTest.class

    krak2 dis --out disassembled.zip --roundtrip r0lling-challenge.jar

You can either disassemble an individual classfile or an entire jar file. If the input filename ends in `.jar` or `.zip`, it will be treated as a jar file. 

The `--out` option controls the output location. If it ends in `.jar` or `.zip`, the output will be placed in a single zipfile at that location. If it ends with `.j` or `.class`, output will be written to that file. Otherwise, it will be treated as a directory name and the output will be placed in individual files under that directory.

To disassemble in roundtrip mode as described above, pass the `--roundtrip` option (or `-r` for short).

## Assembly

The Krakatau assembler allows you to write Java bytecode in a human friendly text based format and convert it into binary Java classfiles.

    krak2 asm --out temp Krakatau/tests/assembler/good/strictfp.j

    krak2 asm --out alltests.jar -r Krakatau/tests/decompiler/source/

You can either assemble an individual `.j` file or an entire jar file. If the input filename ends in `.jar` or `.zip`, it will be treated as a zip archive and every `.j` file inside will be assembled. 

The `--out` option controls the output location. If it ends in `.jar` or `.zip`, the output will be placed in a single zipfile at that location. If it ends with `.j` or `.class`, output will be written to that file. Otherwise, it will be treated as a directory name and the output will be placed in individual files under that directory.
