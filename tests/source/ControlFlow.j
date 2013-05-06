.class public ControlFlow
.super java/lang/Object

.method public static main : ([Ljava/lang/String;)V
    .limit locals 11
    .limit stack 11

LSTART:
    aload_0
    dup
    arraylength
    istore_0

    iconst_0
    aaload
    invokestatic java/lang/Integer decode (Ljava/lang/String;)Ljava/lang/Integer;
    invokevirtual java/lang/Integer intValue ()I
    dup

LDEC:
	iload_0
	iconst_m1
	i2c
	if_icmple LDEC2
		iinc 0 -113
		goto LDEC
LDEC2:

    iinc 0 1
    ifne LIF
LIF:
	iload_0
	dup2
	ixor
	istore_0

	iconst_m1
	if_icmpeq LIF

	tableswitch -2
		LS1
		LS2
		LS1
		default: LS2

LS1:
	iinc 0 4
LS2:
	wide iinc 0 -1289

	iload_0
	i2l
	invokestatic java/lang/Long valueOf (J)Ljava/lang/Long;

LPRINT:
    getstatic java/lang/System out Ljava/io/PrintStream;
    swap
    invokevirtual java/io/PrintStream println (Ljava/lang/Object;)V
    return

LEX:
	checkcast java/lang/ClassCastException
LEX2:
	goto LPRINT

.catch java/lang/IndexOutOfBoundsException from LSTART to LS1 using LEX
.catch java/lang/RuntimeException from LSTART to LS2 using LEX2
.catch java/lang/NumberFormatException from LSTART to LS2 using LEX
.catch java/lang/Throwable from LSTART to LS1 using LEX2

.catch [0] from LSTART to LS2 using LEX
.catch [0] from LEX to LEX2 using LEX
.catch [0] from LEX to LEX2 using LEX2

.end method
