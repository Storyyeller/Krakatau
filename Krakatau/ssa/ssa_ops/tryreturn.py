from .base import BaseOp
from .. import excepttypes
from ..constraints import ObjectConstraint
from ..constraints import returnOrThrow, maybeThrow, throw, return_

class TryReturn(BaseOp):
    def __init__(self, parent, canthrow=True):
        super(TryReturn, self).__init__(parent, [], makeException=True)
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], (excepttypes.MonState,), nonnull=True)

    def propagateConstraints(self):
        return maybeThrow(self.outExceptionCons)