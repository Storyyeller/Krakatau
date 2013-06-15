import collections

from ..ssa.objtypes import IntTT, ShortTT, CharTT, ByteTT, BoolTT
from . import ast
from .. import graph_util

def addSourceArray(left, right, arg_vars, varlist, srcvars, bytearrs, boolarrs):
    if left.dtype[0] == '.bexpr':
        assert(left not in arg_vars)
        if left in bytearrs or left in boolarrs:
            return
        varlist.append(left) # Note, may have duplicates, but this shouldn't really matter

        assert(not isinstance(right, (ast.Assignment, ast.Parenthesis, ast.Ternary)))
        if right in arg_vars or isinstance(right, 
            (ast.ArrayCreation, ast.Cast, ast.FieldAccess, ast.MethodInvocation)):
            temp = bytearrs if right.dtype[0] == ByteTT[0] else boolarrs
            temp.add(left)
            srcvars[left] = []
        elif isinstance(right, ast.Local):
            srcvars[left].append(right)
        elif isinstance(right, ast.ArrayAccess):
            assert(isinstance(right.params[0], ast.Local))
            srcvars[left].append(right.params[0])

def handleResultsArray(varlist, bytearrs, boolarrs):
    for var in varlist:
        assert(var.dtype[1] > 0)
        if var in bytearrs:
            var.dtype = ByteTT[0], var.dtype[1]        
        elif var in boolarrs:
            var.dtype = BoolTT[0], var.dtype[1]

_int_tts = IntTT, ShortTT, CharTT, ByteTT, BoolTT
_int_ops = '* / % + - << >> >>>'.split()
_bool_ops = ' < > <= >= == != instanceof && ||'.split()
_any_ops = '& ^ |'.split()

def addSourceScalar(left, right, arg_vars, varlist, srcvars, ints, bools):
    if left.dtype in _int_tts:
        if left in ints or left in bools:
            return
        varlist.append(left) # Note, may have duplicates, but this shouldn't really matter

        if left in arg_vars:
            temp = bools if right.dtype == BoolTT else ints
            temp.add(left)
            return

        def addLocalLitOrTernary(expr):
            if isinstance(expr, ast.Local):
                srcvars[left].append(expr)            
            elif isinstance(expr, ast.Ternary):
                addLocalLitOrTernary(expr.params[1])
                addLocalLitOrTernary(expr.params[2])
            else:
                assert(isinstance(expr, ast.Literal))
                if not 0 <= expr.val <= 1:
                    ints.add(left)

        assert(not isinstance(right, (ast.Assignment, ast.Parenthesis, ast.UnaryPrefix)))
        if isinstance(right, (ast.ArrayCreation, ast.Cast, ast.FieldAccess, ast.MethodInvocation, 
            ast.ArrayAccess)):
            temp = bools if right.dtype == BoolTT else ints
            temp.add(left)
        elif isinstance(right, (ast.Local, ast.Literal, ast.Ternary)):
            addLocalLitOrTernary(right)
        elif isinstance(right, ast.BinaryInfix):
            if right.opstr in _int_ops:
                ints.add(left)
            elif right.opstr in _bool_ops:
                bools.add(left)
            else:
                assert(right.opstr in _any_ops)
                addLocalLitOrTernary(right.params[0])
                addLocalLitOrTernary(right.params[1])

        if left in bools or left in ints:
            srcvars[left] = []

def handleResultsScalar(varlist, ints, bools):
    for var in varlist:
        if var in bools:
            var.dtype = BoolTT

def propagateTypes(root, arg_vars, addSource, handleResults):
    varlist = []
    srcvars = collections.defaultdict(list)
    set1 = set()
    set2 = set()

    def visitAssign(left, right):
        if isinstance(left, ast.Local):
            addSource(left, right, arg_vars, varlist, srcvars, set1, set2)

    def visitScope(scope):
        for item in scope.statements:
            for sub in item.getScopes():
                visitScope(sub)
            if isinstance(item.expr, ast.Assignment):
                visitAssign(*item.expr.params)
    visitScope(root)

    temp = set1 | set2
    unknown = [v for v in varlist if v not in temp and not temp.add(v)]

    ordered = graph_util.topologicalSort(unknown, lambda v:srcvars[v])
    for var in ordered:
        for source in srcvars[var]:
            if source in set1:
                set1.add(var)
                break            
            elif source in set2:
                set2.add(var)
                break

    assert(not set2 & set1)
    assert(not set2 & arg_vars)
    handleResults(varlist, set1, set2)

def boolizeVars(root, arg_vars):
    arg_vars = frozenset(arg_vars)
    propagateTypes(root, arg_vars, addSourceArray, handleResultsArray)    
    propagateTypes(root, arg_vars, addSourceScalar, handleResultsScalar)  

    #Make sure types match in binary expressions
    def visitExpr(expr):
        for param in expr.params:
            visitExpr(param)

        if isinstance(expr, (ast.Assignment, ast.BinaryInfix)):
            left, right = expr.params
            if left.dtype == BoolTT:
                right = ast.makeCastExpr(BoolTT, right)
            elif right.dtype == BoolTT and isinstance(expr, ast.BinaryInfix):
                left = ast.makeCastExpr(BoolTT, left)
            expr.params = left, right

    def visitScope(scope):
        for item in scope.statements:
            for sub in item.getScopes():
                visitScope(sub)
            if item.expr is not None:
                visitExpr(item.expr)
    visitScope(root)