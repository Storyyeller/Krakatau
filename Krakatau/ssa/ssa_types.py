import collections

from .. import floatutil as fu
from ..verifier import verifier_types as vtypes

nt = collections.namedtuple
slots_t = nt('slots_t', ('monad', 'locals', 'stack'))

#types
SSA_INT = 'int', 32
SSA_LONG = 'int', 64
SSA_FLOAT = 'float', fu.FLOAT_SIZE
SSA_DOUBLE = 'float', fu.DOUBLE_SIZE
SSA_OBJECT = 'obj',

#internal types
SSA_MONAD = 'monad',

def verifierToSSAType(vtype):
    vtype_dict = {vtypes.T_INT:SSA_INT,
                vtypes.T_LONG:SSA_LONG,
                vtypes.T_FLOAT:SSA_FLOAT,
                vtypes.T_DOUBLE:SSA_DOUBLE}
    #These should never be passed in here
    assert(vtype.tag not in ('.new','.init'))
    if vtypes.objOrArray(vtype):
        return SSA_OBJECT
    elif vtype in vtype_dict:
        return vtype_dict[vtype]
    return None

class BasicBlock(object):
    def __init__(self, key, lines, jump):
        self.key = key
        # The list of phi statements merging incoming variables
        self.phis = None #to be filled in later
        # List of operations in the block
        self.lines = lines
        # The exit point (if, goto, etc)
        self.jump = jump
        # Holds constraints (range and type information) for each variable in the block.
        # If the value is None, this variable cannot be reached
        self.unaryConstraints = collections.OrderedDict()
        # List of predecessor pairs in deterministic order
        self.predecessors = None

        #temp vars used during graph creation
        self.sourceStates = collections.OrderedDict()
        self.successorStates = None
        self.tempvars = []
        self.inslots = None
        self.keys = [key]

    def getOps(self):
        return self.phis + self.lines

    def getSuccessors(self):
        return self.jump.getSuccessors()

    def filterVarConstraints(self, keepvars):
        pairs = [t for t in self.unaryConstraints.items() if t[0] in keepvars]
        self.unaryConstraints = collections.OrderedDict(pairs)

    def removePredPair(self, pair):
        self.predecessors.remove(pair)
        for phi in self.phis:
            del phi.dict[pair]

    def replacePredPair(self, oldp, newp):
        self.predecessors[self.predecessors.index(oldp)] = newp
        for phi in self.phis:
            phi.dict[newp] = phi.dict[oldp]
            del phi.dict[oldp]

    def __str__(self):
        return 'Block ' + str(self.key)
    __repr__ = __str__