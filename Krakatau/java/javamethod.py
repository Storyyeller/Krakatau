import itertools, collections
import os, copy

from ..ssa import ssa_types, ssa_ops, ssa_jumps
from ..ssa import objtypes, constraints
from ..ssa.exceptionset import ExceptionSet
from .. import graph_util
from ..namegen import NameGen, LabelGen
from ..inference_verifier import parseFieldDescriptor, parseMethodDescriptor

from . import ast, ast2, preprocess, boolize
from .reserved import reserved_identifiers
from .setree import createSETree, SEBlockItem, SEScope, SEIf, SESwitch, SETry, SEWhile

class DecompilationError(Exception):
    def __init__(self, message, data=None):
        super(DecompilationError, self).__init__(message)
        self.data = data

def error(msg):
    raise DecompilationError(msg)

_math_types = (ssa_ops.IAdd, ssa_ops.IDiv, ssa_ops.IMul, ssa_ops.IRem, ssa_ops.ISub)
_math_types += (ssa_ops.IAnd, ssa_ops.IOr, ssa_ops.IShl, ssa_ops.IShr, ssa_ops.IUshr, ssa_ops.IXor)
_math_types += (ssa_ops.FAdd, ssa_ops.FDiv, ssa_ops.FMul, ssa_ops.FRem, ssa_ops.FSub)
_math_symbols = dict(zip(_math_types, '+ / * % - & | << >> >>> ^ + / * % -'.split()))
def convertJExpr(self, op, info):
    expr = None
    getExpr = lambda var: info[var].expr
    params = [getExpr(var) for var in op.params if var.type != ssa_types.SSA_MONAD]
    assert(None not in params)

    #Have to do this one seperately since it isn't an expression statement
    if isinstance(op, ssa_ops.Throw):
        return ast.ThrowStatement(params[0])    

    if isinstance(op, _math_types):
        opdict = _math_symbols
        expr = ast.BinaryInfix(opdict[type(op)], params)
    elif isinstance(op, ssa_ops.ArrLength):
        expr = ast.FieldAccess(params[0], 'length', objtypes.IntTT)
    elif isinstance(op, ssa_ops.ArrLoad):
        expr = ast.ArrayAccess(*params)
    elif isinstance(op, ssa_ops.ArrStore):
        expr = ast.ArrayAccess(params[0], params[1])
        expr = ast.Assignment(expr, params[2])
    elif isinstance(op, ssa_ops.CheckCast):
        expr = ast.Cast(ast.TypeName(op.target_tt), params[0])        
    elif isinstance(op, ssa_ops.Convert):
        typecode = {ssa_types.SSA_INT:'.int', ssa_types.SSA_LONG:'.long', ssa_types.SSA_FLOAT:'.float', 
            ssa_types.SSA_DOUBLE:'.double'}[op.target]
        tt = typecode, 0
        expr = ast.Cast(ast.TypeName(tt), params[0])
    elif isinstance(op, (ssa_ops.FCmp, ssa_ops.ICmp)):
        var1, var2 = params
        boolt = objtypes.BoolTT
        cn1, c0, c1 = ast.Literal.N_ONE, ast.Literal.ZERO, ast.Literal.ONE

        ascend = isinstance(op, ssa_ops.ICmp) or op.NaN_val == 1
        if ascend:
            expr = ast.Ternary(ast.BinaryInfix('<',params,boolt), cn1, ast.Ternary(ast.BinaryInfix('==',params,boolt), c0, c1))
        else:
            assert(op.NaN_val == -1)
            expr = ast.Ternary(ast.BinaryInfix('>',params,boolt), c1, ast.Ternary(ast.BinaryInfix('==',params,boolt), c0, cn1))
    elif isinstance(op, ssa_ops.FieldAccess):
        dtype = objtypes.verifierToSynthetic(parseFieldDescriptor(op.desc, unsynthesize=False)[0])

        if 'static' in op.instruction[0]:
            tt = op.target, 0
            expr = ast.FieldAccess(ast.TypeName(tt), op.name, dtype)
        else:
            expr = ast.FieldAccess(params[0], op.name, dtype)

        if 'put' in op.instruction[0]:
            expr = ast.Assignment(expr, params[-1])

    elif isinstance(op, ssa_ops.FNeg):
        expr = ast.UnaryPrefix('-', params[0])    
    elif isinstance(op, ssa_ops.InstanceOf):
        args = params[0], ast.TypeName(op.target_tt)
        expr = ast.BinaryInfix('instanceof', args, dtype=objtypes.BoolTT)
    elif isinstance(op, ssa_ops.Invoke):            
        vtypes, rettypes = parseMethodDescriptor(op.desc, unsynthesize=False)
        vtypes = [vt for vt in vtypes if not (vt.cat2 and vt.top)]
        tt_types = objtypes.verifierToSynthetic_seq(vtypes)
        ret_type = objtypes.verifierToSynthetic(rettypes[0]) if rettypes else None 

        if op.instruction[0] == 'invokeinit' and op.uninit_verifier_type.origin is None:
            name = 'this' if (op.target == self.method.class_.name) else 'super'
            expr = ast.MethodInvocation(None, name, tt_types, params[1:], op, ret_type)
        elif op.instruction[0] == 'invokestatic': #TODO - fix this for special super calls
            tt = op.target, 0
            expr = ast.MethodInvocation(ast.TypeName(tt), op.name, [None]+tt_types, params, op, ret_type)
        else:
            expr = ast.MethodInvocation(params[0], op.name, [(op.target,0)]+tt_types, params[1:], op, ret_type)
    elif isinstance(op, ssa_ops.Monitor):
        fmt = '//monexit({})' if op.exit else '//monenter({})'
        expr = ast.Dummy(fmt, params)    
    elif isinstance(op, ssa_ops.MultiNewArray):
        expr = ast.ArrayCreation(op.tt, *params) 
    elif isinstance(op, ssa_ops.New):
        expr = ast.Dummy('//<unmerged new> {}', [ast.TypeName(op.tt)], isNew=True)     
    elif isinstance(op, ssa_ops.NewArray):
        base, dim = op.baset
        expr = ast.ArrayCreation((base, dim+1), params[0])
    elif isinstance(op, ssa_ops.Truncate):
        typecode = {(True,16):'.short', (False,16):'.char', (True,8):'.byte'}[op.signed, op.width]
        tt = typecode, 0
        expr = ast.Cast(ast.TypeName(tt), params[0])
    if op.rval is not None and expr:
        expr = ast.Assignment(getExpr(op.rval), expr)
    
    if expr is None: #Temporary hack to show what's missing
        return ast.StringStatement('//' + type(op).__name__)
    return ast.ExpressionStatement(expr)

_prefix_map = {objtypes.IntTT:'i', objtypes.LongTT:'j',
            objtypes.FloatTT:'f', objtypes.DoubleTT:'d',
            objtypes.BoolTT:'b', objtypes.StringTT:'s'}

def ssavarToExpr(var, tt, namegen):           
    if var.const is not None:
        return ast.Literal(tt, var.const)
    else:
        if var.name:
            namefunc = lambda expr:var.name
        else:
            def namefunc(expr):
                prefix = _prefix_map.get(expr.dtype, 'a')
                return namegen.getPrefix(prefix)
        return ast.Local(tt, namefunc)   

class DeclInfo(object):
    __slots__ = "declScope scope defs".split()
    def __init__(self):
        self.declScope = self.scope = None 
        self.defs = []

def findVarDeclInfo(root, decls):
    info = collections.OrderedDict()
    def visit(scope, expr):
        if isinstance(expr, ast.Assignment):
            left, right = expr.params
            visit(scope, left)
            visit(scope, right)
            if isinstance(left, ast.Local):
                info[left].defs.append(right)
        elif isinstance(expr, (ast.Local, ast.Literal)):
            info[expr] = info.get(expr, DeclInfo())
            info[expr].scope = ast.StatementBlock.join(info[expr].scope, scope)
        elif hasattr(expr, 'params'): #temp hack
            for param in expr.params:
                visit(scope, param)

    def visitDecl(scope, decl):
        expr = decl.local 
        info[expr] = info.get(expr, DeclInfo())
        assert(scope is not None and info[expr].declScope is None)
        info[expr].declScope = scope 

    for decl in decls:
        visitDecl(root, decl)

    stack = [(root,root)]
    while stack:
        scope, stmt = stack.pop()
        if isinstance(stmt, ast.StatementBlock):
            stack.extend((stmt,sub) for sub in stmt.statements)
        else:
            stack.extend((subscope,subscope) for subscope in stmt.getScopes())
            #temp hack
            if getattr(stmt, 'expr', None) is not None:
                visit(scope, stmt.expr)
            if isinstance(stmt, ast.TryStatement):
                visitDecl(stmt.parts[2], stmt.parts[1])
    return info

class MethodDecompiler(object):
    def __init__(self, method, graph):
        self.env = method.class_.env
        self.method, self.graph = method, graph
        self.namegen = NameGen(reserved_identifiers)
        self.labelgen = LabelGen().next

    ###################################################################################################
    def _getBlockIfExpr(self, block):
        if isinstance(block.jump, (ssa_jumps.If)):
            symbols = "== != < >= > <=".split()
            cmp_strs = dict(zip(('eq','ne','lt','ge','gt','le'), symbols))
            cmp_str = cmp_strs[block.jump.cmp]
            exprs = [self.varinfo[var].expr for var in block.jump.params]
            return ast.BinaryInfix(cmp_str, exprs, objtypes.BoolTT)

    def _createAST_block(self, block, targets, ftblock, ifSwitchInfo = None):
        new = ast.StatementBlock(self.labelgen)
        if ftblock is not None:
            targets = targets + ((ftblock, (new,False)),)
        gotoMap = dict(targets) #more recent keys override, as desired

        #Create lists of phi assignments necessary for each sucessor
        phidict = collections.defaultdict(list)
        for child in block.jump.getSuccessors():
            assert(child not in phidict) #we assume that parallel edges were removed earlier
            assignments = phidict[child]
            for phi in child.phis:
                oldvar = phi.odict.get((block,False), phi.odict.get((block,True)))
                newvar = phi.rval

                if oldvar.type == ssa_types.SSA_MONAD or (oldvar.origin and oldvar == oldvar.origin.outException):
                    continue
                oldvar, newvar = self.varinfo[oldvar].expr, self.varinfo[newvar].expr
                assign = ast.Assignment(newvar, oldvar)
                assignments.append(ast.ExpressionStatement(assign))

        # lines = [ast.StringStatement('//' + str(block))]
        lines = [convertJExpr(self, op, self.varinfo) for op in block.lines[:-1]]
        if isinstance(block.jump, ssa_jumps.OnException):
            #For this case, phi assignments needed by exceptional successors must be placed before the last op line
            #(Which is the one that might throw). Phi assignments for the normal successor come after the last line
            #as normal
            assert(block.jump.params[0].origin == block.lines[-1])
            for exceptSuccessor in block.jump.getExceptSuccessors():
                lines += phidict[exceptSuccessor]
        #now add back in the possibly throwing statement
        lines += [convertJExpr(self, op, self.varinfo) for op in block.lines[-1:]]

        if isinstance(block.jump, (ssa_jumps.Goto, ssa_jumps.OnException)):
            if block.jump.getNormalSuccessors():            
                fallthrough = block.jump.getNormalSuccessors()[0]         
                lines += phidict[fallthrough]
                new.setBreak(gotoMap[fallthrough])

        elif isinstance(block.jump, (ssa_jumps.If)):
            expr = self._getBlockIfExpr(block)
            newif = ast.IfStatement(self.labelgen, expr)
            if ftblock is not None:
                targets = targets + ((ftblock, (newif,False)),)
            gotoMap = dict(targets)

            if ifSwitchInfo is None:
                ifSwitchInfo = {}
            sebodies = ifSwitchInfo
            bodies = {}
            for successor in block.jump.getSuccessors():
                if successor not in sebodies:
                    temp = bodies[successor] = ast.StatementBlock(self.labelgen)
                    temp.statements = []
                    temp.setBreak(gotoMap[successor])
                else:
                    bodies[successor] = self._createAST(sebodies[successor], targets, ftblock, forceUnlabled=True)

            for k,v in bodies.items():
                v.statements = phidict[k] + v.statements
            falsebody, truebody = map(bodies.get, block.jump.getSuccessors())
            newif.scopes = truebody, falsebody
            lines.append(newif)

        elif isinstance(block.jump, (ssa_jumps.Switch)):
            var = block.jump.params[0]
            expr = self.varinfo[var].expr
            newswitch = ast.SwitchStatement(self.labelgen, expr)
            if ftblock is not None:
                targets = targets + ((ftblock, (newswitch,False)),)
            gotoMap = dict(targets)

            #Order the blocks in a manner consistent with the fallthroughs. In case of tie, prefer
            #the original order except with default last
            if ifSwitchInfo is None:
                ifSwitchInfo = {}, [], ()
            sebodies, orders, critical = ifSwitchInfo

            for successor in block.jump.getSuccessors():
                if successor not in sebodies:
                    orders.append([successor])
            tiebreak = block.jump.getSuccessors()[1:] + block.jump.getSuccessors()[:1]
            orders = sorted(orders, key=lambda slist:tiebreak.index(slist[0]))
            successors = list(itertools.chain(*orders))
            assert(len(set(successors)) == len(successors))

            bodies = {}
            subft = ftblock
            for successor in reversed(successors):
                if successor not in sebodies:
                    temp = bodies[successor] = ast.StatementBlock(self.labelgen)
                    temp.statements = []
                    temp.setBreak(gotoMap[successor])
                    subft = None
                else:
                    bodies[successor] = self._createAST(sebodies[successor], targets, subft, forceUnlabled=True)
                    subft = sebodies[successor].entryBlock()

            for k,v in bodies.items():
                if k in critical:
                    lines += phidict[k]
                else:
                    v.statements = phidict[k] + v.statements

            pairs = [(block.jump.reverse.get(child), bodies[child]) for child in successors]
            newswitch.pairs = pairs
            lines.append(newswitch)

        elif isinstance(block.jump, ssa_jumps.Rethrow):
            param = self.varinfo[block.jump.params[-1]].expr
            lines.append(ast.ThrowStatement(param))
        else:
            assert(isinstance(block.jump, ssa_jumps.Return))
            if len(block.jump.params)>1: #even void returns have a monad param
                returnTypes = parseMethodDescriptor(self.method.descriptor, unsynthesize=False)[1]
                ret_tt = objtypes.verifierToSynthetic(returnTypes[0])
                param = self.varinfo[block.jump.params[-1]].expr
                lines.append(ast.ReturnStatement(param, ret_tt))
            else:
                lines.append(ast.ReturnStatement())
        
        new.statements = lines
        assert(all(isinstance(s, ast.JavaStatement) for s in new.statements))
        return new        
    
    def _createAST(self, current, targets, ftblock, forceUnlabled=False):
        if isinstance(current, SEScope):
            new = ast.StatementBlock(self.labelgen)
            if not forceUnlabled and ftblock is not None:
                targets = targets + ((ftblock, (new,False)),)

            #todo - is sorting required here?
            last = ftblock
            contents = []
            for item in reversed(current.items):
                contents.append(self._createAST(item, targets, last))
                last = item.entryBlock()

            new.statements = list(reversed(contents))
            new.jump = None
            assert(all(isinstance(s, ast.JavaStatement) for s in new.statements))
        elif isinstance(current, SEWhile):
            new = ast.WhileStatement(self.labelgen)
            targets = targets + ((current.entryBlock(), (new,True)),)
            if ftblock is not None:
                targets = targets + ((ftblock, (new,False)),)
            new.parts = self._createAST(current.body, targets, None),
        elif isinstance(current, SETry):
            new = ast.TryStatement(self.labelgen)
            if ftblock is not None:
                targets = targets + ((ftblock, (new,False)),)
            parts = [self._createAST(scope, targets, None) for scope in current.getScopes()]
            new.parts = parts[0], current.decl, parts[1]
        elif isinstance(current, SEIf):
            parts = {scope.entryBlock():scope for scope in current.getScopes()}
            new = self._createAST_block(current.head.block, targets, ftblock, parts)
        elif isinstance(current, SESwitch):
            parts = {scope.entryBlock():scope for scope in current.getScopes()}
            switchInfo = parts, current.orders, current.critical
            new = self._createAST_block(current.head.block, targets, ftblock, switchInfo)
        elif isinstance(current, SEBlockItem):
            new = self._createAST_block(current.block, targets, ftblock)
        return new
    ###################################################################################################
    def _pruneRethrow_cb(self, item):
        catchb = item.getScopes()[-1]
        lines = catchb.statements
        if len(lines) == 1:
            line = lines[0]
            caught = item.parts[1].local 
            if isinstance(line, ast.ThrowStatement) and line.expr == caught:
                new = item.getScopes()[0]
                assert(not new.Sources())

                for x in item.Sources():
                    x.setBreak((new,x.jump[1]))
                assert(not item.Sources())
                return new
        return item    

    def _reverseBoolExpr(self, expr):
        assert(expr.dtype == objtypes.BoolTT)
        if isinstance(expr, ast.BinaryInfix):
            symbols = "== != < >= > <=".split()
            floatts = (objtypes.FloatTT, objtypes.DoubleTT)
            if expr.opstr in symbols:
                sym2 = symbols[symbols.index(expr.opstr) ^ 1]
                left, right = expr.params
                #be sure not to reverse floating point comparisons since it's not equivalent for NaN
                if expr.opstr in symbols[:2] or (left.dtype not in floatts and right.dtype not in floatts):
                    return ast.BinaryInfix(sym2, (left,right), objtypes.BoolTT)
        elif isinstance(expr, ast.UnaryPrefix) and expr.opstr == '!':
            return expr.params[0]
        return ast.UnaryPrefix('!', expr)

    def _pruneIfElse_cb(self, item):
        for block in item.getScopes():
            if block.jump == (item, False):
                block.setBreak(None)
        if len(item.scopes) > 1:
            #if true block is empty, swap it with false so we can remove it
            tblock, fblock = item.scopes
            if not tblock.statements and tblock.jump == None:
                item.expr = self._reverseBoolExpr(item.expr)
                item.scopes = fblock, tblock
            if not item.scopes[-1].statements and item.scopes[-1].jump == None:
                item.scopes = item.scopes[:-1]
        return item

    def _simplifyBlocks(self, scope):
        newitems = []
        for item in scope.statements:
            for sub in item.getScopes():
                self._simplifyBlocks(sub)

            if isinstance(item, ast.TryStatement):
                item = self._pruneRethrow_cb(item)            
            elif isinstance(item, ast.IfStatement):
                item = self._pruneIfElse_cb(item)

            if isinstance(item, ast.StatementBlock):
                if item.jump:
                    if item.jump[0] == item:
                        item.setBreak(None)
                    elif item is scope.statements[-1] and not item.Sources():
                        assert(scope.jump is None)
                        scope.setBreak(item.jump)
                        item.setBreak(None)

                if not item.jump and not item.Sources():
                    newitems.extend(item.statements)
                    continue
            newitems.append(item)
        scope.statements = newitems        

    def _inlineTryBeginning(self, root):
        info = findVarDeclInfo(root, [])

        def inlineSub(scope):
            newitems = []
            for item in scope.statements:
                for sub in item.getScopes():
                    inlineSub(sub)

                if isinstance(item, ast.TryStatement):
                    tryscope = item.getScopes()[0]
                    for i, stmt in enumerate(tryscope.statements):
                        if isinstance(stmt, ast.ExpressionStatement):
                            if isinstance(stmt.expr, ast.Assignment):
                                left, right = stmt.expr.params
                                if isinstance(right, (ast.Local, ast.Literal)):
                                    if isinstance(left, ast.Local) and info[left].scope != tryscope:
                                        continue 
                        break 
                    newitems.extend(tryscope.statements[:i])
                    tryscope.statements = tryscope.statements[i:]
                newitems.append(item)
            scope.statements = newitems    
        inlineSub(root)
    
    def _setScopeParents(self, scope):
        for item in scope.statements:
            for sub in item.getScopes():
                sub.bases = scope.bases + (sub,)
                self._setScopeParents(sub)

    def _replaceExpressions(self, scope, rdict):
        #Must be done before local declarations are created since it doesn't touch/remove them
        newcontents = []
        for item in scope.statements:
            remove = False
            for subscope in item.getScopes():
                self._replaceExpressions(subscope, rdict)

            try:
                expr = item.expr 
            except AttributeError:
                pass
            else:
                if expr is not None:
                    item.expr = expr.replaceSubExprs(rdict)

            #remove redundant assignments i.e. x=x;
            if isinstance(item, ast.ExpressionStatement) and isinstance(item.expr, ast.Assignment):
                left, right = item.expr.params 
                remove = (left == right)

            if not remove:
                newcontents.append(item) 
        scope.statements = newcontents

    def _mergeVariables(self, root, argumentDecls):
        info = findVarDeclInfo(root, argumentDecls)

        lvars = [expr for expr in info if isinstance(expr, ast.Local)]
        forbidden = set()
        #If var has any defs which aren't a literal or local, mark it as a leaf node (it can't be merged into something)
        for var in lvars:
            if not all(isinstance(expr, (ast.Local, ast.Literal)) for expr in info[var].defs):
                forbidden.add(var)
            elif info[var].declScope is not None:
                forbidden.add(var)

        sccs = graph_util.tarjanSCC(lvars, lambda var:([] if var in forbidden else info[var].defs))
        #the sccs will be in topolgical order
        varmap = {} 
        for scc in sccs:
            if forbidden.isdisjoint(scc):
                alldefs = []
                for expr in scc:
                    for def_ in info[expr].defs:
                        if def_ not in scc:
                            alldefs.append(varmap[def_])
                if len(set(alldefs)) == 1:
                    target = alldefs[0]
                    if all(var.dtype == target.dtype for var in scc):
                        scope = ast.StatementBlock.join(*(info[var].scope for var in scc))
                        scope = ast.StatementBlock.join(scope, info[target].declScope) #scope is unchanged if declScope is none like usual
                        if info[target].declScope is None or info[target].declScope == scope:
                            for var in scc:
                                varmap[var] = target
                            info[target].scope = ast.StatementBlock.join(scope, info[target].scope)
                            continue 
            #fallthrough if merging is impossible
            for var in scc:
                varmap[var] = var
                if len(info[var].defs) > 1:
                    forbidden.add(var)
        self._replaceExpressions(root, varmap)

    def _createDeclarations(self, root, argumentDecls):
        info = findVarDeclInfo(root, argumentDecls)
        localdefs = collections.defaultdict(list)
        newvars = [var for var in info if isinstance(var, ast.Local) and info[var].declScope is None]
        remaining = set(newvars)

        def mdVisitVarUse(var):
            decl = ast.VariableDeclarator(ast.TypeName(var.dtype), var)
            localdefs[info[var].scope].append( ast.LocalDeclarationStatement(decl) )
            remaining.remove(var)

        def mdVisitScope(scope):
            if isinstance(scope, ast.StatementBlock):
                for i,stmt in enumerate(scope.statements):
                    if isinstance(stmt, ast.ExpressionStatement):
                        if isinstance(stmt.expr, ast.Assignment):
                            var, right = stmt.expr.params
                            if var in remaining and scope == info[var].scope:
                                decl = ast.VariableDeclarator(ast.TypeName(var.dtype), var)
                                new = ast.LocalDeclarationStatement(decl, right)
                                scope.statements[i] = new
                                remaining.remove(var)
                    if getattr(stmt,'expr', None) is not None:
                        top = stmt.expr
                        for expr in top.postFlatIter():
                            if expr in remaining:
                                mdVisitVarUse(expr)   
                    for sub in stmt.getScopes():
                        mdVisitScope(sub)

        mdVisitScope(root)
        # print remaining
        assert(not remaining)
        assert(None not in localdefs)
        for scope, ldefs in localdefs.items():
            scope.statements = ldefs + scope.statements

    def _labelReduction(self, scope, breakTarget, continueTarget):
        '''Make breaks and continues unlabeled where possible. Must be called after all code motion and scope pruning'''
        for item in scope.statements:
            newbreak = item if isinstance(item, (ast.WhileStatement, ast.SwitchStatement)) else breakTarget
            newcontinue = item if isinstance(item, ast.WhileStatement) else continueTarget
            
            for subscope in item.getScopes():
                self._labelReduction(subscope, newbreak, newcontinue)

        #Quick hack
        if scope.jump is not None:
            target = scope.jump[0]
            other = continueTarget if scope.jump[1] else breakTarget
            if target == other:
                scope.jump = None, scope.jump[1]           

    def _fixExprStatements(self, scope):
        newitems = []
        for item in scope.statements:
            for sub in item.getScopes():
                self._fixExprStatements(sub)

            if isinstance(item, ast.ExpressionStatement):
                if not isinstance(item.expr, (ast.Assignment, ast.ClassInstanceCreation, ast.MethodInvocation, ast.Dummy)):
                    right = item.expr 
                    left = ast.Local(right.dtype, lambda expr:self.namegen.getPrefix('dummy'))
                    decl = ast.VariableDeclarator(ast.TypeName(left.dtype), left)
                    item = ast.LocalDeclarationStatement(decl, right)
            newitems.append(item)
        scope.statements = newitems        

    def _simplifyExpressions(self, expr):
        truefalse = (ast.Literal.TRUE, ast.Literal.FALSE)

        if hasattr(expr, 'params'):
            expr.params = map(self._simplifyExpressions, expr.params)

        if isinstance(expr, ast.Ternary):
            cond, val1, val2 = expr.params
            if (val1, val2) == truefalse:
                expr = cond 
            elif (val2, val1) == truefalse:
                expr = self._reverseBoolExpr(cond)

        if isinstance(expr, ast.BinaryInfix) and expr.opstr in ('==', '!='):
            v1, v2 = expr.params
            if v1 in truefalse:
                v2, v1 = v1, v2
            if v2 in truefalse:
                match = (v2 == ast.Literal.TRUE) == (expr.opstr == '==')
                expr = v1 if match else self._reverseBoolExpr(v1)
        return expr

    def _createTernaries(self, scope):
        newitems = []
        for item in scope.statements:
            for sub in item.getScopes():
                self._createTernaries(sub)
          
            if isinstance(item, ast.IfStatement):
                assigns = []
                for block in item.getScopes():
                    if block.jump != None and block.jump != (item,False):
                        continue
                    if len(block.statements) != 1:
                        continue                     
                    s = block.statements[0]
                    if isinstance(s, ast.ExpressionStatement):
                        if isinstance(s.expr, ast.Assignment):
                            left, right = s.expr.params
                            if isinstance(left, ast.Local) and right.complexity() <= 1:
                                assigns.append((left, right))
                if len(assigns) == 2 and len(set(zip(*assigns)[0])) == 1:
                    left = zip(*assigns)[0][0]
                    rights = zip(*assigns)[1]
                    tern = ast.Ternary(item.expr, *rights)
                    item = ast.ExpressionStatement(ast.Assignment(left, tern))

            if getattr(item, 'expr', None) is not None:
                item.expr = self._simplifyExpressions(item.expr)

            newitems.append(item)
        scope.statements = newitems        

    def _addCasts(self, scope):
        for item in scope.statements:
            for subscope in item.getScopes():
                self._addCasts(subscope)
            item.addCasts(self.env)

    def _fixObjectCreations(self, scope, copysets=None):
        if copysets is None:
            copysets = []

        newitems = []
        for item in scope.statements:
            remove = False
            for sub in item.getScopes():
                self._fixObjectCreations(sub, copysets)

            if isinstance(item, ast.ExpressionStatement):
                expr = item.expr

                if isinstance(expr, ast.Assignment):
                    left, right = expr.params
                    if isinstance(right, ast.Dummy) and right.isNew:
                        copysets.append([left])
                        remove = True
                    elif isinstance(right, ast.Local):
                        hits = [x for x in copysets if right in x or left in x]
                        if hits:
                            new = list(itertools.chain(*hits))
                            new.append(left)
                            copysets[:] = [x for x in copysets if x not in hits] + [new]
                            remove = True
                elif isinstance(expr, ast.MethodInvocation) and expr.name == '<init>':
                    left = expr.params[0]
                    newexpr = ast.ClassInstanceCreation(ast.TypeName(left.dtype), expr.tts[1:], expr.params[1:])
                    newexpr = ast.Assignment(left, newexpr)
                    item.expr = newexpr
                    
                    temp = set([left])
                    copyset = [x for x in copysets if left in x][0]
                    copyset = [x for x in copyset if not x in temp and not temp.add(x)]
                    copysets[:] = [x for x in copysets if left not in x]

                    newitems.append(item)
                    for other in copyset:
                        newitems.append(ast.ExpressionStatement(ast.Assignment(other, left)))
                    remove = True

            if not remove:
                newitems.append(item)
        scope.statements = newitems 

    def _pruneVoidReturn(self, scope):
        if scope.statements:
            last = scope.statements[-1]
            if isinstance(last, ast.ReturnStatement) and last.expr is None:
                scope.statements.pop()

    def generateAST(self):
        method = self.method
        class_ = method.class_
        inputTypes = parseMethodDescriptor(method.descriptor, unsynthesize=False)[0]
        tts = objtypes.verifierToSynthetic_seq(inputTypes) 

        if self.graph is not None:
            blocks, argvars = preprocess.makeGraphCopy(self.env, self.graph)
            blocks, entryBlock, handlerInfos = preprocess.structureCFG(blocks, blocks[0])

            if not method.static:
                argvars[0].name = 'this'
            self.varinfo = preprocess.addDecInfo(self.env, blocks)
            for var, info in self.varinfo.items():
                if var.type != ssa_types.SSA_MONAD:
                    info.expr = ssavarToExpr(var, info.atype, self.namegen)

            temp = set(self.varinfo)
            for block in blocks:
                for line in block.lines:
                    assert(temp.issuperset(line.params))
                assert(temp.issuperset(block.jump.params))

            argsources = [self.varinfo[var].expr for var in argvars]
            disp_args = argsources if method.static else argsources[1:] 
            for expr, tt in zip(disp_args, tts):
                expr.dtype = tt

            decls = [ast.VariableDeclarator(ast.TypeName(expr.dtype), expr) for expr in disp_args]
            ##############################################################################################
            root = createSETree(self, blocks, entryBlock, handlerInfos)
            ast_root = self._createAST(root, (), None)
            ast_root.bases = (ast_root,)

            self._simplifyBlocks(ast_root)
            self._setScopeParents(ast_root)
            self._inlineTryBeginning(ast_root)
            boolize.boolizeVars(ast_root, argsources)
            self._fixObjectCreations(ast_root)

            self._setScopeParents(ast_root)
            self._mergeVariables(ast_root, decls)
            self._createTernaries(ast_root)
            self._simplifyBlocks(ast_root)

            self._setScopeParents(ast_root)
            self._createDeclarations(ast_root, decls)
            self._fixExprStatements(ast_root)
            self._addCasts(ast_root)
            # self._createTernaries(ast_root)
            # self._simplifyBlocks(ast_root)

            self._labelReduction(ast_root, None, None)
            self._pruneVoidReturn(ast_root)
        else: #abstract or native method
            ast_root = None
            argsources = [ast.Local(tt, lambda expr:self.namegen.getPrefix('arg')) for tt in tts]
            decls = [ast.VariableDeclarator(ast.TypeName(expr.dtype), expr) for expr in argsources]

        flags = method.flags - set(['BRIDGE','SYNTHETIC','VARARGS'])    
        if method.name == '<init>': #More arbtirary restrictions. Yay!
            flags = flags - set(['ABSTRACT','STATIC','FINAL','NATIVE','STRICTFP','SYNCHRONIZED'])

        flagstr = ' '.join(map(str.lower, sorted(flags)))
        inputTypes, returnTypes = parseMethodDescriptor(method.descriptor, unsynthesize=False)
        ret_tt = objtypes.verifierToSynthetic(returnTypes[0]) if returnTypes else ('.void',0)
        return ast2.MethodDef(class_, flagstr, method.name, ast.TypeName(ret_tt), decls, ast_root)