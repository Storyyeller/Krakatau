public class BoolizeTest{
	
	static void main(boolean x, int y) {}
	static void main(boolean[] x, byte[] y) {}

	public static void main(String[] args){
		main(false, 0);
		main(null, null);
	}
}