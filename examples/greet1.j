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
