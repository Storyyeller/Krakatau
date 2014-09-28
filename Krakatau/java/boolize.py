from ..ssa.objtypes import IntTT, ShortTT, CharTT, ByteTT, BoolTT, BExpr
from . import ast

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
            self.d[root2] = root1

##############################################################
def visitStatementTree(scope, callback):
    for item in scope.statements:
        for sub in item.getScopes():
            visitStatementTree(sub, callback=callback)
        if item.expr is not None:
            callback(item, item.expr)

int_tags = frozenset(tt[0] for tt in [IntTT, ShortTT, CharTT, ByteTT, BoolTT])
array_tags = frozenset([ByteTT[0], BoolTT[0], BExpr])

def boolizeVars(root, arg_vars):
    varlist = []
    sets = UnionFind()

    def visitExpr(expr, forceExact=False):
        #see if we have to merge
        if isinstance(expr, ast.Assignment) or isinstance(expr, ast.BinaryInfix) and expr.opstr in ('==','!=','&','|','^'):
            subs = [visitExpr(param) for param in expr.params]
            sets.union(*subs) # these operators can work on either type but need the same type on each side
        elif isinstance(expr, ast.ArrayAccess):
            sets.union(False, visitExpr(expr.params[1])) # array index is int only
        elif isinstance(expr, ast.BinaryInfix) and expr.opstr in ('* / % + - << >> >>>'):
            sets.union(False, visitExpr(expr.params[0])) # these operators are int only
            sets.union(False, visitExpr(expr.params[1]))

        if isinstance(expr, ast.Local):
            tag, dim = expr.dtype
            if (dim == 0 and tag in int_tags) or (dim > 0 and tag in array_tags):
                # the only "unknown" vars are bexpr[] and ints. All else have fixed types
                if forceExact or (tag != BExpr and tag != IntTT[0]):
                    sets.union(tag == BoolTT[0], expr)
                varlist.append(expr)
                return sets.find(expr)
        elif isinstance(expr, ast.Literal):
            if expr.dtype == IntTT and expr.val not in (0,1):
                return False
            return None #if val is 0 or 1, or the literal is a null, it is freely convertable
        elif isinstance(expr, ast.Assignment) or (isinstance(expr, ast.BinaryInfix) and expr.opstr in ('&','|','^')):
            return subs[0]
        elif isinstance(expr, (ast.ArrayAccess, ast.Parenthesis, ast.UnaryPrefix)):
            return visitExpr(expr.params[0])
        elif expr.dtype is not None and expr.dtype[0] != BExpr:
            return expr.dtype[0] == BoolTT[0]
        return None

    def visitStatement(item, expr):
        root = visitExpr(expr)
        if isinstance(item, ast.ReturnStatement):
            forced_val = (item.tt[0] == BoolTT[0])
            sets.union(forced_val, root)

    for expr in arg_vars:
        visitExpr(expr, forceExact=True)
    visitStatementTree(root, callback=visitStatement)

    #Fix the propagated types
    for var in set(varlist):
        tag, dim = var.dtype
        assert(tag in int_tags or (dim>0 and tag == BExpr))
        #make everything bool which is not forced to int
        if sets.find(var) != False:
            var.dtype = BoolTT[0], dim
        elif dim > 0:
            var.dtype = ByteTT[0], dim

    #Fix everything else back up
    def fixExpr(item, expr):
        for param in expr.params:
            fixExpr(None, param)

        if isinstance(expr, ast.Assignment):
            left, right = expr.params
            if left.dtype[0] in int_tags and left.dtype[1] == 0:
                if not ast.isPrimativeAssignable(right.dtype, left.dtype):
                    expr.params = left, ast.makeCastExpr(left.dtype, right)
        elif isinstance(expr, ast.BinaryInfix):
            a, b = expr.params
            #shouldn't need to do anything here for arrays
            if expr.opstr in '== != & | ^' and a.dtype == BoolTT or b.dtype == BoolTT:
                expr.params = [ast.makeCastExpr(BoolTT, v) for v in expr.params]
    visitStatementTree(root, callback=fixExpr)