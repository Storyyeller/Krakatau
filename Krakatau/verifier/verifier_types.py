import collections, itertools

#Define types for Inference
nt = collections.namedtuple
_prim_cat1t = nt('_prim_cat1t', ['type','isObject','cat2'])
_prim_cat2t = nt('_prim_cat2t', ['type','isObject','cat2','top'])
_address_t = nt('_prim_cat2t', ['type','isObject','cat2','entryPoint'])
_obj_t = nt('_obj_t', ['isObject','cat2','isNull','isInit','origin','dim','baset'])

#override print functions
_prim_cat1t.__str__ = lambda t: t.type or 'INVALID'
_prim_cat2t.__str__ = lambda t: t.type if not t.top else '<top>'
_address_t.__str__ = lambda t: 'addr<{}>'.format(t.entryPoint)

def _printObjectType(t):
    if t.isNull:
        return '<null>'
    if not t.isInit:
        if t.origin is None:
            return '<uninit this>'
        else:
            return '<uninit @{}>{}'.format(t.origin, t.baset)
    if t.dim:
        return t.baset.__str__() + '[]'
    return t.baset
_obj_t.__str__ = _printObjectType

def _makeprim(name, cat2):
    if cat2: #cat2 types return a tuple of botType, topType
        bot = _prim_cat2t(name, False, True, top=False)
        top = _prim_cat2t(name, False, True, top=True)
        return bot,top
    else:
        return _prim_cat1t(name, False, False)

#singleton types
T_INVALID = _makeprim(None, False)
T_INT = _makeprim('int', False)
T_FLOAT = _makeprim('float', False)
T_LONG = _makeprim('long', True)        
T_DOUBLE = _makeprim('double', True)
T_NULL = _obj_t(True,False, isNull=True, isInit=True, origin=None, dim=0, baset=None)

#synthetic types - these are only used for the base types of arrays
T_SHORT = _makeprim('short', False)
T_CHAR = _makeprim('char', False)
T_BYTE = _makeprim('byte', False)
T_BOOL = _makeprim('bool', False)

#types with arguments
def T_ADDRESS(entry):
    return _address_t('address',False,False, entryPoint=entry)

def T_OBJECT(name):
    return _obj_t(True,False, isNull=False, isInit=True, origin=None, dim=0, baset=name)

def T_ARRAY(baset, newDimensions=1):
    assert(newDimensions >= 0) #internal assertion
    assert(baset != T_INVALID)
    while newDimensions:
        baseDim = baset.dim if (baset != T_WILDCARD and baset.isObject) else 0
        baset = _obj_t(True,False, isNull=False, isInit=True,
                       origin=None, dim=baseDim+1, baset=baset)
        newDimensions -= 1
    return baset

def T_UNINIT_OBJECT(name, origin):
    return _obj_t(True,False, isNull=False, isInit=False, origin=origin, dim=0, baset=name)

def T_UNINIT_THIS(name):
    return T_UNINIT_OBJECT(name, None)

#Only used for type checking patterns - should never acutally appear
T_WILDCARD = None
T_WILDCARD_ARRAY = T_ARRAY(T_WILDCARD)

def unSynthesizeType(t):
    if t in (T_BOOL, T_BYTE, T_CHAR, T_SHORT):
        return T_INT
    return t

def mergeTypes(env, t1, t2, forAssignment=False):
    #Note: This function is intended to have the same results as the equivalent function in Hotspot's old inference verifier
    #even though our implementation is completely different. Be careful when rearranging the steps.
    if t1 == t2:
        return t1
    #Part of our wildcard array checking. I'm not sure how Hotspot does things
    elif t2 == T_WILDCARD_ARRAY:
        if forAssignment and t1.isObject and t1.dim:
            return t2
        return T_INVALID
    elif t1.isObject and t2.isObject and t1.isInit and t2.isInit:
        if t1.isNull:
            return t2
        if t2.isNull:
            return t1

        if t2 == T_OBJECT('java/lang/Object'):
            return t2
        elif t1 == T_OBJECT('java/lang/Object'):
            #Hotspot's inference verifier allows (nonarray) objects to be assigned to interfaces
            if forAssignment and t2.dim == 0 and 'INTERFACE' in env.getFlags(t2.baset):
                return t2
            return t1

        if t1.dim or t2.dim:
            if t1.dim == t2.dim:
                temp = mergeTypes(env, t1.baset, t2.baset, forAssignment)
                return temp if temp is T_INVALID else T_ARRAY(temp) 
            else:
                if t1.dim > t2.dim:
                    t1, t2 = t2, t1
                temp = t1
                while temp.dim and temp.baset.isObject:
                    temp = temp.baset
                if temp.baset in  ('java/lang/Cloneable','java/io/Serializable'):
                    return t1
                return T_ARRAY(T_OBJECT('java/lang/Object'), t1.dim)
        else: #neither is an array, get first common superclass
            if forAssignment and 'INTERFACE' in env.getFlags(t2.baset): 
                return t2
            hierarchy1 = env.getSupers(t1.baset)
            hierarchy2 = env.getSupers(t2.baset)
            matches = [x for x,y in zip(hierarchy1,hierarchy2) if x==y]
            assert(matches[0] == 'java/lang/Object') #internal assertion
            return T_OBJECT(matches[-1])        
    return T_INVALID

def isAssignable(env, t1, t2):
    return mergeTypes(env, t1, t2, True) == t2

def isAssignableSeq(env, seq1, seq2):
    if (len(seq1) != len(seq2)):
        return False
    return all(isAssignable(env, t1, t2) for t1,t2 in zip(seq1, seq2))

def mergeTypeSequences(env, seq1, seq2, lazyLength):
    if lazyLength:
        zipped = itertools.izip_longest(seq1, seq2, fillvalue=T_INVALID)
        zipped = list(zipped)
    else:
        if (len(seq1) != len(seq2)):
            return None
        zipped = zip(seq1, seq2)
    
    merged = []
    #We go until we find one that can't be assigned and then merge the rest
    #Note that this is not the same as merging everything because isAssignable
    #Allows objects to be assigned to interfaces
    for val, target in zipped:
        if isAssignable(env, val, target):
            merged.append(target)
        else:
            break
    i = len(merged)
    if i < len(zipped):
        merged.extend(mergeTypes(env, t1, t2) for t1,t2 in zipped[i:])
    #now prune end of the list to (potentially) save space and time later
    if lazyLength:
        while merged and merged[-1] == T_INVALID:
            merged.pop()
    return tuple(merged)


