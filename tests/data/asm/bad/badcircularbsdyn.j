.class public badcircularbsdyn
.super java/lang/Object

; Cycle through a bootstrap argument and the Dynamic constant that uses the bootstrap method
.const [d] = Dynamic [bs:b] a I
.bootstrap [bs:b] = Bootstrap invokeStatic Method badcircularbsdyn bsm ()V [d] :
.method public static f : ()V
    .code stack 1 locals 0
        ldc [d]
        return
    .end code
.end method
.end class
