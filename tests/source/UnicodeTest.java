public class UnicodeTest {
	final static String \ufe4f\u2167 = "\uFEFF\uD800\uD8D8\uDFFD";
	transient static short x\u03A7x = 5;

	protected static String __\u0130\u00dFI(UnicodeTest x) {return \ufe4f\u2167;}

	public static void main(String[] a)
	{
		System.out.println(__\u0130\u00dFI(null));
	    System.out.println("\0\17u\\\u005c"\ff'\rr\u0027\nn \u0123\u1234O\uFFFFF");
	}
}