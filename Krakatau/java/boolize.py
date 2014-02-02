import collections

from ..ssa.objtypes import IntTT, ShortTT, CharTT, ByteTT, BoolTT
from . import ast
from .. import graph_util

#Class union-find data structure except that we don't bother with weighting trees and singletons are implicit
#Also, booleans are forced to be seperate roots
FORCED_ROOTS = True, False
class UnionFind(object):
    def __init__(self):
        self.d = {}

    def find(self, x):
        if x not in self.d:
            return x
        path = [x]
        while path[-1] in self.d:
            path.append(self.d[path[-1]])
        root = path.pop()
        for y in path:
            self.d[y] = root
        return root

    def union(self, x, x2):
        if x is None or x2 is None:
            return
        root1, root2 = self.find(x), self.find(x2)
        if root2 in FORCED_ROOTS:
            root1, root2 = root2, root1
        if root1 != root2 and root2 not in FORCED_ROOTS:
        # if root1 != root2:
        #     assert(root2 not in FORCED_ROOTS)
            self.d[root2] = root1

##############################################################
def visitExprs(scope, callback):
    for item in scope.statements:
        for sub in item.getScopes():
            visitExprs(sub, callback)
        if item.expr is not None:
            callback(item, item.expr)

int_tts = IntTT, ShortTT, CharTT, ByteTT, BoolTT
def fixArrays(root, arg_vars):
    varlist = []
    sets = UnionFind()

    for expr in arg_vars:
        forced_val = (expr.dtype[0] == BoolTT[0])
        sets.union(forced_val, expr)

    def visitExprArray(expr):
        #see if we have to merge
        if isinstance(expr, ast.Assignment) or isinstance(expr, ast.BinaryInfix) and expr.opstr in ('==','!='):
            subs = [visitExprArray(param) for param in expr.params]
            sets.union(*subs)

        if isinstance(expr, ast.Local):
            if expr.dtype[1] == 0:
                return None
            if expr.dtype[0] == '.bexpr' and expr.dtype[1] > 0:
                varlist.append(expr)
            return sets.find(expr)
        elif isinstance(expr, ast.Literal):
            return None
        elif isinstance(expr, (ast.ArrayAccess, ast.Parenthesis, ast.UnaryPrefix)):
            return visitExprArray(expr.params[0])
        elif expr.dtype is not None and expr.dtype[0] != '.bexpr':
            return expr.dtype[0] == BoolTT[0]
        return None

    def addSourceArray(item, expr):
        root = visitExprArray(expr)
        if isinstance(item, ast.ReturnStatement):
            forced_val = (item.tt[0] == BoolTT[0])
            sets.union(forced_val, root)

    visitExprs(root, addSourceArray)
    bases = {True:BoolTT[0], False:ByteTT[0]}
    for var in set(varlist):
        assert(var.dtype[0] == '.bexpr' and var.dtype[1] > 0)
        var.dtype = bases[sets.find(var)], var.dtype[1]

def fixScalars(root, arg_vars):
    varlist = []
    sets = UnionFind()

    for expr in arg_vars:
        forced_val = (expr.dtype[0] == BoolTT[0])
        sets.union(forced_val, expr)

    def visitExprScalar(expr):
        #see if we have to merge
        if isinstance(expr, ast.Assignment) or isinstance(expr, ast.BinaryInfix) and expr.opstr in ('==','!=','&','|','^'):
            subs = [visitExprScalar(param) for param in expr.params]
            sets.union(*subs)
            if isinstance(expr, ast.Assignment) or expr.opstr in ('&','|','^'):
                return subs[0]
        elif isinstance(expr, ast.BinaryInfix) and expr.opstr in ('* / % + - << >> >>>'):
            sets.union(False, visitExprScalar(expr.params[0]))
            sets.union(False, visitExprScalar(expr.params[1]))

        if isinstance(expr, ast.Local):
            if expr.dtype in int_tts:
                varlist.append(expr)
            return sets.find(expr)
        elif isinstance(expr, ast.Literal):
            if expr.dtype == IntTT and expr.val not in (0,1):
                return False
            return None
        elif isinstance(expr, (ast.ArrayAccess, ast.Parenthesis, ast.UnaryPrefix)):
            return visitExprScalar(expr.params[0])
        elif expr.dtype is not None and expr.dtype[0] != '.bexpr':
            return expr.dtype[0] == BoolTT[0]
        return None

    def addSourceScalar(item, expr):
        root = visitExprScalar(expr)
        if isinstance(item, ast.ReturnStatement):
            forced_val = (item.tt[0] == BoolTT[0])
            sets.union(forced_val, root)

    visitExprs(root, addSourceScalar)

    #Fix the propagated types
    for var in set(varlist):
        assert(var.dtype in int_tts)
        if sets.find(var) != False:
            var.dtype = BoolTT

    #Fix everything else back up
    def fixExpr(item, expr):
        for param in expr.params:
            fixExpr(None, param)

        if isinstance(expr, ast.Assignment):
            left, right = expr.params
            if left.dtype in int_tts:
                if not ast.isPrimativeAssignable(right.dtype, left.dtype):
                    expr.params = left, ast.makeCastExpr(left.dtype, right)
        elif isinstance(expr, ast.BinaryInfix):
            a,b = expr.params
            if expr.opstr in '== != & | ^' and a.dtype == BoolTT or b.dtype == BoolTT:
                # assert(expr.opstr in '== != & | ^')
                expr.params = [ast.makeCastExpr(BoolTT, v) for v in expr.params]
    visitExprs(root, fixExpr)

def boolizeVars(root, arg_vars):
    arg_vars = frozenset(arg_vars)
    fixArrays(root, arg_vars)
    fixScalars(root, arg_vars)