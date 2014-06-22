import java.io.Serializable;
import java.util.Arrays;

public class ArrayTest {
    public static void main(String args[]){
        Object[] x = new Cloneable[4][];
        Serializable[][] y = new Serializable[4][2];

        y[3] = args;
        x[1] = y;
        y[2][1] = x;

        System.out.println(Arrays.deepToString(x));
        System.out.println(Arrays.deepToString(y));
        try{
            y[3][0] = x;
        } catch (Throwable t) {System.out.println(t);}

        long[] z = new long[1];
        z[0] = (long)-(int)z[~+~0];

        x = y[0];
        x[0] = y.clone();
        x[1] = z.clone();

        foo(x.clone());
        foo(y.clone());
        foo((Object)y.clone());
        foo(z.clone());
    }

    static void foo(Object x) {System.out.println("Object");}
    static void foo(Object[] x) {System.out.println("Object[]");}
    static void foo(long[] x) {System.out.println("long[]");}
}