###preprocess###
.class public annotationdepth
.super java/lang/Object

; Annotations and arrays nested 20000 levels deep, alternating between the two.
; This would overflow the stack if annotations were parsed or printed recursively.
.runtime visible annotations
    .annotation LFoo;
###range(10000):v = array
annotation LBar;
###v = int 1
###range(10000):.end annotation
.end array
###
    .end annotation
.end runtime
.end class
