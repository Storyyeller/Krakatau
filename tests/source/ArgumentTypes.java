public class ArgumentTypes{
	public static int main(boolean b){
		return b ? 1 : 0;
	}

	public static boolean main(int x){
		return x <= 42;
	}	
	
	public static void main(java.lang.String[] a)
	{
		int x = Integer.decode(a[0]);
		boolean y = Boolean.valueOf(a[1]);
			    
		System.out.println(main(x));
		System.out.println(main(y));
	}
}