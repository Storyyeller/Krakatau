.class public badcircularbs
.super java/lang/Object

.bootstrap [bs:x] = [bs:y]
.bootstrap [bs:y] = [bs:x]
.method public static f : ()V
    .code stack 1 locals 0
        ldc Dynamic [bs:x] a I
        return
    .end code
.end method
.end class
