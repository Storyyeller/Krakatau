public class virtual implements Comparable {
    protected int x;
    
    public virtual(int x){
		this.x = x;
	}
	
	public int compareTo(Object o){
		return x;
	}
    
    public static void main(String[] args){
		
		Comparable x = new virtual(42);
		Comparable y = args[0];
		
		System.out.println(x.compareTo(y));
		System.out.println(y.compareTo(x));		
	}   
}