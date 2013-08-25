import collections

class Phi(object):
    __slots__ = 'block dict rval'.split()

    def __init__(self, parent, block, vals, rval):
        self.block = block #used in constraint propagation
        self.dict = vals
        self.rval = rval
        assert(rval is not None)

    @property
    def params(self): return [self.dict[k] for k in self.block.predecessors]

    def get(self, key): return self.dict[key]

    #Copy these over from BaseOp so we don't need to inherit
    def replaceVars(self, rdict):
        for k in self.dict:
            self.dict[k] = rdict.get(self.dict[k], self.dict[k])

    def getOutputs(self):
        return self.rval, None, None

    def removeOutput(self, var):
        assert(var == self.rval)
        self.rval = None

    def replaceOutVars(self, vardict):
        self.rval = vardict.get(self.rval)
