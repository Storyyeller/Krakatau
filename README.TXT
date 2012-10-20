Krakatau Bytecode Tools
Copyright (C) 2012 Robert Grosse

=== Introduction ===

Krakatau currently contains two tools - a decompiler for Java classfiles and 
an assembler to create classfiles.

=== Requirements ===

Krakatau requires Python 2.7. The assembler additionally requires a free
Python library called PLY.

=== Decompilation ===

Usage: 
python Krakatau\decompile.py [-path PATH] [-out OUT] target

PATH : An optional list of directories, jars, or zipfiles to search for 
	classes in. Krakatau will attempt to automatically detect and add the 
	jar containing core language classes, but you can disable this with
	the -nauto option.

OUT : File or directory name where source files are written. Defaults to
	current directory

target : Class name or jar name to decompile. If a jar is specified, all
	classes in the jar will be decompiled.


The Krakatau decompiler takes a different approach to most Java decompilers.
It can be thought of more as a compiler whose input language is Java bytecode
and whose target language happens to be Java source code. Krakatau takes in 
arbitrary bytecode, and attempts to transform it to equivalent Java code. This
makes it robust to minor obfuscation, though it has the drawback of not
reconstructing the "original" source, leading to less readable output than a 
pattern matching decompiler would produce for unobfuscated Java classes. 

Note: decompilation produces a file called "cache.txt" in the current
	directory. This stores information about the standard library so it 
	doesn't have to be loaded every time. However, if you change the library,
	you should delete the cache.

=== Assembly ===

Usage: 
python Krakatau\assemble.py [-d DIR] [-out OUT] [-g] target

DIR : A directory to put all generated classes in. Defaults to the current
	directory.

OUT : The filename or path to output the generated class to. If not given,
	this will default to the name of the class, creating subdirectories if
	necessary. If both DIR and OUT are specified, they are concatenated. 

-g : If specified, SourceFile and LineNumberTable attributes giving the 
	offset of every instruction will be added. This is useful for debugging
	exceptions, as it will let the JVM print the origin of the exception
	in the traceback.

target : Name of file to assemble


The Krakatau assembler is intended as a replacement for Jasmin, and was 
originally written due to frustration with the limitations of Jasmin. Its 
syntax is mostly backwards compatible, but it also offers a host of new
features. 

There only two major changes necessary to convert from Jasmin. First, 'all'
needs to be replaced with '[0]' in exception handlers. Second, Krakatau
does not add the 'super' flag to classes automatically, so you must 
specify it manually if you wish your class to use new style superclass
calling semantics (you probably do).

The assembler uses PLY, which will generate a file called "parsetab.py" in
the current directory.