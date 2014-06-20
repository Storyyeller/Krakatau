from collections import defaultdict as ddict
import itertools, heapq

from . import ast
from ..ssa import objtypes
from .cfg import DUGraph

# Variables x and y can safely be merged when it is true that for any use of y (respectively x)
# that sees definition y0 of y, either there are no intervening definitions of x, or x was known
# to be equal to y *at the point of its most recent definition*
# Given this info, we greedily merge related variables, that is, those where one is assigned to the other
# to calculate which variables can be merged, we first have to build a CFG from the Java AST again

class VarInfo(object):
    __slots__ = "key", "defs", "rdefs", "extracount"
    def __init__(self, key):
        self.key = key
        self.defs = set()
        self.rdefs = set()
        self.extracount = 0

    def priority(self):
        return (len(self.defs) + self.extracount), self.key

class EqualityData(object):
    def __init__(self, d=None):
        # Equal values point to a representative object instance. Singletons are not represented at all for efficiency
        # None represents the top value (i.e. this point has not been visited yet)
        self.d = d.copy() if d is not None else None

    def initialize(self, initvars): #initialize entry point data with method parameters
        assert(self.d is None)
        self.d = {}

    def addvar(self, var): #also called to add a caught exception var
        pass

    def handleAssign(self, var1, var2=None):
        if var1 == var2:
            return
        if var2 is None:
            if var1 in self.d:
                del self.d[var1]
        else:
            self.d[var1] = self.d.setdefault(var2, object())
            assert(self.iseq(var1, var2))

    def iseq(self, var1, var2):
        assert(var1 != var2)
        return var1 in self.d and var2 in self.d and self.d[var1] is self.d[var2]

    def merge_update(self, other):
        if other.d is None:
            return
        elif self.d is None:
            self.d = other.d.copy()
        else:
            d1, d2 = self.d, other.d
            new = {}
            todo = list(set(d1) & set(d2))
            while todo:
                cur = todo.pop()
                matches = [k for k in todo if d1[k] is d1[cur] and d2[k] is d2[cur]]
                if not matches:
                    continue
                new[cur] = object()
                for k in matches:
                    new[k] = new[cur]
                todo = [k for k in todo if k not in new]
            self.d = new

    def copy(self): return EqualityData(self.d)

    def __eq__(self, other):
        if self.d is None or other.d is None:
            return self.d is other.d
        if self.d == other.d:
            return True
        if set(self.d) != set(other.d):
            return False
        match = {}
        for k in self.d:
            if match.setdefault(self.d[k], other.d[k]) != other.d[k]:
                return False
        return True

    def __ne__(self, other): return not self == other
    def __hash__(self): raise TypeError('unhashable type')

def calcEqualityData(graph, methodparams):
    graph.simplify()
    blocks = graph.blocks
    d = {b:[EqualityData()] for b in blocks}
    # print 'calc eq data', len(blocks)

    d[graph.entry][0].initialize(methodparams)
    stack = [graph.entry]
    dirty = set(blocks)
    # for block in graph.blocks:
    #     print '\nblock', block.key, blocks.index(block), block.caught_excepts
    #     for line in block.lines:
    #         print '\t  ', line
    #     print '\tNS', map(blocks.index, block.n_successors)
    #     print '\tES', map(blocks.index, block.e_successors)

    while stack:
        block = stack.pop()
        if block not in dirty:
            continue
        dirty.remove(block)
        # print blocks.index(block), len(dirty)

        cur = d[block][0].copy()
        e_out = EqualityData()
        del d[block][1:]

        for var in block.caught_excepts:
            cur.addvar(var)

        for line_t, data in block.lines:
            if line_t == 'def':
                cur.handleAssign(*data)
                d[block].append(cur.copy())
            elif line_t == 'canthrow':
                e_out.merge_update(cur)

        for out, successors in [(e_out, block.e_successors), (cur, block.n_successors)]:
            stack += successors
            for suc in successors:
                old = d[suc][0].copy()
                d[suc][0].merge_update(out)
                if old != d[suc][0]:
                    dirty.add(suc)

    for block in blocks:
        assert(d[block][0].d is not None)
    print 'eq data done'
    return d

class VarMergeInfo(object):
    def __init__(self, graph, methodparams, isstatic):
        self.info = {}
        self.final, self.unmergeable, self.external = set(), set(), set()
        self.equality = None #to be calculated later
        self.graph = graph
        self.methodparams = methodparams

        #initialize variables and assignment data
        for var in methodparams:
            self._addvar(var)
        self.external.update(methodparams)
        if not isstatic:
            self.final.add(methodparams[0])

        for block in graph.blocks:
            for line_t, data in block.lines:
                if line_t == 'def':
                    self._addassign(data[0], data[1])
            for caught in block.caught_excepts:
                self._addvar(caught)
                self.external.add(caught)
                self.unmergeable.add(caught)

    #initialization helper funcs
    def _addvar(self, v):
        return self.info.setdefault(v, VarInfo(len(self.info)))

    def _addassign(self, v1, v2):
        info = self._addvar(v1)
        if v2 is not None:
            info.defs.add(v2)
            self._addvar(v2).rdefs.add(v1)
        else:
            info.extracount += 1

    #process helper guncs
    def iseq(self, block, index, v1, v2):
        return self.equality[block][index].iseq(v1, v2)

    def compat(self, v1, v2, doeq):
        blocks = self.graph.blocks
        vok = {b:3 for b in blocks} #use bitmask v1ok = 1<<0, v2ok = 1<<1

        stack = blocks[::-1]
        while stack:
            block = stack.pop()
            cur = vok[block]
            # print 'bi', self.graph.blocks.index(block), cur

            e_out = 3
            defcount = 0
            for line_t, data in block.lines:
                if line_t == 'use':
                    if (data == v1 and not cur & 1) or (data == v2 and not cur & 2):
                        return False
                elif line_t == 'def':
                    defcount += 1

                    if data[0] == v1 and data[1] != v1:
                        cur = 1
                    elif data[0] == v2 and data[1] != v2:
                        cur = 2
                    if doeq and self.iseq(block, defcount, v1, v2):
                        cur = 3
                elif line_t == 'canthrow':
                    e_out &= cur

            for out, successors in [(e_out, block.e_successors), (cur, block.n_successors)]:
                for suc in successors:
                    if vok[suc] & out != vok[suc]:
                        stack.append(suc)
                        vok[suc] &= out
        return True

    def process(self, replace, doeq):
        # print '\nmerge', doeq, len(self.info)
        final, unmergeable, external = self.final, self.unmergeable, self.external
        d = self.info
        work_q = [(info.priority(), var) for var, info in d.items()]
        heapq.heapify(work_q)
        dirty = set(d) - external

        while work_q:
            _, cur = heapq.heappop(work_q)
            if (cur in external) or cur not in dirty:
                continue
            dirty.remove(cur)

            candidate_set = d[cur].defs - unmergeable
            if len(d[cur].defs) > 1 or d[cur].extracount > 0:
                candidate_set = candidate_set - final
            candidates = [v for v in candidate_set if v.dtype == cur.dtype]
            candidates = sorted(candidates, key=lambda v:d[v].key)
            assert(cur not in candidates)

            # print cur
            # print '\tdefs: ', d[cur].defs
            # print '\tcandidates: ', candidates

            #find first candidate that is actually compatible
            for parent in candidates:
                if self.compat(cur, parent, doeq):
                    break
            else:
                continue #no candidates found
            # print '\tparent', parent

            # print cur, '->', parent
            replace[cur] = parent
            self.graph.replace(cur, parent)

            infc, infp = d[cur], d[parent]
            #Be careful, there could be a loop with cur in parent.defs
            infc.defs.remove(parent)
            infc.rdefs.discard(parent)
            infp.rdefs.remove(cur)
            infp.defs.discard(cur)

            for var in d[cur].rdefs:
                d[var].defs.remove(cur)
                d[var].defs.add(parent)
                heapq.heappush(work_q, (d[var].priority(), var))

            for var in d[cur].defs:
                d[var].rdefs.remove(cur)
                d[var].rdefs.add(parent)

            d[parent].defs |= d[cur].defs
            d[parent].rdefs |= d[cur].rdefs
            d[parent].extracount += d[cur].extracount

            del d[cur]
            heapq.heappush(work_q, (d[parent].priority(), parent))
            dirty.add(parent)

    def processMain(self, replace):
        self.process(replace, False)
        self.equality = calcEqualityData(self.graph, self.methodparams)
        self.process(replace, True)

###############################################################################
def mergeVariables(root, isstatic, parameters):
    #first, create CFG from the Java AST
    graph = DUGraph()
    graph.makeCFG(root)
    mergeinfo = VarMergeInfo(graph, parameters, isstatic)

    replace = {}
    mergeinfo.processMain(replace)

    #flatten replacements
    for k in list(replace):
        while replace[k] in replace:
            replace[k] = replace[replace[k]]
    return replace