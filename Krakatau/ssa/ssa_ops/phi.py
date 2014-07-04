class Phi(object):
    __slots__ = 'block dict rval'.split()
    def __init__(self, block, rval):
        self.block = block #used in constraint propagation
        self.dict = {}
        self.rval = rval
        assert(rval is not None and rval.origin is None)
        rval.origin = self

    def add(self, key, val):
        assert(key not in self.dict)
        assert(val.type == self.rval.type)
        assert(val is not None)
        self.dict[key] = val

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
