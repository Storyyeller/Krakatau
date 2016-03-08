
.class public super [cls]
.super java/lang/Object

.const [cls] = Class SamSunTests

.method public static main : ([Ljava/lang/String;)V
    .code stack 10 locals 10
        aload_0
        invokestatic [cls] exceptionVerificationUsesOldLocalsState ([Ljava/lang/String;)V
        return
    .end code
.end method

.method public static exceptionVerificationUsesOldLocalsState : ([Ljava/lang/String;)V
    .code stack 10 locals 10
        .catch java/lang/Throwable from L0 to L1 using L0
        new java/lang/Integer
        astore_1
        aconst_null
L0:
        pop
        aload_1
        ifnonnull L3
        new java/lang/Long
        astore_1
L1:
        return
L3:
        aload_1
        dup
        iconst_0
        invokespecial Method java/lang/Integer <init> (I)V
        getstatic java/lang/System out Ljava/io/PrintStream;
        swap
        invokevirtual java/io/PrintStream println (Ljava/lang/Object;)V
        return
    .end code
.end method

.method public static num : ()I
    .code stack 10 locals 10
L0:     iconst_0
L1:     ireturn
L2:
    .end code
.end method

.method public static infiniteLoop : ([Ljava/lang/String;)V
    .code stack 10 locals 10
        invokestatic Method [cls] num ()I
L0:
        dup
        tableswitch 0
            L0
            default: L4
L4:
        return
    .end code
.end method

.end class