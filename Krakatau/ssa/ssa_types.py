import collections, itertools

from .. import floatutil as fu
from .. import verifier_types as vtypes

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
                vtypes.T_LONG[0]:SSA_LONG, 
                vtypes.T_FLOAT:SSA_FLOAT, 
                vtypes.T_DOUBLE[0]:SSA_DOUBLE}
    if vtype.isObject:
        return SSA_OBJECT
    elif vtype in vtype_dict:
        return vtype_dict[vtype]
    return None

class Variable(object):
    def __init__(self, type_, origin=None, name=""):
        self.type = type_
        self.origin = origin
        self.name = name
        self.const = None 
        self.decltype = None #for objects, the inferred type from the verifier if any
        self.verifier_type = None

    #for debugging
    def __str__(self):
        return self.name if self.name else super(Variable, self).__str__()

    def __repr__(self):
        name =  self.name if self.name else "@" + hex(id(self))
        return "Var {}".format(name)

class BasicBlock(object):
    def __init__(self, key, lines, jump):
        self.key = key
        self.phis = None #to be filled in later
        self.lines = lines
        self.jump = jump
        self.unaryConstraints = collections.OrderedDict()
        self.zombie = False

        #temp vars used during graph creation
        self.sourceStates = collections.OrderedDict()

    def getOps(self):
        return self.phis + self.lines

    def getSuccessors(self): 
        return self.jump.getSuccessors()

    def filterVarConstraints(self, keepvars):
        # print 'unused vars', [t[0] for t in self.unaryConstraints.items() if t[0] not in keepvars]
        pairs = [t for t in self.unaryConstraints.items() if t[0] in keepvars]
        self.unaryConstraints = collections.OrderedDict(pairs)

    def __str__(self):
        return 'Block ' + str(self.key)
    __repr__ = __str__

