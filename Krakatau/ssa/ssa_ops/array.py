from .base import BaseOp
from ..ssa_types import SSA_INT

from .. import excepttypes
from ..constraints import IntConstraint, FloatConstraint, ObjectConstraint, DUMMY

class ArrLoad(BaseOp):
    def __init__(self, parent, args, ssatype, monad):
        super(ArrLoad, self).__init__(parent, [monad]+args, makeException=True)
        self.env = parent.env
        self.rval = parent.makeVariable(ssatype, origin=self)
        self.ssatype = ssatype

    def propagateConstraints(self, m, a, i):
        etypes = ()
        if a.null:
            etypes += (excepttypes.NullPtr,)
            if a.isConstNull():
                return None, ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True), None

        if a.arrlen is None or (i.min >= a.arrlen.max) or i.max < 0:
            etypes += (excepttypes.ArrayOOB,)
            eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
            return None, eout, None
        elif (i.max >= a.arrlen.min) or i.min < 0:
            etypes += (excepttypes.ArrayOOB,)

        if self.ssatype[0] == 'int':
            rout = IntConstraint.bot(self.ssatype[1])
        elif self.ssatype[0] == 'float':
            rout = FloatConstraint.bot(self.ssatype[1])
        elif self.ssatype[0] == 'obj':
            supers = [(base,dim-1) for base,dim in a.types.supers]
            exact = [(base,dim-1) for base,dim in a.types.exact]
            rout = ObjectConstraint.fromTops(a.types.env, supers, exact)

        eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
        return rout, eout, None

class ArrStore(BaseOp):
    def __init__(self, parent, args, monad):
        super(ArrStore, self).__init__(parent, [monad]+args, makeException=True, makeMonad=True)
        self.env = parent.env

    def propagateConstraints(self, m, a, i, x):
        etypes = ()
        if a.null:
            etypes += (excepttypes.NullPtr,)
            if a.isConstNull():
                return None, ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True), m

        if a.arrlen is None or (i.min >= a.arrlen.max) or i.max < 0:
            etypes += (excepttypes.ArrayOOB,)
            eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
            return None, eout, m
        elif (i.max >= a.arrlen.min) or i.min < 0:
            etypes += (excepttypes.ArrayOOB,)

        if isinstance(x, ObjectConstraint):
            exact = [(base,dim-1) for base,dim in a.types.exact]
            allowed = ObjectConstraint.fromTops(a.types.env, exact, [])
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
                return None, ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True), None

        excons = eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
        return x.arrlen, excons, None