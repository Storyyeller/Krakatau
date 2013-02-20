Krakatau Bytecode Tools
Copyright (C) 2012-13 Robert Grosse

=== Introduction ===

Krakatau currently contains three tools - a decompiler and disassembler for 
Java classfiles and an assembler to create classfiles.

=== Requirements ===

Krakatau requires Python 2.7. The assembler additionally requires a free
Python library called PLY. Note that if you want to do decompilation, you'll
probably want an installation of the JDK as well. For assembly and disassembly,
a Java installation is not strictly necessary, but it is still useful for
testing the resulting classes.

=== Decompilation ===

Usage: 
python Krakatau\decompile.py [-nauto] [-path PATH] [-out OUT] [-r] target

PATH : An optional list of directories, jars, or zipfiles to search for 
	classes in. Krakatau will attempt to automatically detect and add the 
	jar containing core language classes, but you can disable this with
	the -nauto option.

OUT : File or directory name where source files are to be written. Defaults 
	to the current directory

-r : Decompiles all .class files found in the directory target (recursively)

target : Class name or jar name to decompile. If a jar is specified, all
	classes in the jar will be decompiled. If -r is specified, this should
	be a directory.

The Krakatau decompiler takes a different approach to most Java decompilers.
It can be thought of more as a compiler whose input language is Java bytecode
and whose target language happens to be Java source code. Krakatau takes in 
arbitrary bytecode, and attempts to transform it to equivalent Java code. This
makes it robust to minor obfuscation, though it has the drawback of not
reconstructing the "original" source, leading to less readable output than a 
pattern matching decompiler would produce for unobfuscated Java classes. 

However, it will not always produce valid Java since there are some things 
that are difficult or impossible to decompile at all thanks to the limitations
of the Java language. In most cases, Krakatau will try to at least produce
readable pseudocode, but sometimes it may just throw an exception.

Note: decompilation produces a file called "cache.txt" in the current
	directory. This stores information about the standard library so it 
	doesn't have to be loaded every time. However, if you change the library,
	you should delete the cache.

=== Assembly ===

Usage: 
python Krakatau\assemble.py [-out OUT] [-g] [-jas] [-r] target

OUT : File or directory name where class files are to be written. Defaults 
	to the current directory 

-g : If specified, SourceFile and LineNumberTable attributes giving the 
	offset of every instruction will be added. This is useful for debugging
	exceptions, as it will let the JVM print the origin of the exception
	in the traceback. If these attributes are already specified manually,
	they will not be overridden.

-jas : Enables Jasmin compatibility mode. Specifying 'all' as the exception
	handler type will implicitly catch all exceptions rather than catching a
	class named all. The ACC_SUPER flag is added to classes even if not
	specified. A SourceFile attribute based on the filename is added if no
	SourceFile attribute is specified. The classfile version defaults to 
	45.3 instead of 49.0. 

-r : Assembles all .j files found in the directory target (recursively)

target : Name of file to assemble. If -r is specified, this should be a 
	directory.

The Krakatau assembler is intended as a replacement for Jasmin, and was 
originally written due to the limitations of Jasmin. It is backwards compatible 
with Jasmin, but it also offers many new features, as well as simplifying the 
syntax. Note that for full compatibility, some Jasmin quirks require the 
-jas flag to be enabled, but most Jasmin syntax will work even without it.

A tutorial on writing Java Bytecode Assembly with Krakatau is available at 
https://greyhat.gatech.edu/wiki/index.php?title=Java_Assembly_Tutorial.

The assembler uses PLY, which will generate a file called "parsetab.py" in
the current directory.

=== Disassembly ===

Usage: 
python Krakatau\disassemble.py [-out OUT] [-r] target

OUT : File or directory name where source files are to be written. Defaults 
	to the current directory

-r : Disassembles all .class files found in the directory target (recursively)

target : Filename or jar name to disassemble. If a jar is specified, all
	classes in the jar will be disassembled. If -r is specified, this should
	be a directory.

This takes a classfile and converts it into a human readable assembly format.
Unlike Javap, this can handle even pathological classes, and the output can 
be reassembled. Together with the Krakatau assembler, this tool should be 
able to roundtrip any class through assembly and back into an equivalent 
class with the following caveat:

* Attributes other than Code, ConstantValue, StackMapTable, BootstrapMethods, 
	Exceptions, and SourceFile are currently ignored. The disassembler does not 
	attempt to disassemble LineNumberTable or LocalVariableTable even though 
	they are supported by the assembler.