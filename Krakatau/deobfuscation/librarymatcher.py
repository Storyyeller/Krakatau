import itertools, collections
import os.path, zipfile
Count = collections.Counter

from . import filterlib
from ..ssa import ssa_types, ssa_ops, ssa_jumps, objtypes
from ..verifier.descriptors import parseMethodDescriptor, parseFieldDescriptor
from ..java import ast, ast2
from .. import classfile, method

# _log = open('urnlog.txt','w')
def log(*ss):
    s = ' '.join(map(str, ss))
    print s
    # _log.write(s+'\n')
    # _log.flush()

def isStandard(s): return s.partition('/')[0] in ('java','javax','sun') or s.startswith('.') #hack for primative tags in vtypes

def matchVTypes(vtype1, vtype2, cbfunc):
    if len(vtype1) != len(vtype2):
        return False
    for t1, t2 in zip(vtype1, vtype2):
        if t1 == t2:
            continue
        if t1.tag != t2.tag or t1.dim != t2.dim:
            return False
        e1, e2 = t1.extra, t2.extra
        assert(e1 != e2)
        assert(e1 is not None and e2 is not None)
        if isStandard(e1) or isStandard(e2) or not cbfunc(e1, e2):
            return False
    return True

class BiDict(object):
    def __init__(self, other=None):
        if other is None:
            self.d = {}
            self.vals = set()
        else:
            self.d = other.d.copy()
            self.vals = other.vals.copy()

    def copy(self): return BiDict(self)

    def add(self, k, v):
        assert(k not in self.d and v is not None)
        self.d[k] = v
        self.vals.add(v)

    def addCheck(self, k, v):
        if k in self.d or v in self.vals:
            return self.d.get(k) == v
        self.add(k, v)
        return True

_ignored_cflags = set(['FINAL', 'SYNTHETIC', 'PRIVATE', 'PROTECTED', 'STATIC', 'PUBLIC'])
_ignored_fflags = set(['SYNTHETIC'])
_ignored_mflags = set(['PUBLIC', 'FINAL', 'SYNTHETIC', 'BRIDGE'])
def getTrip(fm): return fm.class_.name, fm.name, fm.descriptor

def getSkeleton(desc, cdict={}, cvals=set()):
    n = 0
    i = 0
    while 'L' in desc[i:]:
        i = desc.index('L', i)
        i2 = desc.index(';', i+1)
        name = desc[i+1:i2]
        if isStandard(name) or name in cvals:
            i = i2+1
        elif name in cdict:
            desc = desc.replace('L'+name+';', 'L'+cdict[name]+';')
        else:
            desc = desc.replace('L'+name+';', str(n))
            n += 1
    return desc

class MapState(object):
    def __init__(self, other=None):
        if other is None:
            self.c = BiDict()
            self.mf = BiDict()
            self.pending = []
        else:
            self.c = other.c.copy()
            self.mf = other.mf.copy()
            self.pending = other.pending[:]

    def copy(self): return MapState(self)

    def checkClassCB(self, cname1, cname2):
        if self.c.d.get(cname1) == cname2:
            return True
        if isStandard(cname1):
            return cname1 == cname2
        return self.precheckClass(self.getClass(cname1), self.getClass(cname2))

    def precheckField(self, f, f2):
        ft, ft2 = getTrip(f), getTrip(f2)
        if (f.flags ^ f2.flags) - _ignored_fflags:
            return False
        if not self.mf.addCheck(ft, ft2):
            return False
        if not self.precheckClass(f.class_, f2.class_):
            return False
        vt = parseFieldDescriptor(f.descriptor)
        vt2 = parseFieldDescriptor(f2.descriptor)
        return matchVTypes(vt, vt2, self.checkClassCB)

    def precheckClass(self, c, c2):
        assert(not isStandard(c2.name))

        if (c.flags ^ c2.flags) - _ignored_cflags:
            return False
        if not self.c.addCheck(c.name, c2.name):
            return False

        self.pending.append((c, c2))
        return self.checkClassCB(c.supername, c2.supername)

    def precheckMethod(self, m, m2):
        mt, mt2 = getTrip(m), getTrip(m2)
        if (m.flags ^ m2.flags) - _ignored_mflags:
            return False
        if not self.mf.addCheck(mt, mt2):
            return False

        self.pending.append((m, m2))
        return self.precheckClass(m.class_, m2.class_)

    def doClass(self, c1, c2):
        def isUnknown(cn):
            return cn not in self.c.d and cn not in self.c.vals and not isStandard(cn)

        interfaces, interfaces2 = [[c.cpool.getArgsCheck('Class', i) for i in c.interfaces_raw] for c in (c1,c2)]
        interfaces, interfaces2 = [filter(isUnknown, ints) for ints in (interfaces, interfaces2)]
        for i1, i2 in zip(interfaces, interfaces2):
            self.checkClassCB(i1, i2)
            # self.precheckClass(i1, i2)

    def doMethod(self, m1, m2):
        vt1 = sum(parseMethodDescriptor(m1.descriptor), [])
        vt2 = sum(parseMethodDescriptor(m2.descriptor), [])
        matchVTypes(vt1, vt2, self.checkClassCB)

    def pumpQueue(self):
        while self.pending:
            p1, p2 = self.pending.pop()
            if isinstance(p1, classfile.ClassFile):
                self.doClass(p1, p2)
            else:
                self.doMethod(p1, p2)

    def getPart(self, t, isfield):
        queue = [t[0]]
        hits = []
        while not hits:
            c = self.getClass(queue.pop(0))
            if c.supername != 'java/lang/Object':
                queue.insert(0, c.supername)
            queue += [c.cpool.getArgsCheck('Class', i) for i in c.interfaces_raw]
            hits = [f for f in (c.fields if isfield else c.methods) if f.name == t[1] and f.descriptor == t[2]]

        if '<' in t[1]:
            assert(c.name == t[0])
        return hits[0]

    def getField(self, t): return self.getPart(t, True)
    def getMethod(self, t): return self.getPart(t, False)

    def filterBySkeleton(self, mycan, cans):
        cdict, cvals = self.c.d, self.c.vals
        mysk = getSkeleton(mycan[-1], cdict, cvals)
        return [t for t in cans if t not in self.mf.vals and getSkeleton(t[-1], cdict, cvals) == mysk]

    def doMethodFullSig(self, sig1, sig2):
        m1, m2 = sig1.m, sig2.m
        self.pending.append((m1, m2))
        self.pumpQueue()

        def findMatches(ts1, ts2):
            ts1 = [t for t in ts1 if t not in self.mf.d and not isStandard(t[0])]
            ts2 = [t for t in ts2 if t not in self.mf.vals and not isStandard(t[0])]
            while ts1:
                mycan = ts1.pop()
                if mycan in self.mf.d:
                    continue
                cans = self.filterBySkeleton(mycan, ts2)
                if len(cans) == 1:
                    yield mycan, cans[0]

        hits = 0
        for op in ('putfield','putstatic','getfield','getstatic'):
            ts1, ts2 = sig1.fields[op], sig2.fields[op]
            for t1, t2 in findMatches(ts1, ts2):
                f1, f2 = self.getField(t1), self.getField(t2)
                if not isStandard(f1.class_.name):
                    self.precheckField(f1, f2)
                hits += 1
        for op in ('invokestatic', 'invokevirtual', 'invokespecial', 'invokeinterface', 'invokeinit'):
            ts1, ts2 = sig1.methods[op], sig2.methods[op]
            for t1, t2 in findMatches(ts1, ts2):
                f1, f2 = self.getMethod(t1), self.getMethod(t2)
                if not isStandard(f1.class_.name):
                    self.precheckMethod(f1, f2)
                hits += 1
        print hits, 'hits from internal propagation in ', getTrip(m1)
        self.pumpQueue()

    def doClassContents(self, info, c):
        assert(c.name in self.c.d)
        c2 = self.getClass(self.c.d[c.name])
        for m in info.oMethods():
            if getTrip(m) in self.mf.d:
                continue

            cans = self.filterBySkeleton(getTrip(m), map(getTrip, c2.methods))
            if len(cans) == 1:
                self.precheckMethod(m, self.getMethod(cans[0]))

        for m in info.oFields():
            if getTrip(m) in self.mf.d:
                continue

            cans = self.filterBySkeleton(getTrip(m), map(getTrip, c2.fields))
            if len(cans) == 1:
                self.precheckField(m, self.getField(cans[0]))
        self.pumpQueue()

    #################################################################
    #used for AST printing
    def visit(self, obj):
        return obj.print_(self, self.visit)
    def className(self, name): return self.c.d.get(name, name)
    def methodName(self, *args): #class, name, desc
        return self.mf.d.get(args, args)[1]
    fieldName = methodName


class MethodSignature(object):
    def __init__(self, m):
        self.m = m
        self.strings = set()
        self.fields = collections.defaultdict(set)
        self.methods = collections.defaultdict(set)

def matchMethSigs(sig1, sig2):
    fail = False, 0
    m, strings1 = sig1.m, sig1.strings
    m2, strings2 = sig2.m, sig2.strings

    if (m.flags ^ m2.flags) - _ignored_mflags:
        return fail
    if '<' in (m.name + m2.name) and m.name != m2.name:
        return fail
    if m.descriptor.count(';') != m2.descriptor.count(';'):
        return fail
    # if m.descriptor.count('[') != m2.descriptor.count('['):

    if (m.code is None) != (m2.code is None):
        return fail
    if strings1 != strings2:
        return fail
    if getSkeleton(m.descriptor) != getSkeleton(m2.descriptor):
        return fail

    score = m.descriptor.count('[')//3
    score += sum(1+len(x)//20 for x in strings2)
    score -= len((m.flags ^ m2.flags))
    return (score >= 0), score

def getMethodSignature(c, m):
    sig = MethodSignature(m)
    if m.code is not None:
        pool = c.cpool
        code = zip(*sorted(m.code.bytecode.items()))[1]
        for instr in code:
            if instr[0] == 'ldc' and instr[2] == 1:
                if pool.getType(instr[1]) == 'String':
                    sig.strings.add(pool.getArgs(instr[1])[0])
            elif instr[0] in ('putfield','putstatic','getfield','getstatic'):
                sig.fields[instr[0]].add(pool.getArgs(instr[1]))
            elif instr[0] in ('invokestatic', 'invokevirtual', 'invokespecial', 'invokeinterface', 'invokeinit'):
                sig.methods[instr[0]].add(pool.getArgs(instr[1]))
    return sig

def getMethodSignature_ic(info, m):
    sig = MethodSignature(m)
    if m.code is not None:
        graph = info.graphs[m]
        for block in graph.blocks:
            for var, uc in block.unaryConstraints.items():
                if var.origin is not None or var.const is None or var.type != ssa_types.SSA_OBJECT:
                    continue
                if not uc.null:
                    sig.strings.add(var.const)
            for op in block.lines:
                if isinstance(op, ssa_ops.FieldAccess):
                    data = op.target, op.name, op.desc
                    sig.fields[op.instruction[0]].add(data)
                elif isinstance(op, ssa_ops.Invoke):
                    data = op.target, op.name, op.desc
                    sig.methods[op.instruction[0]].add(data)
    return sig

def doJar(rdict, e, infos, jarname):
    with zipfile.ZipFile(jarname, 'r') as archive:
        targets = [name[:-6] for name in archive.namelist() if name.endswith('.class')]
    # targets = [n for n in targets if not isStandard(n)]
    icnames = [k for k in infos if k not in rdict.c.d]
    assert(icnames)

    e.addToPath(jarname)

    method_signatures = {}
    with e:
        for target in targets:
            c = e.getClass(target)
            for m in c.methods:
                method_signatures[m] = getMethodSignature(c, m)
            del e.classes[target]
    print len(method_signatures), 'signatures collected'

    j_mmatches = collections.defaultdict(dict)
    i_mmatches = collections.defaultdict(dict)

    for i, cname in enumerate(icnames):
        for m in infos[cname].oMethods():
            sig = getMethodSignature_ic(infos[cname], m)
            for m2, sig2 in method_signatures.items():
                match, score = matchMethSigs(sig, sig2)
                if match:
                    j_mmatches[m2][m] = score
                    i_mmatches[m][m2] = score
        if not (i+1)%200:
            print i+1, 'classes processed'

    unique_is = [(m, v.keys()[0]) for m,v in i_mmatches.items() if len(v) == 1]
    unique_matches = [(m, m2) for m, m2 in unique_is if len(j_mmatches[m2]) == 1]

    best_matches = sorted(unique_matches, key=lambda (m,m2):-i_mmatches[m][m2])
    with e:
        rdict.getClass = e.getClass

        for m, m2 in best_matches:
            if i_mmatches[m][m2] >= 3:
                rdict.precheckMethod(m, m2)
        rdict.pumpQueue()

        for m, m2 in best_matches:
            log('{0[0]}.{0[1]} {0[2]} -> {1[0]}.{1[1]} {1[2]}\tscore: {2}'.format(getTrip(m), getTrip(m2), i_mmatches[m][m2]))
            temp = rdict.copy()
            temp.getClass = e.getClass
            # if rdict.precheckMethod(m, m2):
            if temp.precheckMethod(m, m2):
                rdict = temp
                sig1 = getMethodSignature_ic(infos[m.class_.name], m)
                sig2 = method_signatures[m2]
                rdict.doMethodFullSig(sig1, sig2)

                c = m.class_
                rdict.doClassContents(infos[c.name], c)
            else:
                print '... failed!'

    print 'Cleaning classes', len(e.classes)
    for target in targets:
        if target in e.classes:
            del e.classes[target]
    return rdict

def chooseNames(e, infos):
    r = MapState()
    jars = []

    for jarname in jars:
        old = r.copy()
        r = doJar(r, e, infos, jarname)

        log(len(r.c.d)-len(old.c.d), "classes matched to ", jarname)
        log(len(r.mf.d)-len(old.mf.d), "fields or methods matched to ", jarname)
        newcs = set(r.c.d) - set(old.c.d)
        for c in newcs:
            log('\t{} -> {}'.format(c, r.c.d[c]))

    log(":::", len(r.c.d), "total classes matched with libraries out of", len(infos))
    log(":::", len(r.mf.d), "fields or methods matched with libraries out of", len(infos))
    return r

def create(**kwargs):
    return chooseNames