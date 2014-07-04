import copy

def flattenslots(slots):
    return [slots.monad] + slots.stack + slots.locals

class ProcInfo(object):
    def __init__(self, retblock, target):
        self.retblock = retblock
        self.target = target
        self.jsrblocks = []
        assert(target is retblock.jump.target)

    def __str__(self): return 'Proc{}<{}>'.format(self.target.key, ', '.join(str(b.key) for b in self.jsrblocks))
    __repr__ = __str__

###########################################################################################
class ProcJumpBase(object):
    @property
    def params(self):
        return [v for v in self.input if v is not None]

    def getExceptSuccessors(self): return ()
    def getSuccessors(self): return self.getNormalSuccessors()
    def getSuccessorPairs(self): return [(x,False) for x in self.getNormalSuccessors()]
    def reduceSuccessors(self, pairsToRemove): return self

class ProcCallOp(ProcJumpBase):
    def __init__(self, target, fallthrough, inslots, outslots):
        self.fallthrough = fallthrough
        self.target = target
        self.input = flattenslots(inslots)
        self.output = flattenslots(outslots)
        self.out_localoff = 1 + len(outslots.stack) #store so we can unflatten outslots if necessary
        self.debug_skipvars = None #keep track for debugging

        for var in self.output:
            if var is not None:
                assert(var.origin is None)
                var.origin = self

    def getNormalSuccessors(self): return self.fallthrough, self.target

class DummyRet(ProcJumpBase):
    def __init__(self, inslots, target):
        self.target = target
        self.input = flattenslots(inslots)

    def replaceBlocks(self, blockDict):
        self.target = blockDict[self.target]

    def replaceVars(self, varDict):
        self.input = [varDict.get(v,v) for v in self.input]

    def getNormalSuccessors(self): return ()
    def clone(self): return copy.copy(self) #target and input will be replaced later by calls to replaceBlocks/Vars
