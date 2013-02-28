.class abstract super public DuplicateInit
.super java/lang/Object
.implements java/lang/CharSequence
.implements java/lang/Cloneable

.method static public synchronized main : ([Ljava/lang/String;)V
	.limit stack 19
	.limit locals 2

	new java/lang/Integer
	dup
LFOO:
	dup2
	astore_1
	;ifnull LFOO
	pop

	aload_0
	dup
	arraylength
	sipush 2
	if_icmpne LINT

	iconst_m1
	dup
	iushr

	aaload
	invokespecial java/lang/Integer <init> (Ljava/lang/String;)V
	goto_w LFINAL

LINT:
	arraylength
	iconst_5
	ishl

	invokespecial java/lang/Integer <init> (I)V

LFINAL:
	
	getstatic java/lang/System out Ljava/io/PrintStream;
	dup_x1
	aload_1
	invokevirtual java/io/PrintStream println (Ljava/lang/Object;)V
	invokevirtual java/io/PrintStream println (Ljava/lang/Object;)V

	return
.end method
