from .base import BaseOp
from .. import objtypes, excepttypes, ssa_types
from ..constraints import ObjectConstraint, IntConstraint
from ..constraints import returnOrThrow, maybeThrow, throw, return_

class CheckCast(BaseOp):
    def __init__(self, parent, target, args):
        super(CheckCast, self).__init__(parent, args, makeException=True)
        self.env = parent.env
        self.target_tt = target
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], (excepttypes.ClassCast,), nonnull=True)

    def propagateConstraints(self, x):
        for top in x.types.supers | x.types.exact:
            if not objtypes.isSubtype(self.env, top, self.target_tt):
                assert(not x.isConstNull())
                return maybeThrow(self.outExceptionCons)
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
