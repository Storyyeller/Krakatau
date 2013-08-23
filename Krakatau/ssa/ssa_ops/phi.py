import collections
from .base import BaseOp

class Phi(BaseOp):
    def __init__(self, parent, block, vals, rval):
        super(Phi, self).__init__(parent, ())
        self.block = block #used in constraint propagation
        self.dict = vals
        self.rval = rval
        assert(rval is not None)
        del self._params #in superclass

    @property
    def params(self): return [self.dict[k] for k in self.block.predecessors]

    def get(self, key): return self.dict[key]

    def replaceVars(self, rdict): #override SSAFunctionBase
        for k in self.dict:
            self.dict[k] = rdict.get(self.dict[k], self.dict[k])