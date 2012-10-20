public class Switch {
    strictfp public static void main(String args[]){
    	int x = -1;
    	
    	switch(args.length % -5){
			case 3:
				x += 3;
			case 1:
				x--;
				if (x == -2){
					break;
				}
			case 0:
				x += (x << x);
				break;				
			case 2:
			default:
				x = x ^ (int)0xABCD000L;
			case 4:
				x *= 4;
				break;
		}
    
    	System.out.println(x);
	}
}