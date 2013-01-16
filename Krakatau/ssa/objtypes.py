from ..verifier import verifier_types as vtypes

#types are represented by classname, dimension
#primative types are <int>, etc since these cannot be valid classnames
NullTT = '.null', 0
ObjectTT = 'java/lang/Object', 0
StringTT = 'java/lang/String', 0
ThrowableTT = 'java/lang/Throwable', 0
ClassTT = 'java/lang/Class', 0

BoolTT = '.boolean', 0
IntTT = '.int', 0
LongTT = '.long', 0
FloatTT = '.float', 0
DoubleTT = '.double', 0

ByteTT = '.byte', 0
CharTT = '.char', 0
ShortTT = '.short', 0

def isSubtype(env, x, y):
    if x==y or y==ObjectTT or x==NullTT:
        return True
    elif y==NullTT:
        return False
    xname, xdim = x
    yname, ydim = y

    if ydim > xdim:
        return env.isSubclass(xname, yname)
    elif xdim > ydim: #TODO - these constants should be defined in one place to reduce risk of typos
        return yname in ('java/lang/Object','java/lang/Cloneable','java/io/Serializable')
    else:
        return xname[0] != '.' and yname[0] != '.' and env.isSubclass(xname, yname)

#Will not return interface unless all inputs are same interface or null
def commonSupertype(env, tts):
    assert(hasattr(env, 'getClass')) #catch common errors where we forget the env argument

    tts = set(tts)
    tts.discard(NullTT)

    if len(tts) == 1:
        return tts.pop()
    elif not tts:
        return NullTT

    bases, dims = zip(*tts)
    dim = min(dims)
    if max(dims) > dim or 'java/lang/Object' in bases:
        return 'java/lang/Object', dim 
    #all have same dim, find common superclass
    if any(base[0] == '.' for base in bases):
        return 'java/lang/Object', dim-1

    baselists = [env.getSupers(name) for name in bases]
    common = [x for x in zip(*baselists) if len(set(x)) == 1]
    return common[-1][0], dim

######################################################################################################
_verifierPrims = {vtypes.T_INT:'.int', vtypes.T_FLOAT:'.float', vtypes.T_LONG[0]:'.long',
        vtypes.T_DOUBLE[0]:'.double', vtypes.T_SHORT:'.short', vtypes.T_CHAR:'.char',
        vtypes.T_BYTE:'.byte', vtypes.T_BOOL:'.boolean'}

def verifierToSynthetic_seq(vtypes):
    return [verifierToSynthetic(vtype) for vtype in vtypes if not (vtype.cat2 and vtype.top)]

def verifierToSynthetic(vtype):
    if vtype in _verifierPrims:
        return _verifierPrims[vtype], 0
    return verifierToDeclType(vtype)

def verifierToDeclType(vtype):
    assert(vtype.isObject)
    if vtype.isNull:
        return ('.null', 0)

    dim = vtype.dim
    while vtype.isObject and vtype.dim:
        vtype = vtype.baset

    basename = _verifierPrims[vtype] if vtype in _verifierPrims else vtype.baset
    assert(basename.lower)
    return (basename, dim)

#returns supers, exacts
def declTypeToActual(env, decltype):
    name, dim = decltype 

    #Verifier treats bool[]s and byte[]s as interchangeable, so it could really be either
    if dim and (name == '.boolean' or name == '.byte'):
        return [], [('.byte', dim), ('.boolean', dim)]
    elif name[0] == '.': #primative types can't be subclassed anyway
        return [], [decltype]
    #Verifier doesn't fully verify interfaces so they could be anything
    elif 'INTERFACE' in env.getFlags(name):
        return [(ObjectTT[0],dim)], []
    else:
        exact = 'FINAL' in env.getFlags(name)
        if exact:
            return [], [decltype]
        else:
            return [decltype], []