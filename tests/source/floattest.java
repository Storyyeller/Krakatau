abstract public class floattest {
	static final float e = 2.7182818459f;
	static double d = 2.7182818459;

	strictfp public static void main(String[] args)
	{		
		double t = (double)(1L << 53);
		double x = t*t;
		double y = (double)(-1L >>> 11);
		double z = x % y;
	    System.out.println(z);
	    System.out.println(z == 1.0);
	    System.out.println(z*e);
	    System.out.println(z*d);
	}
}