; InnerClasses attributes on fields and methods are ignored by the JVM, so their declared length must be
; used, unlike class level InnerClasses attributes (see BadInnerTest).
.version 48 0
.class public BadInnerMemberTest
.super java/lang/Object

.field static x I .fieldattributes
    .attribute InnerClasses b'\x00\x01'
    .attribute Deprecated b''
.end fieldattributes

.method public static main : ([Ljava/lang/String;)V
    .attribute InnerClasses b'\x00\x01'
    .code stack 10 locals 10
        getstatic Field java/lang/System out Ljava/io/PrintStream;
        ldc "Bad inners, bad inners, whatcha gonna do?"
        invokevirtual Method java/io/PrintStream println (Ljava/lang/Object;)V
        return
    .end code
.end method
.end class
