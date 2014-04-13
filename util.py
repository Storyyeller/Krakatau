import time

class Timer(object):
	def __init__(self, msg='time'):
		self.msg = msg
	def __enter__(self):
		self.t0 = time.time()
	def __exit__(self, exception_type, exception_value, traceback):
		if exception_type is None:
			print self.msg, time.time() - self.t0