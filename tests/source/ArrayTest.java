import java.io.Serializable;
import java.util.Arrays;

public class ArrayTest {
    public static void main(String args[]){
        Object[] x = new Cloneable[4][];
    	Serializable[][] y = new Serializable[4][2];

    	y[3] = args;
    	x[1] = y;
		y[2][1] = x;

		System.out.println(Arrays.deepToString(x));
		System.out.println(Arrays.deepToString(y));
		y[3][0] = x;

        long[] z = new long[1];
        z[0] = (long)-(int)z[~+~0];		        
    }
}