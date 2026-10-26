.class public symreftoraw
.super java/lang/Object

; Symbolic refs that are aliases for raw refs
.const [20] = Utf8 symreftoraw
.const [a] = [20]
.const [b] = [a]
.const [c] = Class [b]
.bootstrap [bs:3] = Bootstrap invokeStatic Method symreftoraw bsm (Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/Class;)I Int 1 :
.bootstrap [bs:k] = [bs:3]
.method public static f : ()V
    .code stack 2 locals 0
        ldc [c]
        ldc String [b]
        ldc Dynamic [bs:k] a I
        ldc Dynamic [bs:3] b I
        return
    .end code
.end method
.end class
