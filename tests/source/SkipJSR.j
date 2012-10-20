.class public SkipJSR
.super java/lang/Object

.method public static main : ([Ljava/lang/String;)V
    .limit locals 11
    .limit stack 11
    
    iconst_1
    istore_1
    jsr LSUB

    iconst_1
    newarray double
    dup
    astore_2
    iconst_0
    iload_1
    i2d
    dastore
    iinc 1 1

    jsr LSUB
    jsr LSUB
    aload_2
    iconst_0
    daload
    iload_1
    i2d
    ddiv
    dstore_0

	getstatic java/lang/System out Ljava/io/PrintStream;
	dload_0
	invokevirtual java/io/PrintStream println (D)V
	return		

LS_2:
    arraylength
    iadd
    istore_1
    ret 3

LSUB:
    astore_3
    aload_0
    iload_1
    dup_x1
    lookupswitch
        default : LS_2
.end method
