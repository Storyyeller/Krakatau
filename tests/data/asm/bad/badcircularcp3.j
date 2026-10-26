.class public badcircularcp3
.super java/lang/Object

; The cycle should be reported at the last link of the alias chain
.const [x] = [y]
.const [y] = [z]
.const [z] = MethodType [w]
.const [w] = [x]
.const [1] = String [x]
.end class
