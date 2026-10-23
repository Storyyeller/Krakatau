// Originally created as a test for Krakatau (https://github.com/Storyyeller/Krakatau)
public class For {
    static boolean b;

    public static void main(String[] a)
    {
        int i = 0;
        while (i < 10) {
            System.out.println(i);
            int j = i + 1;
            if (b) {j++;}
            i = j + 1;
        };
    }
}