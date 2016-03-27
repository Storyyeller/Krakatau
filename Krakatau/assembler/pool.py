import collections
import itertools

from .writer import Writer

TAGS = [None, 'Utf8', None, 'Int', 'Float', 'Long', 'Double', 'Class', 'String', 'Field', 'Method', 'InterfaceMethod', 'NameAndType', None, None, 'MethodHandle', 'MethodType', None, 'InvokeDynamic']

class Ref(object):
    def __init__(self, tok, index=None, symbol=None, type=None, refs=None, data=None, isbs=False):
        self.tok = tok
        self.isbs = isbs
        self.index = index
        self.symbol = symbol

        assert type == 'Bootstrap' or type in TAGS
        self.type = type
        self.refs = refs or []
        self.data = data

        self.resolved_index = None

    def israw(self): return self.index is not None
    def issym(self): return self.symbol is not None

    def _deepdata(self, pool, error, depth=0):
        if self.issym():
            return pool.sub(self).getroot(self, error)._deepdata(pool, error, depth)

        if self.israw():
            return 'Raw', self.index

        if depth > 5: # Maximum legitimate depth is 5: ID -> BS -> MH -> F -> NAT -> UTF
            error('Constant pool definitions cannot be nested more than 5 deep.', self.tok)
        return self.type, self.data, tuple(ref._deepdata(pool, error, depth + 1) for ref in self.refs)

    def _resolve(self, pool, error):
        if self.israw():
            return self.index
        if self.issym():
            return pool.sub(self).getroot(self, error).resolve(pool, error)
        return pool.sub(self).resolvedata(self, error, self._deepdata(pool, error))

    def resolve(self, pool, error):
        if self.resolved_index is None:
            self.resolved_index = self._resolve(pool, error)
            assert self.resolved_index is not None
        return self.resolved_index

    def __str__(self):
        prefix = 'bs:' if self.isbs else ''
        if self.israw():
            return '[{}{}]'.format(prefix, self.index)
        elif self.issym():
            return '[{}{}]'.format(prefix, self.symbol)
        parts = [self.type] + self.refs
        if self.data is not None:
            parts.insert(1, self.data)
        return ' '.join(map(str, parts))

def utf(tok, s):
    assert isinstance(s, bytes)
    assert len(s) <= 65535
    return Ref(tok, type='Utf8', data=s)

def single(type, tok, s):
    assert type in 'Class String MethodType'.split()
    return Ref(tok, type=type, refs=[utf(tok, s)])

def nat(name, desc):
    return Ref(name.tok, type='NameAndType', refs=[name, desc])

def primative(type, tok, x):
    assert type in 'Int Long Float Double'.split()
    return Ref(tok, type=type, data=x)

class PoolSub(object):
    def __init__(self, isbs):
        self.isbs = isbs
        self.symdefs = {}
        self.symrootdefs = {}
        self.slots = collections.OrderedDict()
        self.dataToSlot = {}
        self.narrowcounter = itertools.count()
        self.widecounter = itertools.count()

        self.dirtyslotdefs = []
        self.defsfrozen = False

    def adddef(self, lhs, rhs, error):
        assert not self.defsfrozen
        assert lhs.israw() or lhs.issym()
        if lhs.israw():
            if lhs.index in self.slots:
                error('Duplicate raw reference definition', lhs.tok)
            self.slots[lhs.index] = rhs
            self.dirtyslotdefs.append(lhs.index)
            assert rhs.type
            if rhs.type in ('Long', 'Double'):
                if lhs.index + 1 in self.slots:
                    error('Conflicting raw reference definitions', lhs.tok)
                self.slots[lhs.index + 1] = None
        else:
            if lhs.symbol in self.symdefs:
                error('Duplicate symbolic reference definition', lhs.tok)
            self.symdefs[lhs.symbol] = rhs

    def freezedefs(self, pool, error): self.defsfrozen = True

    def _getslot(self, iswide):
        assert self.defsfrozen
        if iswide:
            ind = next(self.widecounter)
            while ind in self.slots or ind + 1 in self.slots:
                ind = next(self.widecounter)
            if ind + 1 >= 0xFFFF:
                return None
        else:
            ind = next(self.narrowcounter)
            while ind in self.slots:
                ind = next(self.narrowcounter)
            if ind >= 0xFFFF:
                return None
        return ind

    def getroot(self, ref, error):
        assert self.defsfrozen and ref.issym()

        try:
            return self.symrootdefs[ref.symbol]
        except KeyError:
            visited = set()
            while ref.issym():
                sym = ref.symbol
                if sym in visited:
                    error('Circular symbolic reference', ref.tok)
                visited.add(sym)

                if sym not in self.symdefs:
                    error('Undefined symbolic reference', ref.tok)
                ref = self.symdefs[sym]

            for sym in visited:
                self.symrootdefs[sym] = ref
            return ref

    def resolvedata(self, ref, error, newdata):
        try:
            return self.dataToSlot[newdata]
        except KeyError:
            iswide = newdata[0] in ('Long', 'Double')
            slot = self._getslot(iswide)
            if slot is None:
                name = 'bootstrap method' if ref.isbs else 'constant pool'
                error('Exhausted {} space'.format(name), ref.tok)

            self.dataToSlot[newdata] = slot
            self.slots[slot] = ref
            self.dirtyslotdefs.append(slot)
            if iswide:
                self.slots[slot + 1] = None
        return slot

    def resolveslotrefs(self, pool, error):
        while len(self.dirtyslotdefs) > 0:
            i = self.dirtyslotdefs.pop()
            for ref in self.slots[i].refs:
                ref.resolve(pool, error)

    def writeconst(self, w, ref, pool, error):
        t = ref.type
        w.u8(TAGS.index(t))
        if t == 'Utf8':
            w.u16(len(ref.data))
            w.writeBytes(ref.data)
        elif t == 'Int' or t == 'Float':
            w.u32(ref.data)
        elif t == 'Long' or t == 'Double':
            w.u64(ref.data)
        elif t == 'MethodHandle':
            w.u8(ref.data)
            w.u16(ref.refs[0].resolve(pool, error))
        else:
            for child in ref.refs:
                w.u16(child.resolve(pool, error))
        return w

    def writebootstrap(self, w, ref, pool, error):
        assert ref.type == 'Bootstrap'
        w.u16(ref.refs[0].resolve(pool, error))
        w.u16(len(ref.refs)-1)
        for child in ref.refs[1:]:
            w.u16(child.resolve(pool, error))
        return w

    def write(self, pool, error):
        self.resolveslotrefs(pool, error)
        self.dirtyslotdefs = None # make sure we don't accidently add entries after size is taken

        size = max(self.slots) + 1 if self.slots else 0
        dummyentry = b'\1\0\0' # empty UTF8
        if self.isbs and self.slots:
            first = next(self.slots.itervalues())
            dummyentry = self.writebootstrap(Writer(), first, pool, error).toBytes()

        w = Writer()
        w.u16(size)
        for i in range(size):
            if i not in self.slots:
                w.writeBytes(dummyentry)
                continue

            v = self.slots[i]
            if v is None:
                continue

            if self.isbs:
                self.writebootstrap(w, v, pool, error)
                if len(w) >= (1<<32):
                    error('Maximum BootstrapMethods length is {} bytes.'.format((1<<32)-1), v.tok)
            else:
                self.writeconst(w, v, pool, error)
        return w

class Pool(object):
    def __init__(self):
        self.cp = PoolSub(False)
        self.bs = PoolSub(True)
        self.cp.slots[0] = None

    def sub(self, ref): return self.bs if ref.isbs else self.cp

    def resolveIDBSRefs(self, error):
        for v in self.cp.slots.values():
            if v is not None and v.type == 'InvokeDynamic':
                v.refs[0].resolve(self, error)

    def write(self, error):
        bsmdata = self.bs.write(self, error)
        cpdata = self.cp.write(self, error)
        return cpdata, bsmdata
