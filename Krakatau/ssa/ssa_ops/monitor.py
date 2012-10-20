from base import BaseOp
from .. import objtypes, excepttypes
from ..constraints import ObjectConstraint, DUMMY

class Monitor(BaseOp):
    def __init__(self, parent, args, monad, isExit):
        BaseOp.__init__(self, parent, [monad]+args, makeException=True)
        self.exit = isExit
        self.env = parent.env

    def propagateConstraints(self, m, x):
        etypes = ()
        if x.null:
            etypes += (excepttypes.NullPtr,)
        if self.exit and not x.isConstNull():
            etypes += (excepttypes.MonState,)
        eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
        mout = m if x.isConstNull() else DUMMY
        return eout, mout
