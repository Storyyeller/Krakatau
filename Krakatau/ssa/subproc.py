import collections, copy
ODict = collections.OrderedDict

def slotsToDict(inslots):
    inputs = ODict({'m':inslots.monad})
    for i,v in enumerate(inslots.locals):
        if v is not None:
            inputs['r'+str(i)] = v
    for i,v in enumerate(inslots.stack):
        if v is not None:
            inputs['s'+str(i)] = v
    return inputs

class ProcInfo(object):
    def __init__(self, retblock, target=None):
        self.callops = ODict()
        self.retblock = retblock
        self.retop = retblock.jump
        if target is None: #if explicit target passed in, we are during proc splitting and no iNode refs are left
            target = retblock.jump.iNode.jsrTarget #just key for now, to be replaced later
        self.target = target

    def __str__(self): return 'Proc{}<{}>'.format(self.target.key, ', '.join(str(b.key) for b in self.callops.values()))
    __repr__ = __str__

###########################################################################################
class ProcJumpBase(object):
    @property
    def params(self): return self.input.values()

    def getExceptSuccessors(self): return ()
    def getSuccessors(self): return self.getNormalSuccessors()
    def getSuccessorPairs(self): return [(x,False) for x in self.getNormalSuccessors()]
    def reduceSuccessors(self, pairsToRemove): return self

class ProcCallOp(ProcJumpBase):
    def __init__(self, inslots, iNode):
        self.input = slotsToDict(inslots)
        self.iNode = iNode

        self.fallthrough = iNode.next_instruction
        self.target = iNode.successors[0]
        #self.out

    def registerOuts(self, outslots):
        self.out = slotsToDict(outslots)
        for var in self.out.values():
            assert(var.origin is None)
            var.origin = self

    def replaceBlocks(self, blockDict):
        self.fallthrough = blockDict.get(self.fallthrough, self.fallthrough)
        self.target = blockDict.get(self.target, self.target)

    def replaceVars(self, varDict):
        self.input = ODict((k,varDict.get(v,v)) for k,v in self.input.items())
        self.out = ODict((k,varDict.get(v,v)) for k,v in self.out.items())

    def getNormalSuccessors(self): return self.fallthrough, self.target

class DummyRet(ProcJumpBase):
    def __init__(self, inslots, iNode):
        self.input = slotsToDict(inslots)
        self.iNode = iNode

        self.target = iNode.jsrTarget

    def replaceBlocks(self, blockDict):
        self.target = blockDict.get(self.target, self.target)

    def replaceVars(self, varDict):
        self.input = ODict((k,varDict.get(v,v)) for k,v in self.input.items())

    def getNormalSuccessors(self): return ()

    def clone(self): return copy.copy(self) #input copied on modification anyway