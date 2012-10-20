from base import BaseJump
# from ssa_types import Variable, SSA_OBJECT

class Goto(BaseJump):
	def __init__(self, parent, target):
		super(Goto, self).__init__(parent, [])
		self.successors = [target]

	def replaceBlocks(self, blockDict):
		self.successors = [blockDict[key] for key in self.successors]

	def getNormalSuccessors(self):
		return self.successors