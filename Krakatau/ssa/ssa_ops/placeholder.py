from base import BaseOp
# from ssa_types import Variable, SSA_OBJECT

class Placeholder(BaseOp):
	def __init__(self, parent, *args, **kwargs):
		super(Placeholder, self).__init__(parent, [])

		self.returned = []
		self.rval = None