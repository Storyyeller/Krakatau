from .base import BaseJump
from ..constraints import IntConstraint
from .goto import Goto
import collections

class Switch(BaseJump):
    def __init__(self, parent, default, table, arguments):
        super(Switch, self).__init__(parent, arguments)

        #get ordered successors since our map will be unordered. Default is always first successor
        if not table:
            ordered = [default]
        else:
            tset = set()
            ordered = [x for x in (default,) + zip(*table)[1] if not x in tset and not tset.add(x)]

        self.successors = ordered
        self.reverse = collections.defaultdict(set)
        for k,v in table:
            if v != default:
                self.reverse[v].add(k)

    def getNormalSuccessors(self):
        return self.successors

    def replaceBlocks(self, blockDict):
        self.successors = [blockDict.get(key,key) for key in self.successors]
        self.reverse = {blockDict.get(k,k):v for k,v in self.reverse.items()}

    def reduceSuccessors(self, pairsToRemove):
        temp = list(self.successors)
        for (child, t) in pairsToRemove:
            temp.remove(child)

        if len(temp) == 0:
            return None
        elif len(temp) == 1:
            return Goto(self.parent, temp.pop())
        elif len(temp) < len(self.successors):
            self.successors = temp
            self.reverse = {v:self.reverse[v] for v in temp[1:]}
        return self

    #TODO - implement constrainJumps and getSuccessorConstraints
