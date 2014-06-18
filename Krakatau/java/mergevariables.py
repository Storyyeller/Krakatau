from collections import defaultdict as ddict
import itertools

from . import ast
from ..ssa import objtypes
from .cfg import DUGraph

# Variables x and y can safely be merged when it is true that for any use of y (respectively x)
# that sees definition y0 of y, either there are no intervening definitions of x, or x was known
# to be equal to y *at the point of its most recent definition*
# Given this info, we greedily merge related variables, that is, those where one is assigned to the other
# to calculate which variables can be merged, we first have to build a CFG from the Java AST again

class VarInfo(object):
    __slots__ = "key", "compat", "defs", "extracount"
    def __init__(self, key):
        self.key = key
        self.compat = set()
        self.defs = set()
        self.extracount = 0

    def priority(self):
        return (len(self.defs) + self.extracount), self.key

class VarMergeInfo(object):
    def __init__(self):
        self.info = {}
        self.final, self.unmergeable, self.external = set(), set(), set()

    def addvar(self, var):
        self.info.setdefault(var, VarInfo(len(self.info)))

    def addassign(self, var1, var2):
        self.addvar(var1)
        if var2 is None: #assigning a literal or complex expr, rather than another var
            self.info[var1].extracount += 1
        else:
            self.info[var1].defs.add(var2)

    def douse(self, var, eqdata):
        assert((var,var) in eqdata.eqpairs)
        old = self.info[var].compat
        new = old - eqdata.revokes[var]

        self.info[var].compat = new
        for var2 in old-new:
            self.info[var2].compat.remove(var)

    def domerge(self, replacements):
        final, unmergeable, external = self.final, self.unmergeable, self.external
        d = self.info
        todo = set(d)
        while todo:
            cur = min(todo, key=lambda v:d[v].priority())
            todo.remove(cur)
            if (cur in external):
                continue

            candidates = [v for v in (d[cur].defs & d[cur].compat) if not (v in unmergeable)]
            if len(d[cur].defs) > 1 or d[cur].extracount > 0:
                candidates = [v for v in candidates if not (v in final)]
            candidates = [v for v in candidates if v.dtype == cur.dtype]

            if not candidates:
                continue
            parent = min(candidates, key=lambda v:d[v].key)
            assert(cur != parent)

            replacements[cur] = parent
            newcompat = d[cur].compat & d[parent].compat
            newcompat.remove(cur)
            for other in (d[cur].compat | d[parent].compat):
                d[other].compat.discard(cur)
                d[other].compat.discard(parent)
            for other in newcompat:
                d[other].compat.add(parent)

            for info in d.values():
                if cur in info.defs:
                    info.defs.remove(cur)
                    info.defs.add(parent)

            d[parent].defs |= d[cur].defs
            d[parent].compat = newcompat
            d[parent].defs.remove(parent)
            todo.add(parent)
            del d[cur]

###############################################################################

def getLivenessConflicts(root, parameters):
    #first, create CFG from the Java AST
    graph = DUGraph()
    graph.makeCFG(root, parameters)
    blocks = graph.blocks

    mergeinfo = VarMergeInfo()
    #get variables and assignment data
    for block in blocks:
        for line_t, data in block.lines:
            if line_t == 'use':
                mergeinfo.addvar(data)
            elif line_t == 'def':
                mergeinfo.addassign(data[0], data[1])
        for caught in block.caught_excepts:
            mergeinfo.addvar(caught)
            mergeinfo.external.add(caught)
            mergeinfo.unmergeable.add(caught)

    universe = set(mergeinfo.info)
    for info in mergeinfo.info.values():
        info.compat = universe.copy()

    #now iterate to find all mergeability conflicts
    stack = blocks[:1]
    while stack:
        block = stack.pop()
        if not block.dirty:
            continue
        block.dirty = False

        cur = block.inp.copy()
        for caught in block.caught_excepts:
            cur.addvar(caught)

        for line_t, data in block.lines:
            if line_t == 'use':
                mergeinfo.douse(data, cur)
            elif line_t == 'def':
                cur.handleAssign(data[0], data[1])
            else: #canthrow
                block.e_out.merge_update(cur)
        block.n_out.merge_update(cur)

        for out, successors in [(block.n_out, block.n_successors), (block.e_out, block.e_successors)]:
            for suc in successors:
                temp = suc.inp.copy()
                suc.inp.merge_update(out)
                if suc.inp != temp:
                    suc.dirty = True
                    stack.append(suc)
    return mergeinfo

###############################################################################
def mergeVariables(root, isstatic, parameters):
    mergeinfo = getLivenessConflicts(root, parameters)
    for var in parameters:
        mergeinfo.addvar(var)
        mergeinfo.external.add(var)
    if not isstatic:
        mergeinfo.final.add(parameters[0])

    replace = {}
    mergeinfo.domerge(replace)

    #flatten replacement chains
    for v in replace.keys():
        while replace[v] in replace:
            replace[v] = replace[replace[v]]
    return replace