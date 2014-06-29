from .base import BaseOp
from ..ssa_types import SSA_OBJECT

from .. import excepttypes
from ..constraints import ObjectConstraint, IntConstraint, DUMMY

class New(BaseOp):
    def __init__(self, parent, name, monad, inode_key):
        super(New, self).__init__(parent, [monad], makeException=True, makeMonad=True)
        self.env = parent.env
        self.tt = name,0
        self.rval = parent.makeVariable(SSA_OBJECT, origin=self)
        self.rval.uninit_orig_num = inode_key

    def propagateConstraints(self, m):
        eout = ObjectConstraint.fromTops(self.env, [], (excepttypes.OOM,), nonnull=True)
        rout = ObjectConstraint.fromTops(self.env, [], [self.tt], nonnull=True)
        return rout, eout, DUMMY

class NewArray(BaseOp):
    def __init__(self, parent, param, baset, monad):
        super(NewArray, self).__init__(parent, [monad, param], makeException=True, makeMonad=True)
        self.baset = baset
        self.rval = parent.makeVariable(SSA_OBJECT, origin=self)

        base, dim = baset
        self.tt = base, dim+1
        self.env = parent.env

    def propagateConstraints(self, m, i):
        if i.max < 0:
            eout = ObjectConstraint.fromTops(self.env, [], (excepttypes.NegArrSize,), nonnull=True)
            return None, eout, m

        etypes = (excepttypes.OOM,)
        if i.min < 0:
            etypes += (excepttypes.NegArrSize,)

        eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
        rout = ObjectConstraint.fromTops(self.env, [], [self.tt], nonnull=True)
        return rout, eout, DUMMY

class MultiNewArray(BaseOp):
    def __init__(self, parent, params, type_, monad):
        super(MultiNewArray, self).__init__(parent, [monad] + params, makeException=True, makeMonad=True)
        self.tt = type_
        self.rval = parent.makeVariable(SSA_OBJECT, origin=self)
        self.env = parent.env

    def propagateConstraints(self, m, *dims):
        for i in dims:
            if i.max < 0: #ignore possibility of OOM here
                eout = ObjectConstraint.fromTops(self.env, [], (excepttypes.NegArrSize,), nonnull=True)
                return None, eout, m

        etypes = (excepttypes.OOM,)
        for i in dims:
            if i.min < 0:
                etypes += (excepttypes.NegArrSize,)
                break

        eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
        rout = ObjectConstraint.fromTops(self.env, [], [self.tt], nonnull=True)
        return rout, eout, DUMMY