// Originally created as a test for Krakatau (https://github.com/Storyyeller/Krakatau)
import java.nio.channels.*;
import java.net.*;
import java.io.*;

public class TryCatchTest {
    static volatile boolean i2 = true;

    public static void main(String[] args)
    {
        try{
            int x = args.length;

            try{
                if (args[0].equals("bad") && i2){
                    throw new MalformedURLException(args[1] + args[1]);
                }

                if (args[0].equals("good") || ++x == 3){
                    throw new FileLockInterruptionException();
                }
            } catch (final MalformedURLException e) {
                throw e;
            } catch (Exception e) {
                Throwable t = new MalformedURLException(e.getClass().getName());
                Throwable t2 = e.initCause(t);
                throw (MalformedURLException)t;
            }

            System.out.println(x);
        } catch (IOException e){
            System.out.println(e);
        }

        test2(54); test2(0);
        test3(args);
        System.out.println(i);
    }

    static String x; static int i;
    public static void test2(int i) {
        String[] x = null;
        try {
            TryCatchTest.i = 54/i;
            TryCatchTest.x = x[0];
            System.out.println(x);}
        catch (RuntimeException e) {}
        catch (Throwable e) {x = new String[0];}

        try {
            TryCatchTest.i = 54/i;
            TryCatchTest.x = x[0] = "";
            System.out.println(x);}
        catch (RuntimeException e) {}
        catch (Throwable e) {x = new String[-1];}
    }

    Object z;
    public static void test3(Object x) {
        long j = 0;
        try {
            (new TryCatchTest()).z = x;
            i = 123456;
            i = (int)(123456L/j);
        }
        catch (Throwable e) {}
    }

    // This function was added because it breaks Procyon 0.5.25
    public static int bar()
    {
        while(true) {
            ltry:
            try {
                main(null);
                return 0;
            } catch (Throwable t) {
                t.printStackTrace();
                continue;
            } finally {
                int x = 0;
                break ltry;
            }
        }
    }
}