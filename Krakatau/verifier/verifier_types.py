import collections

#Define types for Inference
nt = collections.namedtuple
fullinfo_t = nt('fullinfo_t', ['tag','dim','extra'])

#Differences from Hotspot with our tags:
#BOGUS changed to None. Array omitted as it is unused. Void omitted as unecessary. Boolean added
valid_tags = ['.'+x for x in 'int float double double2 long long2 obj new init address byte short char boolean'.split()]
valid_tags = frozenset([None] + valid_tags)

def _makeinfo(tag, dim=0, extra=None):
    assert(tag in valid_tags)
    return fullinfo_t(tag, dim, extra)


T_INVALID = _makeinfo(None)
T_INT = _makeinfo('.int')
T_FLOAT = _makeinfo('.float')
T_DOUBLE = _makeinfo('.double')
T_DOUBLE2 = _makeinfo('.double2') #Hotspot only uses these in locals, but we use them on the stack too to simplify things
T_LONG = _makeinfo('.long')
T_LONG2 = _makeinfo('.long2')

T_NULL = _makeinfo('.obj')
T_UNINIT_THIS = _makeinfo('.init')

T_BYTE = _makeinfo('.byte')
T_SHORT = _makeinfo('.short')
T_CHAR = _makeinfo('.char')
T_BOOL = _makeinfo('.boolean') #Hotspot doesn't have a bool type, but we can use this elsewhere

cat2tops = {T_LONG:T_LONG2, T_DOUBLE:T_DOUBLE2}

#types with arguments
def T_ADDRESS(entry):
    return _makeinfo('.address', extra=entry)

def T_OBJECT(name):
    return _makeinfo('.obj', extra=name)

def T_ARRAY(baset, newDimensions=1):
    assert(0 <= baset.dim <= 255-newDimensions)
    return _makeinfo(baset.tag, baset.dim+newDimensions, baset.extra)

def T_UNINIT_OBJECT(origin):
    return _makeinfo('.new', extra=origin)

OBJECT_INFO = T_OBJECT('java/lang/Object')
CLONE_INFO = T_OBJECT('java/lang/Cloneable')
SERIAL_INFO = T_OBJECT('java/io/Serializable')

def objOrArray(fi): #False on uninitialized
    return fi.tag == '.obj' or fi.dim > 0

def unSynthesizeType(t):
    if t in (T_BOOL, T_BYTE, T_CHAR, T_SHORT):
        return T_INT
    return t

def decrementDim(fi):
    if fi == T_NULL:
        return T_NULL
    assert(fi.dim)
    
    tag = unSynthesizeType(fi).tag if fi.dim <= 1 else fi.tag
    return _makeinfo(tag, fi.dim-1, fi.extra)

def withNoDimension(fi):
    return _makeinfo(fi.tag, 0, fi.extra)

def _decToObjArray(fi):
    return fi if fi.tag == '.obj' else T_ARRAY(OBJECT_INFO, fi.dim-1)

def _arrbase(fi):
    return _makeinfo(fi.tag, 0, fi.extra)

def mergeTypes(env, t1, t2, forAssignment=False):
    #Note: This function is intended to have the same results as the equivalent function in Hotspot's old inference verifier
    if t1 == t2:
        return t1
    #non objects must match exactly
    if not objOrArray(t1) or not objOrArray(t2):
        return T_INVALID

    if t1 == T_NULL:
        return t2
    elif t2 == T_NULL:
        return t1

    if t1 == OBJECT_INFO or t2 == OBJECT_INFO:
        if forAssignment and t2.dim == 0 and 'INTERFACE' in env.getFlags(t2.extra):
            return t2 #Hack for interface assignment
        return OBJECT_INFO

    if t1.dim or t2.dim:
        for x in (t1,t2):
            if x in (CLONE_INFO,SERIAL_INFO):
                return x
        t1 = _decToObjArray(t1)
        t2 = _decToObjArray(t2)

        if t1.dim > t2.dim:
            t1, t2 = t2, t1

        if t1.dim == t2.dim:
            res = mergeTypes(env, _arrbase(t1), _arrbase(t2), forAssignment)
            return res if res == T_INVALID else _makeinfo('.obj', t1.dim, res.extra)
        else: #t1.dim < t2.dim
            return t1 if _arrbase(t1) in (CLONE_INFO,SERIAL_INFO) else T_ARRAY(OBJECT_INFO, t1.dim)
    else: #neither is array 
        if 'INTERFACE' in env.getFlags(t2.extra):
            return t2 if forAssignment else OBJECT_INFO

        hierarchy1 = env.getSupers(t1.extra)
        hierarchy2 = env.getSupers(t2.extra)
        matches = [x for x,y in zip(hierarchy1,hierarchy2) if x==y]
        assert(matches[0] == 'java/lang/Object') #internal assertion
        return T_OBJECT(matches[-1])        

def isAssignable(env, t1, t2):
    return mergeTypes(env, t1, t2, True) == t2

#Make verifier types printable for easy debugging
def vt_toStr(self):
    if self == T_INVALID:
        return '.none'
    elif self == T_NULL:
        return '.null'
    if self.tag == '.obj':
        base = self.extra
    elif self.extra is not None:
        base = '{}<{}>'.format(self.tag, self.extra)
    else:
        base = self.tag
    return base + '[]'*self.dim
fullinfo_t.__str__ = fullinfo_t.__repr__ = vt_toStr