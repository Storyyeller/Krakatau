// Originally created as a test for Krakatau (https://github.com/Storyyeller/Krakatau)
import java.net.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
import java.lang.reflect.*;
import java.lang.annotation.*;
import java.util.function.*;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Target({
    // ElementType.ANNOTATION_TYPE,
    // ElementType.CONSTRUCTOR,
    // ElementType.FIELD,
    // ElementType.LOCAL_VARIABLE,
    // ElementType.METHOD,
    // ElementType.PACKAGE,
    // ElementType.PARAMETER,
    // ElementType.TYPE,
    // ElementType.TYPE_PARAMETER,
    ElementType.TYPE_USE
})
@interface A {
    double value() default 0.0/0.0;
}

@Retention(RetentionPolicy.RUNTIME)
@Target({
    ElementType.TYPE_USE
})
@interface B {}

record IPair (int a, @A(13) @B String b, IPair p) {
    static final int X = 7;
}


public class RecordTest {
    public static void main(String... args) throws Throwable {
        System.out.println(new IPair(3, "x", null));
    }
}
