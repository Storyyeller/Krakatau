import collections, itertools
from . import objtypes
from .mixin import ValueType

class CatchSetManager(object):
    def __init__(self, env, chpairs, attributes=None):
        if attributes is not None:
            self.env, self.sets, self.mask = attributes
        else:
            self.env = env
            self.sets = collections.OrderedDict() #make this ordered since OnException relies on it

            sofar = empty = ExceptionSet.EMPTY
            for catchtype, handler in chpairs:
                old = self.sets.get(handler, empty)
                new = ExceptionSet.fromTops(env, catchtype)

                self.sets[handler] = old | (new - sofar)
                sofar = sofar | new
            self.mask = sofar #temp hack
            self.pruneKeys()

    def newMask(self, mask):
        for k in self.sets:
            self.sets[k] &= mask 
        self.mask &= mask

    def pruneKeys(self):
        for handler, catchset in list(self.sets.items()):
            if not catchset:
                del self.sets[handler]

    def copy(self):
        return CatchSetManager(0,0,(self.env, self.sets.copy(), self.mask))

    def replaceKey(self, old, new):
        assert(old in self.sets and new not in self.sets)
        self.sets[new] = self.sets[old]
        del self.sets[old]

    def replaceKeys(self, replace):
        self.sets = collections.OrderedDict((replace.get(key,key), val) for key, val in self.sets.items())

class ExceptionSet(ValueType):
    def __init__(self, env, pairs): #assumes arguments are in reduced form
        self.env = env
        self.pairs = frozenset([(x,frozenset(y)) for x,y in pairs])
        assert(not pairs or '.null' not in zip(*pairs)[0])
        #We allow env to be None for the empty set so we can construct empty sets easily
        #Any operation resulting in a nonempty set will get its env from the nonempty argument
        assert(self.env or self.empty()) 

    @staticmethod #factory
    def fromTops(env, *tops):
        return ExceptionSet(env, [(x, frozenset()) for x in tops])

    def _key(self): return self.pairs
    def empty(self): return not self.pairs
    def __nonzero__(self): return bool(self.pairs)

    def getSingleTType(self):
        #comSuper doesn't care about order so we can freely pass in nondeterministic order
        return objtypes.commonSupertype(self.env, [(top,0) for (top,holes) in self.pairs])

    def __sub__(self, other):
        assert(type(self) == type(other))
        if self.empty() or other.empty():
            return self
        if self == other:
            return ExceptionSet.EMPTY

        subtest = self.env.isSubclass
        pairs = self.pairs

        for pair2 in other.pairs:
            #Warning, due to a bug in Python, TypeErrors raised inside the gen expr will give an incorect error message
            #TypeError: type object argument after * must be a sequence, not generator
            pairs = itertools.chain(*(ExceptionSet.diffPair(subtest, pair1, pair2) for pair1 in pairs))
        return ExceptionSet.reduce(self.env, pairs)    

    def __or__(self, other):
        assert(type(self) == type(other))        
        if not other:
            return self 
        if not self:
            return other
        return ExceptionSet.reduce(self.env, self.pairs | other.pairs)

    def __and__(self, other):
        assert(type(self) == type(other))    

        # temp = self-other
        # if ('java/lang/NullPointerException',frozenset()) in other.pairs:
        #     import pdb;pdb.set_trace()
        # temp2 = self-temp

        new = self - (self - other)
        return new

    def isdisjoint(self, other):
        assert(type(self) == type(other))

        #quick test on tops
        if not set(zip(*self.pairs)[0]).isdisjoint(zip(*other.pairs)[0]):
            return False
        return (self-other) == self

    def __str__(self): return 'ES' + str(map(list, self.pairs))
    __repr__ = __str__

    @staticmethod
    def diffPair(subtest, pair1, pair2): #subtract pair2 from pair1. Returns a list of new pairs
        t1, holes1 = pair1
        t2, holes2 = pair2
        if subtest(t2,t1):
            fs = frozenset()
            newpairs = [(h2,fs) for h2 in holes2 if subtest(h2, t1) and not any(subtest(h2,h1) for h1 in holes1)]
            if t2 != t1: #t2 is a stict subset of t1
                newpairs.append((t1,list(holes1) + [t2])) 
            return newpairs
        elif subtest(t1,t2):
            if any(subtest(t1, h) for h in holes2):
                return pair1,
            else:
                newpairs = []
                for h in holes2:
                    if subtest(h, t1):
                        newtop = h
                        newholes = [h2 for h2 in holes1 if h2 != h and subtest(h2, h)]
                        newpairs.append((newtop, newholes))
                return newpairs
        else:
            return pair1,

    @staticmethod
    def mergePair(subtest, pair1, pair2): #merge pair2 into pair1 and return the union
        t1, holes1 = pair1
        t2, holes2 = pair2
        assert(subtest(t2,t1))

        #TODO - this can probably be made more efficient
        holes = set(h for h in holes1 if not subtest(h, t2))
        for h1, h2 in itertools.product(holes1, holes2):
            if subtest(h2, h1):
                holes.add(h1)
            elif subtest(h1, h2):
                holes.add(h2)
        holes = ExceptionSet.reduceHoles(subtest, holes)
        return t1, holes

    @staticmethod
    def reduceHoles(subtest, holes):
        newholes = []
        for hole in holes:
            for ehole in newholes:
                if subtest(hole, ehole):
                    break
            else:
                newholes = [hole] + [h for h in newholes if not subtest(h, hole)]
        return newholes

    @staticmethod
    def reduce(env, pairs):
        subtest = env.isSubclass
        pairs = [pair for pair in pairs if pair[0] not in pair[1]] #remove all degenerate pairs
        newpairs = []
        while pairs:
            top, holes = pair = pairs.pop()

            #look for an existing top to merge into
            for epair in newpairs[:]: 
                etop, eholes = epair
                #new pair can be merged into existing pair
                if subtest(top, etop) and not any(subtest(top, ehole) for ehole in eholes):
                    new = ExceptionSet.mergePair(subtest, epair, pair)
                    newpairs, pairs = [new], [p for p in newpairs if p is not epair] + pairs
                    break
                #existing pair can be merged into new pair
                elif subtest(etop, top) and not any(subtest(etop, hole) for hole in holes):
                    new = ExceptionSet.mergePair(subtest, pair, epair)
                    newpairs, pairs = [new], [p for p in newpairs if p is not epair] + pairs
                    break                
            #pair is incomparable to all existing pairs
            else:
                holes = ExceptionSet.reduceHoles(subtest, holes)
                newpairs.append((top,holes))
        return ExceptionSet(env, newpairs)

ExceptionSet.EMPTY = ExceptionSet(None, [])