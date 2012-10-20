.class public DualIf
.super java/lang/Object

.method public static main : ([Ljava/lang/String;)V
    .limit locals 11
    .limit stack 11
    .catch java/lang/Exception from L1 to L2 using L2
    .catch java/lang/Throwable from L1 to L2 using L1
    
    aconst_null
    sipush 0
    ifne L1
L1:
	return	
L2:	
	return
.end method
