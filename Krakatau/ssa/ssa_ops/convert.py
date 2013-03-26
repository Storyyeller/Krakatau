from .base import BaseOp
# from ..constraints import IntConstraint

class Convert(BaseOp):
    def __init__(self, parent, arg, target_ssa):
        super(Convert, self).__init__(parent, [arg])
        self.target = target_ssa
        self.rval = parent.makeVariable(target_ssa, origin=self)