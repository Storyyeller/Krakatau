from .base import BaseOp
from .. import excepttypes
from ..constraints import ObjectConstraint

class TryReturn(BaseOp):
    def __init__(self, parent, canthrow=True):
        super(TryReturn, self).__init__(parent, [], makeException=True)
        canthrow = True #TODO - temporary hack until try/catch structuring improves
        self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], (excepttypes.MonState,), nonnull=True) if canthrow else None

    def propagateConstraints(self):
        return None, self.outExceptionCons