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
