from .base import BaseOp
from .. import excepttypes
from ..constraints import ObjectConstraint
from ..constraints import returnOrThrow, maybeThrow, throw, return_

class Throw(BaseOp):
    def __init__(self, parent, args):
        super(Throw, self).__init__(parent, args, makeException=True)
        self.env = parent.env

    def propagateConstraints(self, x):
        if x.null:
            t = x.types
            exact = list(t.exact) + [excepttypes.NullPtr]
            return throw(ObjectConstraint.fromTops(t.env, t.supers, exact, nonnull=True))
        return throw(x)