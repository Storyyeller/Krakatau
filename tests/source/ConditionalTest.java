public class ConditionalTest{

	public static void main(String[] args){
		short s;
		float f = -4.2f;

		test(true);
		test(false);
		test((s = -42));
		test(f = f);
	}

	static void test(boolean b) {
		long j;
		int i, k;
		char c;
		byte bb;
		boolean z;
		double f,g = 5_5_5;

		if (b) {
			j = 77 * (i = 7 ^ (c = '1'));
			bb = (byte)(f = (float)j);
			g = 0x1234p567;
			z = true;
			k = 1;
		} else {
			j = 077 * (i = 07 ^ (c = '\1'));
			bb = (byte)(f = (float)j);
			g = 0xfdecbap-567;
			z = false;
			k = 0;
		}

		System.out.println(j);
		System.out.println(i);
		System.out.println(k);
		System.out.println(c);
		System.out.println(bb);
		System.out.println(z);
		System.out.println(f);
		System.out.println(g);
	}

	static void test(long j) {
		System.out.println(~j);
	}

	static void test(double j) {
		System.out.println(j - 0x1p-51);
		System.out.println(j - 0x1p-52);
	}

}\u001a