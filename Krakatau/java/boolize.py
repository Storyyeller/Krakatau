import collections

from ..ssa.objtypes import IntTT, ShortTT, CharTT, ByteTT, BoolTT
from . import ast

class _GraphNode(object):
    def __init__(self, key):
        self.keys = frozenset([key])
        self.weights = collections.defaultdict(int)

def graphCutVars(root, arg_vars, visit_cb):
    # Any var which isn't known to be 0 or 1 is wide and must have a forced value
    # Forced int if any defs are methods, fields, arrays, or literals > 1 or any
    # defs are forced int. Forced bool otherwise

    # Compute graph for 01 vars
    # choose a cut
    # assign every chosen var to bool dtype
    # add expr param casts
    edges = []
    nodes = collections.OrderedDict()
    def get(key):
        if key not in nodes:
            nodes[key] = _GraphNode(key)
        return nodes[key]

    def contract(*keys):
        knodes = map(get, keys)
        new = knodes[0]
        new.keys = frozenset().union(*(x.keys for x in knodes))

        assert(not (True in new.keys and False in new.keys))

        for key in new.keys:
            nodes[key] = new

    def addedge(key1, key2):
        edges.append((key1, key2))

    def visitExpr(expr):
        if hasattr(expr, 'params'):
            for param in expr.params:
                visitExpr(param)
            visit_cb(expr, arg_vars, addedge, contract)

    def visitScope(scope):
        for item in scope.statements:
            for sub in item.getScopes():
                visitScope(sub)
            if getattr(item, 'expr', None) is not None:
                visitExpr(item.expr)

    visitScope(root)
    assert(get(False) != get(True))
    for key1, key2 in edges:
        node1, node2 = get(key1), get(key2)
        if node1 != node2:
            node1.weights[node2] += 1
            node2.weights[node1] += 1

    temp = set()
    nodelist = [n for n in nodes.values() if not n in temp and not temp.add(n)]
    for node in nodelist:
        items = node.weights.items()
        node.weights = collections.OrderedDict(sorted(items, key=lambda (n,w):nodelist.index(n)))

    # print '\n'.join(map('{0[0]} <-> {0[1]}'.format, edges))
    # import pdb;pdb.set_trace()

    #Greedy algorithm - todo: Edumund Karps
    set1 = set()
    stack = [get(False)]
    while stack:
        cur = stack.pop()
        if cur not in set1 and True not in cur.keys:
            set1.add(cur)
            stack.extend(cur.weights)

    set2 = temp - set1
    keys1 = frozenset().union(*(n.keys for n in set1))
    keys2 = frozenset().union(*(n.keys for n in set2))
    keys1 -= set([False])
    keys2 -= set([True])
    assert(False not in keys2)
    return keys1, keys2

_prefixes = '.bexpr', BoolTT[0], ByteTT[0]
def visitExpr_array(expr, arg_vars, addedge, contract):
    getbase = lambda expr:expr.dtype[0] if expr.dtype else None

    pkeys = [(expr, i) for i,param in enumerate(expr.params) if getbase(param) in _prefixes]
    for key in pkeys:
        param = expr.params[key[1]]
        if not isinstance(param, ast.Literal):
            addedge(key, param)
        if getbase(param) != '.bexpr':
            contract((getbase(param) == BoolTT[0]), param)

    if isinstance(expr, ast.Assignment):
        if len(pkeys) == 2:
            addedge(*pkeys)
            contract(expr, pkeys[0])
    elif isinstance(expr, ast.ArrayAccess):
        if pkeys:
            contract(expr, pkeys[-1])   
    elif isinstance(expr, (ast.MethodInvocation, ast.ClassInstanceCreation)):
        for i,tt in enumerate(expr.tts):
            if tt and tt[0] in _prefixes:
                contract((tt[0]==BoolTT[0]), (expr,i))
    elif isinstance(expr, ast.Ternary):
        if getbase(expr) in _prefixes:
            contract(expr, *pkeys[1:])    

def processResults_array(bytekeys, boolkeys):
    for key in bytekeys | boolkeys:
        if not isinstance(key, tuple):
            expr = key
            base, dim = expr.dtype
            if base == '.bexpr':
                new = BoolTT[0] if key in boolkeys else ByteTT[0]
                expr.dtype = new, dim

all_tts = IntTT, ShortTT, CharTT, ByteTT, BoolTT
def visitExpr_bool(expr, arg_vars, addedge, contract):
    contractIf = lambda (expr):contract((expr.dtype==BoolTT), expr) if expr.dtype in all_tts else None

    if expr in arg_vars:
        contractIf(expr)

    pkeys = [(expr, i) for i,param in enumerate(expr.params) if param.dtype in all_tts]
    for key in pkeys:
        param = expr.params[key[1]]
        if not isinstance(param, ast.Literal):
            addedge(key, param)
        else:
            if param.val not in (0,1):
                contract(False, param)

    if isinstance(expr, ast.Assignment):
        if len(pkeys) == 2:
            addedge(*pkeys)
            contract(expr, pkeys[0])
    elif isinstance(expr, ast.ArrayAccess):
        contractIf(expr)
        contract(False, pkeys[0])     
    elif isinstance(expr, ast.BinaryInfix):
        if expr.opstr in ('==', '!=', '<', '>', '<=', '>=', 'instanceof'):
            contract(True, expr)
            if pkeys:
                if expr.opstr in ('==', '!='):
                    contract(*pkeys)
                elif expr.opstr in ('<', '>', '<=', '>='):
                    contract(False, *pkeys)
        elif expr.opstr in ('+', '/', '*', '-', '%', '<<', '>>', '>>>'):
            contract(False, expr, *pkeys)
        elif expr.opstr in ('&', '|', '^'):
            contract(expr, *pkeys)
        else:
            assert(0)
    elif isinstance(expr, (ast.MethodInvocation, ast.ClassInstanceCreation)):
        for i,tt in enumerate(expr.tts):
            if tt in all_tts:
                contract((tt==BoolTT), (expr,i))
        contractIf(expr)
    elif isinstance(expr, ast.Ternary):
        if expr.dtype in all_tts:
            contract(expr, *pkeys[1:])
        contract(True, pkeys[0])        
    else:
        contractIf(expr) 

def processResults_bool(intkeys, boolkeys):
    for key in boolkeys:
        if not isinstance(key, tuple):
            expr = key
            expr.dtype = BoolTT
    for key in boolkeys:
        if isinstance(key, tuple):
            expr, i = key
            new = ast.makeCastExpr(BoolTT, expr.params[i])
            assert(new.dtype == BoolTT)
            expr.params = type(expr.params)((new if j == i else x) for j,x in enumerate(expr.params))

def boolizeVars(root, arg_vars):
    processResults_array(*graphCutVars(root, arg_vars, visitExpr_array))
    processResults_bool(*graphCutVars(root, arg_vars, visitExpr_bool))