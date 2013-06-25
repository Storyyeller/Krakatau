from .base import BaseOp
from .. import excepttypes
from ..constraints import ObjectConstraint

class Throw(BaseOp):
    def __init__(self, parent, args):
        super(Throw, self).__init__(parent, args, makeException=True)
        self.env = parent.env

    def propagateConstraints(self, x):
        if x.null:
            t = x.types
            exact = list(t.exact) + [excepttypes.NullPtr]
            return None, ObjectConstraint.fromTops(t.env, t.supers, exact, nonnull=True), None
        return None, x, None