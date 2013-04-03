from .base import BaseOp
from ..constraints import IntConstraint, FloatConstraint

from .imath import propagateBitwise

class Convert(BaseOp):
    def __init__(self, parent, arg, source_ssa, target_ssa):
        super(Convert, self).__init__(parent, [arg])
        self.source = source_ssa
        self.target = target_ssa
        self.rval = parent.makeVariable(target_ssa, origin=self)

    def propagateConstraints(self, x):
        #Cases: i2l, i2f, i2d, l2i, l2f, l2d, f2i, f2l, f2d, d2i, d2l, d2f

        srct, srcw = self.source
        destt, destw = self.target

        if srct == 'int':
            if destt == 'int':
                if srcw > destw:
                    #copied from imath.py
                    mask = IntConstraint(srcw, 0, (1<<destw)-1)
                    x = propagateBitwise(x, mask, operator.__and__, False, True)
                return IntConstraint(destw, x.min, x.max),
            # elif destt == 'float':
            #     ints = [x.min, x.max]
            #     for v in (-1,0,1):
            #         if x.min <= v <= x.max:
            #             ints.append(v)

        if destt == 'int':
            return IntConstraint.bot(destw),
        return FloatConstraint.bot(destw),