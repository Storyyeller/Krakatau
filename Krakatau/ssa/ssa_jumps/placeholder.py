from base import BaseJump
# from ssa_types import Variable, SSA_OBJECT

class Placeholder(BaseJump):
	def __init__(self, parent, *args, **kwargs):
		super(Placeholder, self).__init__(parent)
