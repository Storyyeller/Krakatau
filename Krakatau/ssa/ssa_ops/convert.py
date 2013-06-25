from .base import BaseOp
from ..constraints import IntConstraint, FloatConstraint
from . import bitwise_util

class Convert(BaseOp):
    def __init__(self, parent, arg, source_ssa, target_ssa):
        super(Convert, self).__init__(parent, [arg])
        self.source = source_ssa
        self.target = target_ssa
        self.rval = parent.makeVariable(target_ssa, origin=self)