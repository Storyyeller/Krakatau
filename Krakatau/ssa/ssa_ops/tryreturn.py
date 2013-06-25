from .base import BaseOp
from .. import excepttypes
from ..constraints import ObjectConstraint

class TryReturn(BaseOp):
    def __init__(self, parent, monad):
        super(TryReturn, self).__init__(parent, [monad], makeException=True)
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], (excepttypes.MonState,), nonnull=True)

    def propagateConstraints(self, x):
        return None, self.outExceptionCons, None