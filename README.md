Krakatau provides an assembler and disassembler for Java bytecode, which allows you to convert binary classfiles to a human readable text format, make changes, and convert it back to a classfile, even for obfuscated code. You can also create your own classfiles from scratch by writing bytecode manually, and can examine and compare low level details of Java binaries. Unlike `javap`, the Krakatau disassembler can handle even highly obfuscated code, and the disassembled output can be reassembled into a classfile.

Krakatau's assembler syntax is mostly a superset of Jasmin syntax with some minor incompatibilities, but unlike Jasmin, Krakatau has full support for all Java 14 features and even supports some undocumented features found in old versions of the JVM.

Krakatau also provides a decompiler for converting Java binaries to readable source code. Unlike other decompilers, the Krakatau decompiler was specifically designed for working with obfuscated code and can easily handle tricks that break other decompilers. However, the Krakatau decompiler does not support some Java 8+ features such as lambdas, so it works best on older code.

## Installation

Krakatau is pure python, so assuming you have Python already installed, all you need to do is checkout this repository.

## Disassembly

The disassembler has two modes: default and roundtrip. The default mode is optimized for readability and ease of modification of the resulting assembly files. When the output is reassembled, it will result in classfiles that are equivalent in behavior to the original from the perspective of the JVM specification, but not necessarily bit for bit identical (for example, the constant pool entries may be reordered). Roundtrip mode produces output that will reassemble into classfiles that are bit for bit identical to the original, but this means that the assembly files preserve low level encoding information that makes them harder to read, such as the exact order of constant pool entries. **It is recommended to use roundtrip mode when working with code that relies on non-standard attributes, such as CLDC code or Scala code**.

Example usage:

    python Krakatau/disassemble.py -out temp RecordTest.class

    python Krakatau/disassemble.py -out disassembled.zip -roundtrip r0lling-challenge.jar

You can either disassemble an individual classfile, a directory of classfiles, or an entire jar file. If the input filename ends in `.jar`, it will be treated as a jar file. To disassemble a directory recursively, pass the `-r` option.

The `-out` option controls the output location. If it ends in `.jar` or `.zip`, the output will be placed in a single zipfile at that location. Otherwise, it will be treated as a directory name and the output will be placed in individual files under that directory.

To disassemble in roundtrip mode as described above, pass the `-roundtrip` option.

## Assembly

The Krakatau assembler allows you to write Java bytecode in a human friendly text based format and convert it into binary Java classfiles.

    python Krakatau/assemble.py -out temp Krakatau/tests/assembler/good/strictfp.j

    python Krakatau/assemble.py -out alltests.jar -r Krakatau/tests/decompiler/source/

You can either assemble an individual source file, a directory of source files, or an entire jar file containing assembly files. If the input filename ends in `.jar`, it will be treated as a jar file. To assemble a directory recursively, pass the `-r` option. In the case of the jar and directory modes, all files with the extention `.j` will be assembled.

The `-out` option controls the output location. If it ends in `.jar` or `.zip`, the output will be placed in a single zipfile at that location. Otherwise, it will be treated as a directory name and the output will be placed in individual files under that directory.

The `-q` option surpresses all console output other than warnings and errors. This can be useful if you are using Krakatau as part of an automated build system.

## Decompilation

First off, make sure you have Python 2.7 installed. The Krakatau assembler and disassembler support both Python 2.7 and Python 3.5+, but the decompiler only supports Python 2.7.

Next, make sure you have jars containing defintions for any external classes (i.e. libraries) that might be referenced by the jar you are trying to decompile. This includes the standard library classes (i.e. JRT). In versions of Java up to Java 8, this was conveniently provided as a `rt.jar` somewhere in your Java installation. Starting with Java 9, there is no longer any `rt.jar`, but you can use [this tool](https://github.com/Storyyeller/jrt-extractor) to create one. Finding copies of all the libraries used by the target application can unfortunately be a tedious process. In the example below, I took a large number of popular libaries and merged them into a couple of giant jars (`merged.jar`, `merged2.jar`, and `merged3.jar`) in order to save time.

By default Krakatau will attempt to locate the pre-installed `rt.jar` and use that for convenience, but this will not work for any recent version of Java as described above. You can pass `-nauto` to disable this check, such as if you are passing the path to `rt.jar` explicitly.

Example usage:

    python Krakatau/decompile.py -out temp difficult_jars/issue133/sample.jar -nauto -path jres/jrt9.jar -path merged.jar -path merged2.jar -path merged3.jar

The `-out` option controls the output location. If it ends in `.jar` or `.zip`, the output will be placed in a single zipfile at that location. Otherwise, it will be treated as a directory name and the output will be placed in individual files under that directory.

The `-path` option is used to pass the location of any library jars that the decompiled classes reference (see above). You can also pass multiple paths at once as a semicolon separated list.

The `-skip` option will skip errors and continue decompilation whenever an error is encountered during decompilation. By default, Krakatau will immediately stop and print the error message to the console. With `-skip` enabled, you may get partial output with errors printed as comments in the decompiled source files.


