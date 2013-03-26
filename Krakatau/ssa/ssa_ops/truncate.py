from .base import BaseOp
from ..constraints import IntConstraint

class Truncate(BaseOp):
    def __init__(self, parent, arg, signed, width):
        super(Truncate, self).__init__(parent, [arg])

        self.signed, self.width = signed, width
        self.rval = parent.makeVariable(arg.type, origin=self)

    def propagateConstraints(self, x):
        #get range of target type
        w = self.width
        tmin,tmax = (-1<<w-1,(1<<w-1)-1) if self.signed else (0,1<<w)

        xmin = max(tmin, x.min)
        xmax = min(tmax, x.max)
        return IntConstraint.range(x.width, xmin, xmax),