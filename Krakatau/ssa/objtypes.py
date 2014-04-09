from ..verifier import verifier_types as vtypes
from ..error import ClassLoaderError

#types are represented by classname, dimension
#primative types are .int, etc since these cannot be valid classnames since periods are forbidden
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
    if x == y or y == ObjectTT or x == NullTT:
        return True
    elif y == NullTT:
        return False
    xname, xdim = x
    yname, ydim = y

    if ydim > xdim:
        return False
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
_verifierConvert = {vtypes.T_INT:IntTT, vtypes.T_FLOAT:FloatTT, vtypes.T_LONG:LongTT,
        vtypes.T_DOUBLE:DoubleTT, vtypes.T_SHORT:ShortTT, vtypes.T_CHAR:CharTT,
        vtypes.T_BYTE:ByteTT, vtypes.T_BOOL:BoolTT, vtypes.T_NULL:NullTT,
        vtypes.OBJECT_INFO:ObjectTT}

def verifierToSynthetic_seq(vtypes):
    return [verifierToSynthetic(vtype) for vtype in vtypes if not (vtype.tag and vtype.tag.endswith('2'))]

def verifierToSynthetic(vtype):
    assert(vtype.tag not in (None, '.address', '.double2', '.long2', '.new', '.init'))

    if vtype in _verifierConvert:
        return _verifierConvert[vtype]

    base = vtypes.withNoDimension(vtype)
    if base in _verifierConvert:
        return _verifierConvert[base][0], vtype.dim

    return vtype.extra, vtype.dim

#returns supers, exacts
def declTypeToActual(env, decltype):
    name, dim = decltype

    #Verifier treats bool[]s and byte[]s as interchangeable, so it could really be either
    if dim and (name == ByteTT[0] or name == BoolTT[0]):
        return [], [(ByteTT[0], dim), (BoolTT[0], dim)]
    elif name[0] == '.': #primative types can't be subclassed anyway
        return [], [decltype]

    try:
        flags = env.getFlags(name)
    except ClassLoaderError: #assume the worst if we can't find the class
        flags = set(['INTERFACE'])

    #Verifier doesn't fully verify interfaces so they could be anything
    if 'INTERFACE' in flags:
        return [(ObjectTT[0],dim)], []
    else:
        exact = 'FINAL' in flags
        if exact:
            return [], [decltype]
        else:
            return [decltype], []


