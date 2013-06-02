.version 49 49
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

    dup
    iconst_0
    aaload
    invokestatic ControlFlow dsm (Ljava/lang/String;)V

    iconst_1
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

.method static dsm : (Ljava/lang/String;)V
    .limit locals 11
    .limit stack 11

    aload_0
    invokevirtual java/lang/String toCharArray ()[C

    bipush 127
    newarray char
    astore_0
    iconst_m1
    istore_2
    bipush 32

LS0:
	bipush 64
	jsr LXWRITE
	lookupswitch
		0 : LS0
		1 : LS1
		2 : LS2
		default : LS3

LS1:
	bipush 32
	jsr LXWRITE
	lookupswitch
		0 : LS1
		3 : LS2
		4 : LS0
		default : LS3

LS2:
	bipush 16
	jsr LXWRITE
	lookupswitch
		0 : LS3
		1 : LS0
		2 : LS1
		4 : LS1
		default : LS0

LS3:
	bipush 8
	jsr LXWRITE
	lookupswitch
		0 : LS0
		1 : LS1
		2 : LS3
		default : LS2

LXWRITE:
	astore_1
	ixor
	jsr LWRITE
	iconst_5
	irem
	ret 1

LWRITE:
	iinc 2 1
	swap
	aload_0
	swap
	iload_2
	swap
	castore
	astore_3
	dup
	iload_2
	caload
	dup
	ret 3

.catch java/lang/IndexOutOfBoundsException from LWRITE to LEND using LEND

LEND:
    getstatic java/lang/System out Ljava/io/PrintStream;
    
    new java/lang/String
    dup
    aload_0
    iconst_0
    iload_2
    invokespecial java/lang/String <init> ([CII)V

    invokevirtual java/io/PrintStream println (Ljava/lang/Object;)V

	return
.end method
