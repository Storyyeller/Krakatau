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
