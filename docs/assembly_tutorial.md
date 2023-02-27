## Krakatau assembly tutorial

This is a high level introduction to Krakatau assembler syntax. [For a complete, low level specification of the syntax, click here](assembly_specification.md).


_Note: This tutorial assumes that you already understand the classfile format and how Java bytecode works. To learn about bytecode, consult the JVM specification._


## A minimal classfile

Technically speaking, the simplest Krakatau assembly file is just an empty file, since one `.j` file can contain any number of class definitions, including zero. But that's boring, so let's try a minimal class definition:

```
; This is a comment. Comments start with ; and go until end of the line
.class public Foo 
.super java/lang/Object ; Java bytecode requires us to explicitly inherit from java.lang.Object
.end class
```

This defines a class with no fields or methods. We can now assemble this `.j` file and try to run the resulting classfile:

```
> krak2 asm -o Foo.class examples/minimal.j 
got 1 classes
Wrote 55 bytes to Foo.class
> java Foo
Error: Main method not found in class Foo, please define the main method as:
   public static void main(String[] args)
or a JavaFX application class must extend javafx.application.Application

```

Unfortunately, since it has no main method, Java can't run it. Let's make a class with a `main` method that prints "Hello World!":

```
.class public Foo 
.super java/lang/Object 

; ([Ljava/lang/String;)V  means "takes a single String[] argument and returns void"
.method public static main : ([Ljava/lang/String;)V
    ; We have to put an upper bound on the number of locals and the operand stack
    ; Machine generated code will usually calculate the exact limits, but that's a pain to do
    ; when writing bytecode by hand, especially as we'll be making changes to the code.
    ; Therefore, we'll just set a value that's way more than we're using, 13 in this case
    .code stack 13 locals 13
        ; Equivalent to "System.out" in Java code
        getstatic Field java/lang/System out Ljava/io/PrintStream;
        ; put our argument on the operand stack
        ldc "Hello World!"
        ; now invoke println()
        invokevirtual Method java/io/PrintStream println (Ljava/lang/Object;)V
        return
    .end code
.end method
.end class

```

Now we can assemble and run our class successfully!

```
> krak2 asm -o Foo.class examples/hello.j 
got 1 classes
Wrote 278 bytes to Foo.class
> java Foo
Hello World!
```

Now let's try greeting the user by name, assuming that they supply their name as a command line parameter. Java include the command line parameters in the `String[]` array passed to `main()`, so we just need to access the first element:

```
.class public Foo 
.super java/lang/Object 

.method public static main : ([Ljava/lang/String;)V
    .code stack 13 locals 13
        getstatic Field java/lang/System out Ljava/io/PrintStream;
        ldc "Hello, "

        ; Access args[0]
        aload_0
        iconst_0
        aaload

        ; Concat the strings
        invokevirtual Method java/lang/String concat (Ljava/lang/String;)Ljava/lang/String;

        ; Now print like normal
        invokevirtual Method java/io/PrintStream println (Ljava/lang/Object;)V
        return
    .end code
.end method
.end class
```

Running it shows that our program correctly greets different people by name:

```
> krak2 asm -o Foo.class examples/greet1.j 
got 1 classes
Wrote 361 bytes to Foo.class
> java Foo Alice
Hello, Alice
> java Foo Bob
Hello, Bob

```

## Control flow

Suppose we want to print a different message depending on the user's name. For example, we would like our program to print "Fuck you" if the name contains "Bob" and otherwise say "Hello" like normal. 

In order to have control flow, we need to use *labels*. A label can be any word starting with an uppercase `L`. In this case, we call `String.contains()` to see if the name contains "Bob". `contains()` returns `1` if the string does contain "Bob" and `0` otherwise (booleans are just ordinary ints at the bytecode level). 

We then use the `ifeq` instruction, which compares this value to `0`. If it is `0`, we jump to our `LELSE` label, otherwise, we fallthrough to the main branch, push "Fuck you, " onto the stack, and then `goto` `LEND`. The `LELSE` label then pushes "Hello, " onto the stack instead.


```
.class public Foo 
.super java/lang/Object 

.method public static main : ([Ljava/lang/String;)V
    .code stack 13 locals 13
        getstatic Field java/lang/System out Ljava/io/PrintStream;

        ; Access the user's name
        aload_0
        iconst_0
        aaload

        ; Store name in the first variable slot for later
        astore_0

        ; See if name contains "Bob"
        aload_0
        ldc "Bob"
        invokevirtual Method java/lang/String contains (Ljava/lang/CharSequence;)Z

        ifeq LELSE
        ldc "Fuck you, "
        goto LEND
LELSE:
        ldc "Hello, "
LEND:
        ; Load name again so we can concat it to the prefix above
        aload_0
        invokevirtual Method java/lang/String concat (Ljava/lang/String;)Ljava/lang/String;
        invokevirtual Method java/io/PrintStream println (Ljava/lang/Object;)V
        return
    .end code
.end method
.end class

```

As expected, our new class works like a charm.


```
> krak2 asm -o Foo.class examples/greet2.j 
got 1 classes
Wrote 453 bytes to Foo.class
> java Foo Alice
Hello, Alice
> java Foo Bob
Fuck you, Bob
> java Foo "Alice Margatroid"
Hello, Alice Margatroid
> java Foo "Totally Not Bob"
Fuck you, Totally Not Bob
```

## Conclusion

That's the end of the tutorial for now. Hopefully, this at least gives you a very basic introduction to bytecode. 

_Tip: If you aren't sure how to do something, try compiling a Java class with code to do what you want, and then disassembling it with the Krakatau disassembler to see what the bytecode looks like._
