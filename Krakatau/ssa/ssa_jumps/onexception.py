from .base import BaseJump
from .goto import Goto
from ..exceptionset import  CatchSetManager, ExceptionSet
from ..constraints import ObjectConstraint

class OnException(BaseJump):
    def __init__(self, parent, key, line, rawExceptionHandlers, fallthrough=None):
        super(OnException, self).__init__(parent, [line.outException])
        self.default = fallthrough

        chpairs = []
        for (start, end, handler, index) in rawExceptionHandlers:
            if start <= key < end:
                catchtype = parent.getConstPoolArgs(index)[0] if index else 'java/lang/Throwable'
                chpairs.append((catchtype, handler))
        self.cs = CatchSetManager(parent.env, chpairs)
        self.cs.pruneKeys()

    def replaceExceptTarget(self, old, new):
        self.cs.replaceKeys({old:new})

    def replaceNormalTarget(self, old, new):
        self.default = new if self.default == old else self.default

    def replaceBlocks(self, blockDict):
        self.cs.replaceKeys(blockDict)
        if self.default is not None and self.default in blockDict:
            self.default = blockDict[self.default]

    def reduceSuccessors(self, pairsToRemove):
        for (child, t) in pairsToRemove:
            if t:
                self.cs.mask -= self.cs.sets[child]
                del self.cs.sets[child]
            else:
                self.replaceNormalTarget(child, None)
                
        self.cs.pruneKeys()
        if not self.cs.sets:
            if not self.default:
                return None
            return Goto(self.parent, self.default)
        return self

    def getNormalSuccessors(self):
        return [self.default] if self.default is not None else []

    def getExceptSuccessors(self):
        return self.cs.sets.keys()

    def clone(self): 
        new = super(OnException, self).clone()
        new.cs = self.cs.copy()
        return new

    ###############################################################################
    def constrainJumps(self, x):
        if x is None:
            mask = ExceptionSet.EMPTY
        else:
            mask = ExceptionSet(x.types.env, [(name,()) for name,dim in x.types.supers | x.types.exact])
        self.cs.newMask(mask)
        return self.reduceSuccessors([])

    def getSuccessorConstraints(self, (block, t)):
        if t:
            def propagateConstraints(x):
                if x is None:
                    return None
                t = x.types 
                top_tts = t.supers | t.exact
                tops = [tt[0] for tt in top_tts]
                if 'java/lang/Object' in tops:
                    tops = 'java/lang/Throwable',
                mask = ExceptionSet.fromTops(t.env, *tops)

                eset = self.cs.sets[block] & mask
                if not eset:
                    return None,
                else:
                    ntops = zip(*eset.pairs)[0]
                    return ObjectConstraint.fromTops(t.env, [(base,0) for base in ntops], [], nonnull=True),
            return propagateConstraints
        else:
            #In fallthrough case, no exception so always return invalid
            assert(block == self.default)
            return lambda arg:[None]


            