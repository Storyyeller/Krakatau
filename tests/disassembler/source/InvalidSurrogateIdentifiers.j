

.class public InvalidSurrogateIdentifiers
.super java/lang/Object

.field static "x\uDCA9x" Ljava/lang/String; = "Hallo, "

.method public static "y\uD83Dy" : ()Ljava/lang/String;
    .code stack 10 locals 10
        ldc "Welt!"
        areturn
    .end code
.end method

.method public static main : ([Ljava/lang/String;)V
    .code stack 10 locals 10
        getstatic java/lang/System out Ljava/io/PrintStream;
        dup
        getstatic Field InvalidSurrogateIdentifiers "x\uDCA9x" Ljava/lang/String;
        invokevirtual Method java/io/PrintStream println (Ljava/lang/Object;)V
        invokestatic Method InvalidSurrogateIdentifiers "y\uD83Dy" ()Ljava/lang/String;
        invokevirtual Method java/io/PrintStream println (Ljava/lang/Object;)V
        return
    .end code
.end method
