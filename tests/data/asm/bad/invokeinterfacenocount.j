.class public invokeinterfacenocount
.super java/lang/Object

.method public static f : ()V
    .code stack 1 locals 0
        aconst_null
        ; The argument count can only be omitted if the method descriptor is given inline
        invokeinterface InterfaceMethod java/util/function/LongUnaryOperator applyAsLong [desc]
        return
    .end code
.end method

.const [desc] = Utf8 (J)J
.end class
