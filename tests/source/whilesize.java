public class whilesize {
	static int x;

	public static void main(String[] a)
	{           
		boolean y = a.length > 0;
		boolean z = a.length < 2;
		x = 42;
		
	    while(1==1){
	    	x++;
	    	
			if (x <= 127){
				if (y ^ z){
					//x = y ? 4 : z ? x%7 : 127;
					x = a.length ^ x;
					break;	
				}		
				else{
					y = y & true;
					z = z | false;
					continue;
				}
			} 		
			x = ~(~x) >>> 3L;
			break;
		}
		
		System.out.println(x);
		System.out.println(y);
		System.out.println(z);
	}
}