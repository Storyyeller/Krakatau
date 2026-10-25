; Regression test for 207a43f: Krakatau v1 output can combine .stack directives with
; .noimplicitstackmap, in which case the frames are parsed and then discarded.
.class public noimplicitstackmap
.super java/lang/Object

.method public static main : ([Ljava/lang/String;)V
    .code stack 1 locals 1
        aload_0
        ifnull L5
L4:     nop
        .stack stack_1 Object java/lang/String
L5:     return
.noimplicitstackmap
    .end code
.end method
.end class
