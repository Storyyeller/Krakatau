import collections

from ..ssa.objtypes import IntTT, ShortTT, CharTT, ByteTT, BoolTT
from . import ast
from .. import graph_util

mask_t = collections.namedtuple('mask_t', ('consts', 'vars'))
BOT, BOOL, BYTE, TOP = 0,1,2,3

def visitLeaf(expr, mask, arg_vars):
    #designed to handle both array and scalar case so doesn't do type checking
    if isinstance(expr, ast.Local):
        if expr in arg_vars or (expr.dtype[0] != '.bexpr' and expr.dtype[1]>0):
            isbool = (expr.dtype[0] == BoolTT[0])
            mask.consts.append(BOOL if isbool else BYTE)
        else:
            mask.vars.append(expr)
    else:
        assert(isinstance(expr, ast.Literal))
        if expr.dtype == IntTT and expr.val not in (0,1):
            mask.consts.append(BYTE)

def visitExprs(scope, callback):
    for item in scope.statements:
        for sub in item.getScopes():
            visitExprs(sub, callback)
        callback(item, item.expr)

def propagate(varlist, sources):
    vals = {}
    ordered = graph_util.tarjanSCC(varlist, lambda v:sources[v].vars)
    for scc in ordered: #make sure this is in topological order
        val = TOP
        for var in scc:
            for c in sources[var].consts:
                val &= c        
            for v in sources[var].vars:
                if v not in scc:
                    val &= vals[v]
        for var in scc:
            vals[var] = val
    return vals

def backPropagate(varlist, sources, vals):
    #Propagate backwards to vars that are undecided
    ordered = graph_util.topologicalSort(varlist, lambda v:sources[v].vars)
    revorder = [v for v in reversed(ordered) if vals[v] != BOT]

    for var in revorder:
        for v2 in sources[var].vars:
            if vals[v2] == TOP:
                vals[v2] = vals[var]

def fixArrays(root, arg_vars):
    varlist = []
    sources = collections.defaultdict(lambda:mask_t([], []))

    def addSourceArray(item, expr):
        if isinstance(expr, ast.Assignment):
            left, right = expr.params
            if not isinstance(left, ast.Local):
                return

            if left.dtype[0] == '.bexpr':
                assert(left not in arg_vars)
                varlist.append(left) # Note, may have duplicates, but this shouldn't really matter

                if isinstance(right, (ast.Local, ast.Literal)):
                    visitLeaf(right, sources[left], arg_vars)
                elif isinstance(right, (ast.ArrayCreation, ast.Cast, ast.FieldAccess, ast.MethodInvocation)):
                    isbool = (right.dtype[0] == BoolTT[0])
                    sources[left].consts.append(BOOL if isbool else BYTE)
                elif isinstance(right, ast.ArrayAccess):
                    visitLeaf(right.params[0], sources[left], arg_vars)
                else:
                    assert(0)
        if isinstance(item, ast.ReturnStatement) and isinstance(expr, ast.Local):
            if expr.dtype[0] == '.bexpr':
                isbool = (item.tt[0] == BoolTT[0])
                sources[expr].consts.append(BOOL if isbool else BYTE)
    
    visitExprs(root, addSourceArray)
    vals = propagate(varlist, sources)
    backPropagate(varlist, sources, vals)

    bases = {BOT:'.bexpr', BOOL:BoolTT[0], BYTE:ByteTT[0]}
    for var in set(varlist):
        assert(var.dtype[0] == '.bexpr' and var.dtype[1] > 0)
        var.dtype = bases[vals[var]], var.dtype[1]


def fixScalars(root, arg_vars):
    varlist = []
    sources = collections.defaultdict(lambda:mask_t([], []))

    int_tts = IntTT, ShortTT, CharTT, ByteTT, BoolTT
    instanceofs = []

    def addSourceScalar(item, expr):
        if isinstance(expr, ast.Assignment):
            left, right = expr.params
            if not isinstance(left, ast.Local):
                return

            if left.dtype in int_tts and left not in arg_vars:
                varlist.append(left) # Note, may have duplicates, but this shouldn't really matter

                if isinstance(right, (ast.Local, ast.Literal)):
                    visitLeaf(right, sources[left], arg_vars)
                elif isinstance(right, (ast.ArrayCreation, ast.ArrayAccess, ast.Cast, ast.FieldAccess, ast.MethodInvocation)):
                    isbool = (right.dtype[0] == BoolTT[0])
                    sources[left].consts.append(BOOL if isbool else BYTE)
                elif isinstance(right, ast.Ternary): #at this point, only ternaries should be from float/long comparisons
                    sources[left].consts.append(BYTE)
                elif isinstance(right, ast.BinaryInfix):
                    if right.opstr in '&^|':
                        visitLeaf(right.params[0], sources[left], arg_vars)
                        visitLeaf(right.params[1], sources[left], arg_vars)
                    elif right.opstr == 'instanceof':
                        instanceofs.append(left)
                    else:
                        assert(right.opstr in '* / % + - << >> >>>')
                        sources[left].consts.append(BYTE)
                else:
                    assert(0)
        if isinstance(item, ast.ReturnStatement) and isinstance(expr, ast.Local):
            if expr.dtype in int_tts and expr not in arg_vars:
                isbool = (item.tt[0] == BoolTT[0])
                sources[expr].consts.append(BOOL if isbool else BYTE)

    visitExprs(root, addSourceScalar)
    vals = propagate(varlist, sources)

    #Make instanceof results bool if it doesn't conflict with previous assignments
    for var in instanceofs:
        if vals[var] & BOOL:
           vals[var] = BOOL 
    backPropagate(varlist, sources, vals)

    #Fix the propagated types
    for var in set(varlist):
        if vals[var] == BOOL:
            var.dtype = BoolTT

    #Fix everything else back up
    def fixExpr(item, expr):
        if isinstance(expr, ast.Assignment):
            left, right = expr.params
            if left.dtype in int_tts:
                if not ast.isPrimativeAssignable(right.dtype, left.dtype):
                    expr.params = left, ast.makeCastExpr(left.dtype, right)
        elif isinstance(expr, ast.BinaryInfix):
            a,b = expr.params
            if a.dtype == BoolTT or b.dtype == BoolTT:
                assert(expr.opstr in '== != & | ^')
                expr.params = [ast.makeCastExpr(BoolTT, v) for v in expr.params]
    visitExprs(root, fixExpr)

def boolizeVars(root, arg_vars):
    arg_vars = frozenset(arg_vars)
    fixArrays(root, arg_vars)
    fixScalars(root, arg_vars)