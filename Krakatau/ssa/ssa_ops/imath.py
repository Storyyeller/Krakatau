from base import BaseOp
from .. import ssa_types
from ..constraints import IntConstraint, ObjectConstraint
import itertools, operator

def getNewRange(w, zmin, zmax):
    HN = 1 << w-1
    zmin = zmin + HN
    zmax = zmax + HN
    split = (zmin>>w != zmax>>w)

    if split:
        return IntConstraint.range(w, -HN, HN-1), 
    else:
        N = 1<<w
        return IntConstraint.range(w, (zmin % N)-HN, (zmax % N)-HN),    

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
def split_pow2ranges(x,y):
    '''split given range into power of two ranges of form [x, x+2^k)'''
    out = []
    while x<=y:
        #The largest power of two range of the form x,k 
        #has k min of number of zeros at end of x
        #and the largest power of two that fits in y-x
        bx = bin(x)
        numzeroes = float('inf') if x==0 else (len(bx)-bx.rindex('1')-1) 
        k = min(numzeroes, (y-x+1).bit_length()-1)
        out.append((x,k))
        x += 1<<k
    return out

def propagateBitwise(arg1, arg2, op, usemin, usemax):
    ranges1 = split_pow2ranges(arg1.min, arg1.max)
    ranges2 = split_pow2ranges(arg2.min, arg2.max)

    vals = []
    for (s1,k1),(s2,k2) in itertools.product(ranges1, ranges2):
        # there are three parts. The high bits fixed in both arguments,
        # the middle bits fixed in one but not the other, and the 
        # lowest bits which can be chosen freely for both arguments
        # high = op(h1,h2) and low goes from 0 to 1... but the range of
        # the middle depends on the particular operation
        # 0-x, x-1 and 0-1 for and, or, and xor respectively
        if k1 > k2:
            (s1,k1),(s2,k2) = (s2,k2),(s1,k1)

        mask1 = (1<<k1) - 1
        mask2 = (1<<k2) - 1 - mask1

        high = op(s1, s2) & ~(mask1 | mask2)
        midmin = (s1 & mask2) if usemin else 0
        midmax = (s1 & mask2) if usemax else mask2

        vals.append(high | midmin)
        vals.append(high | midmax | mask1)
    return IntConstraint.range(arg1.width, min(vals), max(vals)),

class IAnd(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        return propagateBitwise(x, y, operator.__and__, False, True)

class IOr(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        return propagateBitwise(x, y, operator.__or__, True, False)

class IXor(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

    def propagateConstraints(self, x, y):
        return propagateBitwise(x, y, operator.__xor__, False, False)

#############################################################################################
class IShl(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

class IShr(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)

class IUshr(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(args[0].type, origin=self)
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
            return None, excons 

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
        return rvalcons, excons

class IRem(BaseOp):
    def __init__(self, parent, args):
        super(IRem, self).__init__(parent, args, makeException=True)
        self.rval = parent.makeVariable(args[0].type, origin=self)
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], exec_tts, nonnull=True)

    def propagateConstraints(self, x, y):
        excons = self.outExceptionCons if (y.min <= 0 <= y.max) else None
        if y.min == 0 == y.max:
            return None, excons 
        #only do an exact result if both values are constants, and otherwise
        #just approximate the range as -(y-1) to (y-1) (or 0 to y-1 if it's positive)
        if x.min == x.max and y.min == y.max:
            val = abs(x.min) % abs(y.min) 
            val = val if x.min >= 0 else -val
            return IntConstraint.range(x.width, val, val), None

        mag = max(abs(y.min), abs(y.max)) - 1
        rmin = -min(mag, abs(x.min)) if x.min < 0 else 0
        rmax = min(mag, abs(x.max)) if x.max > 0 else 0

        rvalcons = IntConstraint.range(x.width, rmin, rmax)
        return rvalcons, excons

###############################################################################
class ICmp(BaseOp):
    def __init__(self, parent, args):
        BaseOp.__init__(self, parent, args)
        self.rval = parent.makeVariable(ssa_types.SSA_INT, origin=self)

    def propagateConstraints(self, x, y):
        rvalcons = IntConstraint.range(32, -1, 1)
        return rvalcons,