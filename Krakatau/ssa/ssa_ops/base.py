from ..functionbase import SSAFunctionBase
from ..ssa_types import SSA_OBJECT

class BaseOp(SSAFunctionBase):
    def __init__(self, parent, arguments, makeException=False):
        super(BaseOp, self).__init__(parent,arguments)

        self.rval = None
        self.outException = None
        self.outMonad = None

        if makeException:
            self.outException = parent.makeVariable(SSA_OBJECT, origin=self)
            self.errorState = set([False, True])

    def getOutputs(self):
        outs = self.rval, self.outException, self.outMonad
        return [x for x in outs if x is not None]

    def removeOutput(self, var):
        outs = self.rval, self.outException, self.outMonad
        self.rval, self.outException, self.outMonad = [(x if x != var else None) for x in outs]

    def replaceOutVars(self, vardict):
        self.rval, self.outException, self.outMonad = map(vardict.get, (self.rval, self.outException, self.outMonad))

    # def propagateConstraints(self, *cons):
    #   return ?