import java.util.*;

public class ArgumentTypes{

	public static int main(boolean b){
		return b ? 1 : 0;
	}

	public static boolean main(int x){
		return x <= 42;
	}

	public static char main(char x){
		return x ^= '*';
	}

	public static String main(Object x){
		if (x instanceof boolean[]){
			return Arrays.toString((boolean[])x);
		}
		else if (x instanceof String[]) {
		}
		else if (x instanceof int[]) {
			return "" + ((int[])x)[0];
		}
		else {
			return java.util.Arrays.toString((byte[])x);
		}
		return null;
	}

	public static void main(java.lang.String[] a)
	{
		int x = Integer.decode(a[0]);
		boolean y = Boolean.valueOf(a[1]);

		System.out.println(main(x));
		System.out.println(main(y));

		byte[] z = {1,2,3,45,6};
		boolean[] w = {false, true, false};
		Object[] v = a;

		System.out.println(main(v));
		System.out.println(main(w));
		System.out.println(main(z));

		char c = 'C';
		System.out.println(c);
		System.out.println((int)c);
	}

	public static byte[] main(byte[][] x){
		if (x.length > 0) {
			return x[0];
		}
		return null;
	}
}