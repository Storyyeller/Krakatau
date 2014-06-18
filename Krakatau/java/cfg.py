from collections import defaultdict as ddict

from . import ast
from ..ssa import objtypes

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

    def canThrow(self): return ('canthrow', None) in self.lines

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

    def makeBlock(self, key, break_dict, caught_except, myexcept_parents):
        block = DUBlock(key)
        self.blocks.append(block)

        for parent in break_dict[block.key]:
            parent.n_successors.append(block)
        del break_dict[block.key]

        assert((myexcept_parents is None) == (caught_except is None))
        if caught_except is not None: #this is the head of a catch block:
            block.caught_excepts = (caught_except,)
            for parent in myexcept_parents:
                parent.e_successors.append(block)
        return block

    def visitScope(self, scope, isloophead, break_dict, catch_stack, caught_except=None, myexcept_parents=None):
        #catch_stack is copy on modify
        head_block = block = self.makeBlock(scope.continueKey, break_dict, caught_except, myexcept_parents)

        for stmt in scope.statements:
            if isinstance(stmt, (ast.ExpressionStatement, ast.ThrowStatement, ast.ReturnStatement)):
                visitExpr(stmt.expr, block.lines)
                if isinstance(stmt, ast.ThrowStatement):
                    block.lines.append(('canthrow', None))
                continue

            #compound statements
            assert(stmt.continueKey is not None)
            if isinstance(stmt, (ast.IfStatement, ast.SwitchStatement)):
                visitExpr(stmt.expr, block.lines)
                jumps = [sub.continueKey for sub in stmt.getScopes()]

                if isinstance(stmt, ast.SwitchStatement):
                    ft = not stmt.hasDefault()
                else:
                    ft = len(jumps) == 1
                if ft:
                    jumps.append(stmt.breakKey)

                for sub in stmt.getScopes():
                    break_dict[sub.continueKey].append(block)
                    self.visitScope(sub, False, break_dict, catch_stack)

            elif isinstance(stmt, ast.WhileStatement):
                assert(stmt.expr == ast.Literal.TRUE)
                assert(stmt.continueKey == stmt.getScopes()[0].continueKey)
                break_dict[stmt.continueKey].append(block)
                self.visitScope(stmt.getScopes()[0], True, break_dict, catch_stack)

            elif isinstance(stmt, ast.TryStatement):
                new_stack = catch_stack + [[] for _ in stmt.pairs]

                break_dict[stmt.tryb.continueKey].append(block)
                self.visitScope(stmt.tryb, False, break_dict, new_stack)

                for cdecl, catchb in stmt.pairs:
                    parents = new_stack.pop()
                    self.visitScope(catchb, False, break_dict, catch_stack, cdecl.local, parents)
                assert(new_stack == catch_stack)
            else:
                assert(isinstance(stmt, ast.StatementBlock))
                break_dict[stmt.continueKey].append(block)
                self.visitScope(stmt, False, break_dict, catch_stack)

            if stmt.breakKey is not None:
                #register exception handlers for completed old block
                if block.canThrow():
                    for clist in catch_stack:
                        clist.append(block)
                # start new block after return from compound statement
                block = self.makeBlock(stmt.breakKey, break_dict, None, None)
            else:
                del block #should never be accessed anyway if we're exiting abruptly

        if scope.jumpKey is not None:
            break_dict[scope.jumpKey].append(block)

        if isloophead: #special case - if scope is the contents of a loop, we need to check for backedges
            # assert(scope.continueKey != scope.breakKey)
            head_block.n_successors += break_dict[scope.continueKey]
            del break_dict[scope.continueKey]

    def makeCFG(self, root, method_params):
        break_dict = ddict(list)
        self.visitScope(root, False, break_dict, [])

        entry = self.blocks[0] #entry point should always be first block generated
        entry.inp.initialize(method_params)

    # def finish(self, method_params):
    #     #prune useless blocks which have no content and merely jump to themselves
    #     #many of these are generated as a side effect of the way we generate the CFG and the way the continue/break keys work
    #     self.blocks = [b for b in self.blocks if b.lines or b.caught_excepts or self.nsuc_keys[b] != set([b.key])]

    #     entry = self.blocks[0] #entry point should always be first block generated
    #     entry.inp.initialize(method_params)

    #     allkeys = set(b.key for b in self.blocks)
    #     for block in self.blocks:
    #         assert(self.esuc_keys[block] | self.nsuc_keys[block] <= allkeys)
    #         for b2 in self.blocks:
    #             if b2.key in self.esuc_keys[block]:
    #                 block.e_successors.append(b2)
    #             if b2.key in self.nsuc_keys[block]:
    #                 block.n_successors.append(b2)