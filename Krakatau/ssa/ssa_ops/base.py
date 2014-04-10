from ..functionbase import SSAFunctionBase
from ..ssa_types import SSA_OBJECT, SSA_MONAD

class BaseOp(SSAFunctionBase):
    def __init__(self, parent, arguments, makeException=False, makeMonad=False):
        super(BaseOp, self).__init__(parent,arguments)

        self.rval = None
        self.outException = None
        self.outMonad = None

        if makeException:
            self.outException = parent.makeVariable(SSA_OBJECT, origin=self)
        if makeMonad:
            self.outMonad = parent.makeVariable(SSA_MONAD, origin=self)

    def getOutputs(self):
        return self.rval, self.outException, self.outMonad

    def removeOutput(self, var):
        outs = self.rval, self.outException, self.outMonad
        assert(var is not None and var in outs)
        self.rval, self.outException, self.outMonad = [(x if x != var else None) for x in outs]

    def replaceOutVars(self, vardict):
        self.rval, self.outException, self.outMonad = map(vardict.get, (self.rval, self.outException, self.outMonad))

    # Given input constraints, return constraints on outputs. Output is (rval, exception, monad)
    # With None returned for unused or impossible values. This should only be defined if it is
    # actually implemented.
    # def propagateConstraints(self, *cons):