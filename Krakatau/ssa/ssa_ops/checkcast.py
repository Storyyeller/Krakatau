from .base import BaseOp
from .. import objtypes, excepttypes, ssa_types
from ..constraints import ObjectConstraint, IntConstraint
from ..constraints import join, maybeThrow, throw, return_

class CheckCast(BaseOp):
    def __init__(self, parent, target, args):
        super(CheckCast, self).__init__(parent, args, makeException=True)
        self.env = parent.env
        self.target_tt = target

        if objtypes.isBaseTClass(target):
            self.outCasted = ObjectConstraint.fromTops(parent.env, [target], [])
        else:
            # Primative array types need to be in exact, not supers
            self.outCasted = ObjectConstraint.fromTops(parent.env, [], [target])
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], (excepttypes.ClassCast,), nonnull=True)

    def propagateConstraints(self, x):
        intersect = join(x, self.outCasted)
        if intersect is None:
            return throw(self.outExceptionCons)
        elif intersect != x:
            assert(not x.isConstNull())
            return maybeThrow(self.outExceptionCons)
        else:
            return return_(None)

class InstanceOf(BaseOp):
    def __init__(self, parent, target, args):
        super(InstanceOf, self).__init__(parent, args)
        self.env = parent.env
        self.target_tt = target
        self.rval = parent.makeVariable(ssa_types.SSA_INT, origin=self)

    def propagateConstraints(self, x):
        rvalcons = IntConstraint.range(32, 0, 1)
        return return_(rvalcons)
