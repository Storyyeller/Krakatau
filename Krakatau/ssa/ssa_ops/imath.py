from .base import BaseOp
from .. import ssa_types
from ..constraints import IntConstraint, ObjectConstraint
from . import bitwise_util

import itertools

def getNewRange(w, zmin, zmax):
    HN = 1 << w-1
    zmin = zmin + HN
    zmax = zmax + HN
    split = (zmin>>w != zmax>>w)

    if split:
        return IntConstraint.range(w, -HN, HN-1), None, None
    else:
        N = 1<<w
        return IntConstraint.range(w, (zmin % N)-HN, (zmax % N)-HN), None, None

class IAdd(BaseOp):
    def __init__(self, parent, args):
        super(IAdd, self).__init__(parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        return getNewRange(x.width, x.min+y.min, x.max+y.max)

class IMul(BaseOp):
    def __init__(self, parent, args):
        super(IMul, self).__init__(parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        vals = x.min*y.min, x.min*y.max, x.max*y.min, x.max*y.max
        return getNewRange(x.width, min(vals), max(vals))

class ISub(BaseOp):
    def __init__(self, parent, args):
        super(ISub, self).__init__(parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        return getNewRange(x.width, x.min-y.max, x.max-y.min)

#############################################################################################
class IAnd(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        return bitwise_util.propagateAnd(x,y), None, None

class IOr(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        return bitwise_util.propagateOr(x,y), None, None

class IXor(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        return bitwise_util.propagateXor(x,y), None, None

#############################################################################################
# Shifts currently only propogate ranges in the case where the shift is a known constant
# TODO - make this handle the general case
def getMaskedRange(x, bits):
    assert(bits < x.width)
    y = IntConstraint.const(x.width, (1<<bits) - 1)
    x = bitwise_util.propagateAnd(x,y)

    H = 1<<(bits-1)
    M = 1<<bits

    m1 = x.min if (x.max <= H-1) else -H
    m2 = x.max if (x.min >= -H) else H-1
    return m1, m2

class IShl(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        if y.min < y.max:
            return IntConstraint.bot(x.width), None, None
        shift = y.min % x.width
        if not shift:
            return x, None, None
        m1, m2 = getMaskedRange(x, x.width - shift)
        return IntConstraint.range(x.width, m1<<shift, m2<<shift), None, None

class IShr(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        if y.min < y.max:
            return IntConstraint.range(x.width, min(x.min, 0), max(x.max, 0)), None, None
        shift = y.min % x.width
        if not shift:
            return x, None, None
        m1, m2 = x.min, x.max
        return IntConstraint.range(x.width, m1>>shift, m2>>shift), None, None

class IUshr(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        M = 1<<x.width
        if y.min < y.max:
            intmax = (M//2)-1
            return IntConstraint.range(x.width, min(x.min, 0), max(x.max, intmax)), None, None
        shift = y.min % x.width
        if not shift:
            return x, None, None

        parts = [x.min, x.max]
        if x.min <= -1 <= x.max:
            parts.append(-1)        
        if x.min <= 0 <= x.max:
            parts.append(0)
        parts = [p % M for p in parts]
        m1, m2 = min(parts), max(parts)

        return IntConstraint.range(x.width, m1>>shift, m2>>shift), None, None

#############################################################################################
exec_tts = ('java/lang/ArithmeticException', 0),
class IDiv(BaseOp):
    def __init__(self, parent, args):
        super(IDiv, self).__init__(parent, args, makeException=True)
        self.rval = parent.makeVariable(args[0].type, origin=self)
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], exec_tts, nonnull=True)

    def propagateConstraints(self, x, y):
        excons = self.outExceptionCons if (y.min <= 0 <= y.max) else None
        if y.min == 0 == y.max:
            return None, excons, None

        #Calculate possible extremes for division, taking into account special case of intmin/-1
        intmin = -1<<(x.width - 1)
        xvals = set([x.min, x.max])
        yvals = set([y.min, y.max])

        for val in (intmin+1, 0):
            if x.min <= val <= x.max:
                xvals.add(val)
        for val in (-2,-1,1):
            if y.min <= val <= y.max:
                yvals.add(val)
        yvals.discard(0)

        vals = set()
        for xv, yv in itertools.product(xvals, yvals):
            if xv == intmin and yv == -1:
                vals.add(intmin)
            elif xv*yv < 0: #Unlike Python, Java rounds to 0 so opposite sign case must be handled specially
                vals.add(-(-xv//yv))                
            else:
                vals.add(xv//yv)

        rvalcons = IntConstraint.range(x.width, min(vals), max(vals))
        return rvalcons, excons, None

class IRem(BaseOp):
    def __init__(self, parent, args):
        super(IRem, self).__init__(parent, args, makeException=True)
        self.rval = parent.makeVariable(args[0].type, origin=self)
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], exec_tts, nonnull=True)

    def propagateConstraints(self, x, y):
        excons = self.outExceptionCons if (y.min <= 0 <= y.max) else None
        if y.min == 0 == y.max:
            return None, excons, None
        #only do an exact result if both values are constants, and otherwise
        #just approximate the range as -(y-1) to (y-1) (or 0 to y-1 if it's positive)
        if x.min == x.max and y.min == y.max:
            val = abs(x.min) % abs(y.min) 
            val = val if x.min >= 0 else -val
            return IntConstraint.range(x.width, val, val), None, None

        mag = max(abs(y.min), abs(y.max)) - 1
        rmin = -min(mag, abs(x.min)) if x.min < 0 else 0
        rmax = min(mag, abs(x.max)) if x.max > 0 else 0

        rvalcons = IntConstraint.range(x.width, rmin, rmax)
        return rvalcons, excons, None

###############################################################################
class ICmp(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(ssa_types.SSA_INT, origin=self)

    def propagateConstraints(self, x, y):
        rvalcons = IntConstraint.range(32, -1, 1)
        return rvalcons, None, None