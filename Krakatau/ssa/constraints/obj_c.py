import itertools
from ..mixin import ValueType
from .int_c import IntConstraint
from .. import objtypes

array_supers = 'java/lang/Object','java/lang/Cloneable','java/io/Serializable'
obj_fset = frozenset([objtypes.ObjectTT])

def isAnySubtype(env, x, seq):
    return any(objtypes.isSubtype(env,x,y) for y in seq)

class TypeConstraint(ValueType):
    __slots__ = "env supers exact isBot".split()
    def __init__(self, env, supers, exact):
        self.env, self.supers, self.exact = env, frozenset(supers), frozenset(exact)
        self.isBot = objtypes.ObjectTT in supers

        temp = self.supers | self.exact
        assert(not temp or min(zip(*temp)[1]) >= 0)
        assert(objtypes.NullTT not in temp)
        assert(not any(tt[0].startswith('.') for tt in supers))

    @staticmethod
    def fromTops(*args):
        return TypeConstraint(*args)

    def _key(self): return self.supers, self.exact
    def __nonzero__(self): return bool(self.supers or self.exact)

    def getSingleTType(self):
        #comSuper doesn't care about order so we can freely pass in nondeterministic order
        return objtypes.commonSupertype(self.env, list(self.supers) + list(self.exact))

    def isBoolOrByteArray(self):
        if self.supers or len(self.exact) != 2:
            return False
        bases, dims = zip(*self.exact)
        return dims[0] == dims[1] and sorted(bases) == [objtypes.BoolTT[0], objtypes.ByteTT[0]]

    @staticmethod
    def reduce(env, supers, exact):
        newsupers = []
        for x in supers:
            if not isAnySubtype(env, x, newsupers):
                newsupers = [y for y in newsupers if not objtypes.isSubtype(env, y, x)]
                newsupers.append(x)

        newexact = [x for x in exact if not isAnySubtype(env, x, newsupers)]
        return TypeConstraint(env, newsupers, newexact)

    def join(*cons):
        assert(len(set(map(type, cons))) == 1)
        env = cons[0].env

        #optimize for the common case of joining with itself or with bot
        cons = set(c for c in cons if not c.isBot)
        if not cons:
            return TypeConstraint(env, obj_fset, [])
        elif len(cons) == 1:
            return cons.pop()
        assert(len(cons) == 2) #joining more than 2 not currently supported

        supers_l, exact_l = zip(*(c._key() for c in cons))

        newsupers = set()
        for t1,t2 in itertools.product(*supers_l):
            if objtypes.isSubtype(env, t1, t2):
                newsupers.add(t1)
            elif objtypes.isSubtype(env, t2, t1):
                newsupers.add(t2)
            else: #TODO: need to add special handling for interfaces here
                pass

        newexact = frozenset.union(*exact_l)
        for c in cons:
            newexact = [x for x in newexact if x in c.exact or isAnySubtype(env, x, c.supers)]
        return TypeConstraint.reduce(env, newsupers, newexact)

    def meet(*cons):
        supers = frozenset.union(*(c.supers for c in cons))
        exact = frozenset.union(*(c.exact for c in cons))
        return TypeConstraint.reduce(cons[0].env, supers, exact)

class ObjectConstraint(ValueType):
    __slots__ = "null types arrlen isBot".split()
    def __init__(self, null, types):
        self.null, self.types = null, types
        self.isBot = null and types.isBot

    @staticmethod
    def constNull(env):
        return ObjectConstraint(True, TypeConstraint(env, [], []))

    @staticmethod
    def fromTops(env, supers, exact, nonnull=False):
        types = TypeConstraint(env, supers, exact)
        if nonnull and not types:
            return None
        return ObjectConstraint(not nonnull, types)

    def _key(self): return self.null, self.types

    def isConstNull(self): return self.null and not self.types

    def getSingleTType(self):
        return self.types.getSingleTType() if self.types else objtypes.NullTT

    def join(*cons):
        null = all(c.null for c in cons)
        types = TypeConstraint.join(*(c.types for c in cons))
        if not null and not types:
            return None

        res = ObjectConstraint(null, types)
        return cons[0] if cons[0] == res else res

    def meet(*cons):
        null = any(c.null for c in cons)
        types = TypeConstraint.meet(*(c.types for c in cons))
        return  ObjectConstraint(null, types)
