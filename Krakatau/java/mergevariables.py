from collections import defaultdict as ddict
import itertools

from . import ast
from ..ssa import objtypes

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
def copySetDict(d):
    return {k:v.copy() for k,v in d.items()}

class RevocationData(object):
    def __init__(self, eqpairs=None, revokes=None):
        # eqpairs: set(v1,v2) - the pairs of variables known to be equal at this point
        # revokes: v1 -> set(v2) - for each v1, the set of varaibles v2 such that a
        #   use of v1 at this point will make v1 and v2 incompatible

        # this represents the intersection of such information along all code paths
        # reaching this point. The empty data (i.e. no paths intersected yet)
        # is represented by None, None

        # v,v in eqpairs if v defined on every path to this point
        # v is a key in revokes if v is defined on any path to this point
        self.eqpairs = eqpairs.copy() if eqpairs is not None else None
        self.revokes = copySetDict(revokes) if revokes is not None else None

    def initialize(self, initvars): #initialize entry point data with method parameters
        assert(self.eqpairs is None and self.revokes is None)
        self.eqpairs = set()
        self.revokes = {}
        for var in initvars:
            self.addvar(var)

    def addvar(self, var): #also called to add a caught exception var
        self.eqpairs.add((var,var))
        self.revokes.setdefault(var, set())

    def _clobberVal(self, var): #v = expr (where expr isn't another var)
        self.eqpairs = set(t for t in self.eqpairs if var not in t)
        self.eqpairs.add((var,var))

    def _assignVal(self, var1, var2): #v1 = v2
        if (var1, var2) in self.eqpairs:
            return

        self._clobberVal(var1) #Important! var1 is no longer equal to anything it was equal to before
        others = [y for x,y in self.eqpairs if x == var2] + [var2]
        for y in others: #set var1 equal to anything that var2 is equal to
            self.eqpairs.add((var1, y))
            self.eqpairs.add((y, var1))

    def _assignRevokes(self, var): #update revoke sets after a new assignment
        for v2 in self.revokes:
            if (var, v2) not in self.eqpairs:
                self.revokes[v2].add(var)
        self.revokes[var] = set()

    def handleAssign(self, var1, var2=None):
        if var2 is None:
            self._clobberVal(var1)
        else:
            self._assignVal(var1, var2)
        self._assignRevokes(var1)

    def merge_update(self, other):
        if other.eqpairs is None:
            return
        if self.eqpairs is None:
            self.eqpairs = other.eqpairs.copy()
            self.revokes = copySetDict(other.revokes)
        else:
            self.eqpairs &= other.eqpairs
            for k,v in other.revokes.items():
                self.revokes[k] = v | self.revokes.get(k, set())

    def copy(self): return RevocationData(self.eqpairs, self.revokes)

    def __eq__(self, other): return self.eqpairs == other.eqpairs and self.revokes == other.revokes
    def __ne__(self, other): return not self == other
    def __hash__(self): raise TypeError('unhashable type')

# The basic block in our temporary CFG
# instead of code, it merely contains a list of defs and uses
# This is an extended basic block, i.e. it only terminates in a normal jump(s).
# exceptions can be thrown from various points within the block
class DUBlock(object):
    def __init__(self, key):
        self.key = key
        self.caught_excepts = ()
        self.lines = []     # 3 types of lines: ('use', var), ('def', (var, var2_opt)), or ('canthrow', None)

        self.inp = RevocationData()
        self.n_out = RevocationData()
        self.e_out = RevocationData()
        self.e_successors = []
        self.n_successors = []
        self.dirty = True

def varOrNone(expr):
    return expr if isinstance(expr, ast.Local) else None

def canThrow(expr):
    if isinstance(expr, (ast.ArrayAccess, ast.ArrayCreation, ast.Cast, ast.ClassInstanceCreation, ast.FieldAccess, ast.MethodInvocation)):
        return True
    if isinstance(expr, ast.BinaryInfix) and expr.opstr in ('/','%'): #check for possible division by 0
        return expr.dtype not in (objtypes.FloatTT, objtypes.DoubleTT)
    return False

def visitExpr(expr, lines):
    if expr is None:
        return
    if isinstance(expr, ast.Local):
        lines.append(('use', expr))

    if isinstance(expr, ast.Assignment):
        lhs, rhs = map(varOrNone, expr.params)

        #with assignment we need to only visit LHS if it isn't a local in order to avoid spurious uses
        #also, we need to visit RHS before generating the def
        if lhs is None:
            visitExpr(expr.params[0], lines)
        visitExpr(expr.params[1], lines)
        if lhs is not None:
            lines.append(('def', (lhs, rhs)))
    else:
        for param in expr.params:
            visitExpr(param, lines)

    if canThrow(expr):
        lines.append(('canthrow', None))

class DUGraph(object):
    def __init__(self):
        self.blocks = []
        self.nsuc_keys = ddict(set)
        self.esuc_keys = ddict(set)

    def makeBlock(self, key):
        b = DUBlock(key)
        self.blocks.append(b)
        return b

    def finishBlock(self, block, catch_stack, jumps):
        if block is None:
            return
        assert(block not in self.nsuc_keys)
        if ('canthrow', None) in block.lines:
            self.esuc_keys[block] = set(catch_stack)
        self.nsuc_keys[block] = set(jumps)

    def _vsEnsureBlock(self, block, next_key, caught_excepts):
        if block is None:
            block = self.makeBlock(next_key)
            block.caught_excepts = caught_excepts
        return block, None, ()

    def visitScope(self, scope, catch_stack, caught_excepts=()):
        #catch_stack is copy on modify

        #One bit of complexity is that a scope may have the same break and continue key
        #when it contains no statements.
        #Such blocks will become selfloops in the resulting CFG. They're harmless
        #unless they define a caught var, since that will confuse the variable domination stuff
        #nevertheless, we try to avoid all such blocks, thus a complicated scheme of
        #generating the blocks here lazily so that we can be sure they have some actual content
        #There is also a step to try to remove such blocks in finish()

        block, next_key = None, scope.continueKey  #create first block lazily
        abrupt_exit = False

        for stmt in scope.statements:
            assert(not abrupt_exit)
            if isinstance(stmt, (ast.ExpressionStatement, ast.ThrowStatement, ast.ReturnStatement)):
                block, next_key, caught_excepts = self._vsEnsureBlock(block, next_key, caught_excepts)

                visitExpr(stmt.expr, block.lines)
                if isinstance(stmt, ast.ThrowStatement):
                    block.lines.append(('canthrow', None))
                abrupt_exit = isinstance(stmt, (ast.ThrowStatement, ast.ReturnStatement))
                continue

            #compound statements
            assert(stmt.continueKey is not None)
            if isinstance(stmt, (ast.IfStatement, ast.SwitchStatement)):
                block, next_key, caught_excepts = self._vsEnsureBlock(block, next_key, caught_excepts)
                visitExpr(stmt.expr, block.lines)
                jumps = [sub.continueKey for sub in stmt.getScopes()]

                if isinstance(stmt, ast.SwitchStatement):
                    ft = not stmt.hasDefault()
                else:
                    ft = len(jumps) == 1
                if ft:
                    jumps.append(stmt.breakKey)

                assert(block is not None)

                self.finishBlock(block, catch_stack, jumps)
                for sub in stmt.getScopes():
                    self.visitScope(sub, catch_stack, caught_excepts)
            elif isinstance(stmt, ast.WhileStatement):
                assert(stmt.expr == ast.Literal.TRUE)
                self.finishBlock(block, catch_stack, [stmt.continueKey])
                self.visitScope(stmt.getScopes()[0], catch_stack)
            elif isinstance(stmt, ast.TryStatement):
                self.finishBlock(block, catch_stack, [stmt.continueKey])

                new_stack = catch_stack[:]
                new_stack += [catchb.continueKey for cdecl, catchb in reversed(stmt.pairs)]
                self.visitScope(stmt.tryb, new_stack, caught_excepts)
                for cdecl, catchb in stmt.pairs:
                    self.visitScope(catchb, catch_stack, caught_excepts + (cdecl.local,))
            else:
                assert(isinstance(stmt, ast.StatementBlock))
                self.finishBlock(block, catch_stack, [stmt.continueKey])
                self.visitScope(stmt.getScopes()[0], catch_stack, caught_excepts)

            block, next_key, caught_excepts = None, stmt.breakKey, ()
            if stmt.breakKey is None:
                abrupt_exit = True

        jumps = []
        if scope.jumpKey is not None:
            jumps.append(scope.jumpKey)
        if not abrupt_exit:
            block, next_key, caught_excepts = self._vsEnsureBlock(block, next_key, caught_excepts)
            self.finishBlock(block, catch_stack, jumps)
        else:
            assert(scope.jumpKey is None)

    def finish(self, method_params):
        #prune useless blocks which have no content and merely jump to themselves
        #many of these are generated as a side effect of the way we generate the CFG and the way the continue/break keys work
        self.blocks = [b for b in self.blocks if b.lines or b.caught_excepts or self.nsuc_keys[b] != set([b.key])]

        entry = self.blocks[0] #entry point should always be first block generated
        entry.inp.initialize(method_params)

        allkeys = set(b.key for b in self.blocks)
        for block in self.blocks:
            assert(self.esuc_keys[block] | self.nsuc_keys[block] <= allkeys)
            for b2 in self.blocks:
                if b2.key in self.esuc_keys[block]:
                    block.e_successors.append(b2)
                if b2.key in self.nsuc_keys[block]:
                    block.n_successors.append(b2)

def getLivenessConflicts(root, parameters):
    #first, create CFG from the Java AST
    graph = DUGraph()
    graph.visitScope(root, [])
    graph.finish(parameters)
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