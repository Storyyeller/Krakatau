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
	}

    public static void main(String args[]){
        test(42.24f, args);	
		test(4.224f, Long.valueOf(args[0]));		        
    }
}