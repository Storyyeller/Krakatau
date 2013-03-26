import collections
from .base import BaseOp

class Phi(BaseOp):
    def __init__(self, parent, odict, rval):
        odict = collections.OrderedDict(odict)

        super(Phi, self).__init__(parent, odict.values())
        self.odict = odict
        self.rval = rval
        assert(rval is not None)
        #self.block must be set later for obvious reasons
        #block is used in constraint propagation

    def updateDict(self, newpairs):
        self.odict = collections.OrderedDict(newpairs)
        self.updateParams(self.odict.values())

    def replaceVars(self, rdict):
        pairs = [(k, rdict.get(x,x)) for k,x in self.odict.items()]
        self.updateDict(pairs)

    def replaceBlocks(self, rdict):
        pairs = [((rdict.get(x,x), t), v) for (x,t),v in self.odict.items()]
        self.updateDict(pairs)

    def replaceKey(self, old, new):
        pairs = [((new if x is old else x), v) for x,v in self.odict.items()]
        self.updateDict(pairs)  

    def removeKey(self, key):
        assert(key in self.odict)
        pairs = [(x, v) for x,v in self.odict.items() if x != key]
        self.updateDict(pairs)