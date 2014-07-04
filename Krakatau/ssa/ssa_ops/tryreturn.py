from .base import BaseOp
from .. import excepttypes
from ..constraints import ObjectConstraint

class TryReturn(BaseOp):
    def __init__(self, parent, monad, canthrow=True):
        super(TryReturn, self).__init__(parent, [monad], makeException=True)
        canthrow = True #TODO - temporary hack until try/catch structuring improves
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], (excepttypes.MonState,), nonnull=True) if canthrow else None

    def propagateConstraints(self, x):
        return None, self.outExceptionCons, None