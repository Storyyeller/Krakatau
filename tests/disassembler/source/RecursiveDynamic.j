.version 55 0
.class public RecursiveDynamic
.super java/lang/Object

.bootstrap [bs:0] = Bootstrap invokeStatic Method RecursiveDynamic main ([Ljava/lang/String;)V [1] :
.const [1] = Dynamic [bs:0] RecursiveDynamic I


.method public static main : ([Ljava/lang/String;)V
    .code stack 10 locals 10
        getstatic java/lang/System out Ljava/io/PrintStream;
        ldc "Hello World!"
        invokevirtual java/io/PrintStream println (Ljava/lang/Object;)V
        return
    .end code
.end method
