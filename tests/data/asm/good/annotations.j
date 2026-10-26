.class public annotations
.super java/lang/Object
.runtime visible annotations
    .annotation LFoo;
        a = int 1
        b = array
            int 2
            array
            .end array
            array
                annotation LBar;
                    x = string "hi"
                    y = array
                        enum LE; A
                        class LC;
                    .end array
                .end annotation
                double 1.5
            .end array
            annotation LEmpty;
            .end annotation
        .end array
        c = annotation LBaz;
            z = array
                array
                    array
                        long 7L
                    .end array
                .end array
            .end array
        .end annotation
        d = boolean 1
    .end annotation
    .annotation LEmpty;
    .end annotation
.end runtime
.runtime invisible typeannotations
    .typeannotation 0x13 empty
        .typepath
        .end typepath
        LT;
        v = array
            annotation LN;
                q = char 65
            .end annotation
        .end array
    .end typeannotation
.end runtime
.method public abstract m : ()V
    .annotationdefault array
        annotation LD;
            k = array
                short 3
            .end array
        .end annotation
        byte 1
        float 1.0f
    .end array
    .runtime visible paramannotations
        .paramannotation
            .annotation LP;
                p = array
                .end array
            .end annotation
        .end paramannotation
    .end runtime
.end method
.method public abstract m2 : ()V
    .annotationdefault int 5
.end method
.end class
