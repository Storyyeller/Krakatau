from .base import BaseOp
from ..ssa_types import SSA_INT

from .. import excepttypes
from ..constraints import IntConstraint, FloatConstraint, ObjectConstraint, DUMMY

def getElementTypes(env, tops):
    types = [(base,dim-1) for base,dim in tops]
    supers = [tt for tt in types if not tt[0].startswith('.')]
    exact = [tt for tt in types if tt[0].startswith('.')]
    return ObjectConstraint.fromTops(env, supers, exact)

class ArrLoad(BaseOp):
    def __init__(self, parent, args, ssatype, monad):
        super(ArrLoad, self).__init__(parent, [monad]+args, makeException=True)
        self.env = parent.env
        self.rval = parent.makeVariable(ssatype, origin=self)
        self.ssatype = ssatype

    def propagateConstraints(self, m, a, i):
        etypes = (excepttypes.ArrayOOB,)
        if a.null:
            etypes += (excepttypes.NullPtr,)
            if a.isConstNull():
                return None, ObjectConstraint.fromTops(self.env, [], [excepttypes.NullPtr], nonnull=True), None

        if self.ssatype[0] == 'int':
            rout = IntConstraint.bot(self.ssatype[1])
        elif self.ssatype[0] == 'float':
            rout = FloatConstraint.bot(self.ssatype[1])
        elif self.ssatype[0] == 'obj':
            rout = getElementTypes(self.env, a.types.supers | a.types.exact)

        eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
        return rout, eout, None

class ArrStore(BaseOp):
    def __init__(self, parent, args, monad):
        super(ArrStore, self).__init__(parent, [monad]+args, makeException=True, makeMonad=True)
        self.env = parent.env

    def propagateConstraints(self, m, a, i, x):
        etypes = (excepttypes.ArrayOOB,)
        if a.null:
            etypes += (excepttypes.NullPtr,)
            if a.isConstNull():
                return None, ObjectConstraint.fromTops(self.env, [], [excepttypes.NullPtr], nonnull=True), m

        if isinstance(x, ObjectConstraint):
            # If the type of a is known exactly to be the single possibility T[]
            # and x is assignable to T, we can assume there is no ArrayStore exception
            # if a's type has multiple possibilities, then there can be an exception
            known_type = a.types.exact if len(a.types.exact) == 1 else frozenset()
            allowed = getElementTypes(self.env, known_type)
            if allowed.meet(x) != allowed:
                etypes += (excepttypes.ArrayStore,)

        eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
        return None, eout, DUMMY

class ArrLength(BaseOp):
    def __init__(self, parent, args):
        super(ArrLength, self).__init__(parent, args, makeException=True)
        self.env = parent.env
        self.rval = parent.makeVariable(SSA_INT, origin=self)
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], (excepttypes.NullPtr,), nonnull=True)

    def propagateConstraints(self, x):
        etypes = ()
        if x.null:
            etypes += (excepttypes.NullPtr,)
            if x.isConstNull():
                return None, ObjectConstraint.fromTops(self.env, [], [excepttypes.NullPtr], nonnull=True), None

        excons = eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
        return IntConstraint.range(32, 0, (1<<31)-1), excons, None