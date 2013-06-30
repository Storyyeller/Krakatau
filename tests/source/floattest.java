abstract public class floattest {
	static final float e = 2.7182818459f;
	static double d = 2.7182818459;

	static double x = -1.0/0.0;
	static double y = -5e-324;
	static float z = 700649232162408535461864791644958065640130970938257885878534141944895541342930300743319094181060791015626E-150f;

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

	    System.out.println(floattest.x);
	    System.out.println(floattest.y);
	    System.out.println(floattest.z);
	    System.out.println((double)floattest.z);
	}
}