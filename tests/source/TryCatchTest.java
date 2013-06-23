import java.nio.channels.*;
import java.net.*;
import java.io.*;

public class TryCatchTest{

	static volatile boolean i2 = true;
	

	public static void main(String[] args)
	{
		try{
			int x = args.length;

			try{
				if (args[0].equals("bad") && i2){
					throw new MalformedURLException(args[1] + args[1]);
				}

				if (args[0].equals("good") || ++x == 3){
					throw new FileLockInterruptionException();
				}
			} catch (final MalformedURLException e) {
				throw e;
			} catch (Exception e) {
				Throwable t = new MalformedURLException(e.getClass().getName());
				Throwable t2 = e.initCause(t);
				throw (MalformedURLException)t;
			}

			System.out.println(x);
		} catch (IOException e){
			System.out.println(e);
		}
	}
}