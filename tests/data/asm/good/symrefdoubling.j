###preprocess###
.class public symrefdoubling
.super java/lang/Object

; Each level references the previous one twice, so this takes exponential time without memoization
.const [mh] = MethodHandle invokeStatic Method symrefdoubling bsm (Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/Class;[Ljava/lang/Object;)Ljava/lang/Object;
.const [d0] = Int 0

###range(40,):.bootstrap [bs:b{}] = Bootstrap [mh] [d{}] [d{}] :
.const [d{ip1}] = Dynamic [bs:b{}] x Ljava/lang/Object;
###
.method public static f : ()V
    .code stack 1 locals 0
        ldc [d40]
        pop
        return
    .end code
.end method
.end class
