// Originally created as a test for Krakatau (https://github.com/Storyyeller/Krakatau)
public final strictfp class OddsAndEnds {

    static private void test(float f, Object o){
        //synchronized(o)
        {
            long x = (long)f;
            if (o instanceof Long) {
                long y = (Long)o;

                if (y <= x){
                    System.out.println((-y) % (-f));
                }
            }
        }

        int x = print("Hello, World!");
        int y = (o == null) ? (x ^ -1) : 42;
        print("" + f + y + (f + y));
    }

    public static void main(String args[]){

        if (args != null) {
            Object x = args;
            try {
                java.util.List<String> y;
                System.out.println(y = (java.util.ArrayList)x);
                args = y.toArray(new String[0]);
            }
            catch (final ClassCastException e) {
                args = true?args:null;
            }
        }

        test(42.24f, args);
        test(4.224f, Long.valueOf(args[0]));

        test(-0.0f, main(999999999L));

        testCastToInterface("This is a string");
        testCastToInterface2("This is also a string");
    }

    public static int main(Object x){
        boolean a = false;
        boolean b = true;
        boolean c = x == null == a;
        boolean d = b?a?b:a?b:a:b?a:b;
        boolean e = (a?b:c)?d:c?b:a;

        return ((Number) x).shortValue();
    }


    static int print(String s){
        System.out.println(s);
        return s.hashCode();
    }

    public static void testCastToInterface(String s){
        CharSequence cs = (CharSequence)(Object)s;
        System.out.println(s);
        System.out.println(cs);
    }

    public static void testCastToInterface2(String... s){
        CharSequence[] cs = (CharSequence[])(Object[])s;
        System.out.println(java.util.Arrays.deepToString(s));
        System.out.println(java.util.Arrays.deepToString(cs));
    }
}
