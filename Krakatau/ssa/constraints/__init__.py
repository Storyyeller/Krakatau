import collections, itertools

from ... import floatutil
from .. import objtypes
from .int_c import IntConstraint
from .float_c import FloatConstraint
from .obj_c import ObjectConstraint
from .monad_c import MonadConstraint as DummyConstraint

#joins become more precise (intersection), meets become more general (union)
def join(*cons): 
    if None in cons:
        return None
    return cons[0].join(*cons[1:])

def meet(*cons):
    return cons[0].meet(*cons[1:])

DUMMY = DummyConstraint()

def fromConstant(env, var):
    ssa_type = var.type
    cval = var.const

    if ssa_type[0] == 'int':
        return IntConstraint.const(ssa_type[1], cval)    
    elif ssa_type[0] == 'float':
        xt = floatutil.fromRawFloat(ssa_type[1], cval)
        return FloatConstraint.const(ssa_type[1], xt)
    elif ssa_type[0] == 'obj':
        if var.decltype == objtypes.NullTT:
            return ObjectConstraint.constNull(env)
        return ObjectConstraint.fromTops(env, *objtypes.declTypeToActual(env, var.decltype))
    return DUMMY

def fromVariable(env, var):
    if var.const is not None:
        return fromConstant(env, var)
    ssa_type = var.type

    if ssa_type[0] == 'int':
        return IntConstraint.bot(ssa_type[1])    
    elif ssa_type[0] == 'float':
        return FloatConstraint.bot(ssa_type[1])
    elif ssa_type[0] == 'obj':
        if var.decltype is not None:
            if var.decltype == objtypes.NullTT:
                return ObjectConstraint.constNull(env)
            return ObjectConstraint.fromTops(env, *objtypes.declTypeToActual(env, var.decltype))
        else:
            return ObjectConstraint.fromTops(env, [objtypes.ObjectTT], [])
    return DUMMY