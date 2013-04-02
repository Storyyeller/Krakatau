.version 48 0
.class public BadInnerTest
.super java/lang/Object

.innerlength 0xFFFFFFFF
.attribute InnerClasses '\0\0'

.method public static main : ([Ljava/lang/String;)V
    .limit stack 10
    .limit locals 10

    getstatic java/lang/System out Ljava/io/PrintStream;
    ldc "Bad inners, bad inners, whatcha gonna do?"
    invokevirtual java/io/PrintStream println (Ljava/lang/Object;)V
    return
.end method