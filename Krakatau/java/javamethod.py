import collections

from ..ssa import objtypes
from .. import graph_util
from ..namegen import NameGen, LabelGen
from ..verifier.descriptors import parseMethodDescriptor

from . import ast, ast2, boolize
from . import graphproxy, structuring, astgen

class DeclInfo(object):
    __slots__ = "declScope scope defs".split()
    def __init__(self):
        self.declScope = self.scope = None 
        self.defs = []

def findVarDeclInfo(root, predeclared):
    info = collections.OrderedDict()
    def visit(scope, expr):
        for param in expr.params:
            visit(scope, param)

        if isinstance(expr, ast.Assignment):
            left, right = expr.params
            if isinstance(left, ast.Local):
                info[left].defs.append(right)
        elif isinstance(expr, (ast.Local, ast.Literal)):
            #this would be so much nicer if we had Ordered defaultdicts
            info.setdefault(expr, DeclInfo())
            info[expr].scope = ast.StatementBlock.join(info[expr].scope, scope)

    def visitDeclExpr(scope, expr): 
        info.setdefault(expr, DeclInfo())
        assert(scope is not None and info[expr].declScope is None)
        info[expr].declScope = scope 

    for expr in predeclared:
        visitDeclExpr(root, expr)

    stack = [(root,root)]
    while stack:
        scope, stmt = stack.pop()
        if isinstance(stmt, ast.StatementBlock):
            stack.extend((stmt,sub) for sub in stmt.statements)
        else:
            stack.extend((subscope,subscope) for subscope in stmt.getScopes())
            #temp hack
            if stmt.expr is not None:
                visit(scope, stmt.expr)
            if isinstance(stmt, ast.TryStatement):
                for catchdecl, body in stmt.pairs:
                    visitDeclExpr(body, catchdecl.local)
    return info

def reverseBoolExpr(expr):
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

class MethodDecompiler(object):
    def __init__(self, method, graph, forbidden_identifiers):
        self.env = method.class_.env
        self.method, self.graph = method, graph
        self.namegen = NameGen(forbidden_identifiers)
        self.labelgen = LabelGen().next

    def _preorder(self, scope, func):
        newitems = []
        for i, item in enumerate(scope.statements):
            for sub in item.getScopes():
                self._preorder(sub, func)

            val = func(scope, item)
            vals = [item] if val is None else val
            newitems.extend(vals)
        scope.statements = newitems

    def _fixObjectCreations(self, scope, copyset_stack=(), copyset={}):
        '''Combines new/invokeinit pairs into Java constructor calls'''

        # There are two main data structures used in this function

        # Copyset: dict(var -> tuple(var)) gives the variables that a 
        # given new object has been assigned to. Copysets are copied on
        # modification, so can freely be shared. 
        # Intersection identity (universe) represented by None

        # Copyset Stack: tuple(item -> copyset) gives for each
        # scope-containing item, the intersection of all copysets 
        # representing paths of execution which jump to after that item. 
        # None if no paths jump to that item

        def mergeCopysets(csets1, csets2):
            if csets1 is None:
                return csets2
            elif csets2 is None:
                return csets1

            keys = [k for k in csets1 if k in csets2]
            return {k:tuple(x for x in csets1[k] if x in csets2[k]) for k in keys}

        def mergeCopysetList(csets):
            #Can't just pass None as initializer since reduce treats it as the default value
            return reduce(mergeCopysets, csets) if csets else None

        newitems = []
        for item in scope.statements:
            remove = False

            if item.getScopes():
                newstack = copyset_stack + ((item,None),)
                items = zip(*newstack)[0]

                #Check if item may not be executed (eg. if with no else)
                mayskip = isinstance(item, ast.IfStatement) and len(item.getScopes()) < 2
                mayskip = mayskip or isinstance(item, ast.SwitchStatement) and None not in zip(*item.pairs)[0]
                oldcopyset = copyset

                returned_stacks = []
                passed_cset = copyset
                for sub in item.getScopes():
                    returned_stack, fallthrough_cset = self._fixObjectCreations(sub, newstack, passed_cset)
                    returned_stacks.append(returned_stack)
                    passed_cset = mergeCopysets(passed_cset, fallthrough_cset)

                assert(returned_stacks[0])
                assert(zip(*returned_stacks[0])[0] == items)

                csetonly_stacks = [zip(*stack)[1] for stack in returned_stacks]
                copyset_lists = zip(*csetonly_stacks)
                joins = map(mergeCopysetList, copyset_lists)
                assert(len(joins) == len(items))
                merged_stack = zip(items, joins)

                copyset = merged_stack.pop()[1]
                copyset_stack = tuple(merged_stack)
                if mayskip:
                    copyset = mergeCopysets(copyset, oldcopyset)
                
                if copyset is None: #In this case, every one of the subscopes breaks, meaning that whatever follows this item is unreachable
                    assert(item is scope.statements[-1])

            #Nothing after this is reachable
            #Todo - add handling for merging across a thrown exception
            if isinstance(item, (ast.ReturnStatement, ast.ThrowStatement)):
                assert(item is scope.statements[-1])
                copyset = None

            #Todo - handle conditional statements that can also have an expression (if, switch, while)
            #Not currently necessary as we'll never generate such statement expressions containing constructor calls
            if isinstance(item, ast.ExpressionStatement):
                expr = item.expr

                if isinstance(expr, ast.Assignment):
                    left, right = expr.params
                    if isinstance(right, ast.Dummy) and right.isNew:
                        assert(left not in copyset)
                        copyset = copyset.copy()
                        copyset[left] = left,
                        remove = True

                    elif isinstance(right, ast.Local):
                        assert(left not in copyset)
                        hits = [(k,v) for k,v in copyset.items() if right in v]
                        if hits:
                            assert(len(hits)==1)
                            assert(isinstance(left, ast.Local))
                            k, v = hits[0]
                            copyset = copyset.copy()
                            copyset[k] = v + (left,)
                            remove = True

                elif isinstance(expr, ast.MethodInvocation) and expr.name == '<init>':
                    left = expr.params[0]
                    newexpr = ast.ClassInstanceCreation(ast.TypeName(left.dtype), expr.tts[1:], expr.params[1:])
                    newexpr = ast.Assignment(left, newexpr)
                    item.expr = newexpr
                    
                    hits = [(k,v) for k,v in copyset.items() if left in v]
                    assert(len(hits)==1)
                    k, v = hits[0]

                    newitems.append(item)
                    for other in v:
                        newitems.append(ast.ExpressionStatement(ast.Assignment(other, left)))

                    copyset = dict(kv for kv in copyset.items() if kv not in hits)
                    remove = True
            if  not remove:
                newitems.append(item)

        scope.statements = newitems 
        if copyset_stack: #if it is empty, we are at the root level and can't return anything
            fallthrough_cset = None

            if scope.canFallthrough():
                target = copyset_stack[-1][0]
                assert(scope in target.getScopes())

                #In this case, the fallthrough goes back to the beginning of the loop, not after it
                if isinstance(target, ast.WhileStatement):
                    target = None
                #Switch fallthrough case
                elif isinstance(target, ast.SwitchStatement) and scope is not target.getScopes()[-1]:
                    target = None
                    fallthrough_cset = copyset
            else:
                jumps = [x[0] for x in scope.jumps if x is not None and not x[1]]
                target = jumps[-1] if jumps else None

            if target is not None:
                keys = zip(*copyset_stack)[0]
                ind = keys.index(target)
                new_pair = target, mergeCopysets(copyset_stack[ind][1], copyset)
                copyset_stack = copyset_stack[:ind] + (new_pair,) + copyset_stack[ind+1:]
            return copyset_stack, fallthrough_cset

    def _pruneRethrow_cb(self, item):
        '''Convert try{A} catch(T e) {throw t;} to {A}'''
        while item.pairs:
            decl, body = item.pairs[-1]
            caught, lines = decl.local, body.statements

            if len(lines) == 1:
                line = lines[0]
                if isinstance(line, ast.ThrowStatement) and line.expr == caught:
                    body.setBreaks([])
                    item.pairs = item.pairs[:-1]
                    continue
            break
        if not item.pairs:
            new = item.tryb
            assert(not new.getSources())

            for x in item.getSources():
                x.removeJump((item, False))
                x.addJump((new, False))
            assert(not item.getSources())
            return new
        return item    

    def _pruneIfElse_cb(self, item):
        '''Convert if(A) {B} else {} to if(A) {B}'''
        for block in item.getScopes():
            if not block.canFallthrough() and (item, False) in block.jumps:
                block.addJump(None)
        if len(item.scopes) > 1:
            #if true block is empty, swap it with false so we can remove it
            tblock, fblock = item.scopes

            if not tblock.statements and tblock.canFallthrough():
                item.expr = reverseBoolExpr(item.expr)
                item.scopes = fblock, tblock

            if not item.scopes[-1].statements and item.scopes[-1].canFallthrough():
                item.scopes[-1].setBreaks([])
                item.scopes = item.scopes[:-1]
        return item

    def _whileCondition_cb(self, item):
        '''Convert while(true) {if(A) {B break;} else {C} D} to while(!A) {{C} D} {B}'''
        def getSubscopeIter(root):
            stack = [root]
            while stack:
                scope = stack.pop()
                if isinstance(scope, ast.StatementBlock):
                    stack.extend(scope.statements)
                    yield scope
                else:
                    stack.extend(scope.getScopes())

        failure = [], item #what to return if we didn't inline
        body = item.getScopes()[0]
        if not body.statements or not isinstance(body.statements[0], ast.IfStatement):
            return failure

        head = body.statements[0]
        cond = head.expr 
        trueb, falseb = (head.getScopes() + (None,))[:2]

        if falseb is not None and (item, False) in falseb.jumps:
            cond = reverseBoolExpr(cond)
            trueb, falseb = falseb, trueb

        if item.expr != ast.Literal.TRUE or (item, False) not in trueb.jumps:
            return failure
        true_scopes = list(getSubscopeIter(trueb))
        assert(true_scopes.pop(0) == trueb)
        badjumps = frozenset([(item, True), (head, False)])
        if any(badjumps.issuperset(s.jumps) for s in true_scopes):
            return failure

        #Now we can actually do the inlining
        #First remove any jumps there may be to after the if statement
        false_scopes = [] if falseb is None else list(getSubscopeIter(falseb))
        for block, scopes in [(trueb, true_scopes), (falseb, false_scopes)]:
            for scope in scopes:
                if (head, False) in scope.jumps:
                    scope.removeJump((head, False))
                    scope.addJump((block, False))
        trueb.setBreaks([None])
        assert(not head.getSources())

        #Inline everything
        item.expr = reverseBoolExpr(cond)
        body.statements[0] = falseb
        if falseb is None:
            body.statements.pop(0)
        return [item], trueb

    def _simplifyBlocks(self, scope, item):
        rest = []
        if isinstance(item, ast.TryStatement):
            item = self._pruneRethrow_cb(item)            
        elif isinstance(item, ast.IfStatement):
            item = self._pruneIfElse_cb(item)
        elif isinstance(item, ast.WhileStatement):
            rest, item = self._whileCondition_cb(item)

        if isinstance(item, ast.StatementBlock):
            #If item jumps to immediately after item, change it to fallthrough
            if not item.canFallthrough() and (item, False) in item.jumps:
                item.addJump(None)

            assert(not item.sources[True]) #can only happen if item is a while loop
            if item is scope.statements[-1]:
                if item.canFallthrough():
                    for jump in scope.jumps:
                        if jump not in item.jumps:
                            item.addJump(jump)
                elif scope.getSources(): # Make sure it isn't a forcibly unlabeled scope
                    for child in item.getSources():
                        child.removeJump((item, False))
                        if (scope, False) not in child.jumps:
                            child.addJump((scope, False))

                if not item.canFallthrough() and not item.hasDependents():
                    assert((item, False) not in item.jumps)
                    # don't bother removing item from children jumps since it will be done after inlining
                    scope.setBreaks(item.jumps)
                    item.setBreaks([None])

            #Inline the block if possible
            if item.canFallthrough() and not item.hasDependents():
                for child in item.getSources():
                    child.removeJump((item, False))
                item.setBreaks([])
                return rest + item.statements
        return rest + [item]
    
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

    def _mergeVariables(self, root, predeclared):
        info = findVarDeclInfo(root, predeclared)

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
        self._replaceExpressions(root, varmap)

    def _inlineVariables(self, root):
        #first find all variables with a single def and use
        defs = collections.defaultdict(list)
        uses = collections.defaultdict(int)

        def visitExprFindDefs(expr):
            if isinstance(expr, ast.Assignment): 
                left, right = expr.params
                if isinstance(left, ast.Local):
                    defs[left].append(expr)
            elif isinstance(expr, ast.Local):
                uses[expr] += 1

        def visitFindDefs(scope, item):
            if item.expr is not None:
                stack = [item.expr]
                while stack:
                    expr = stack.pop()
                    visitExprFindDefs(expr)
                    stack.extend(expr.params)

        self._preorder(root, visitFindDefs)
        #These should have 2 uses since the initial assignment also counts
        temp = {v[0] for k,v in defs.items() if len(v)==1 and uses[k]==2 and k.dtype == v[0].params[1].dtype} 
        replacevars = {k for k,v in defs.items() if len(v)==1 and uses[k]==2 and k.dtype == v[0].params[1].dtype} 
        # import pdb;pdb.set_trace()

        #Avoid reordering past expressions that potentially have side effects or depend on external state
        oktypes = ast.BinaryInfix, ast.Local, ast.Literal, ast.Parenthesis, ast.TypeName, ast.UnaryPrefix
        def isBarrier(expr):
            if not isinstance(expr, oktypes):
                return True
            #check for division by 0. If it's a float or dividing by nonzero literal, it's ok
            elif isinstance(expr, ast.BinaryInfix) and expr.opstr in ('/','%'):
                if expr.dtype not in (objtypes.FloatTT, objtypes.DoubleTT):
                    divisor = expr.params[-1]
                    if not isinstance(divisor, ast.Literal) or divisor.val == 0:
                        return True
            return False

        def doReplacement(item, pairs):
            old, new = item.expr.params
            assert(isinstance(old, ast.Local) and old.dtype == new.dtype)

            stack = [(True, (True, item2, expr)) for item2, expr in reversed(pairs) if expr is not None]
            while stack:
                recurse, args = stack.pop()

                if recurse:
                    canReplace, parent, expr = args
                    stack.append((False, expr))

                    #For ternaries, we don't want to replace into the conditionally
                    #evaluated part, but we still need to check those parts for 
                    #barriers
                    if isinstance(expr, ast.Ternary):
                        stack.append((True, (False, expr, expr.params[2])))
                        stack.append((True, (False, expr, expr.params[1])))
                        stack.append((True, (True, expr, expr.params[0])))
                    else:
                        for param in reversed(expr.params):
                            stack.append((True, (True, expr, param)))

                    if expr == old:
                        if canReplace:
                            if isinstance(parent, ast.JavaExpression):
                                params = parent.params = list(parent.params)
                                params[params.index(old)] = new
                            else: #replacing in a top level statement
                                assert(parent.expr == old)
                                parent.expr = new
                        return canReplace
                else:
                    expr = args
                    if isBarrier(expr):
                        return False
            return False

        def visitReplace(scope):
            newstatements = []
            for item in reversed(scope.statements):
                for sub in item.getScopes():
                    visitReplace(sub)

                if isinstance(item.expr, ast.Assignment) and item.expr.params[0] in replacevars:
                    expr_roots = []
                    for item2 in newstatements:
                        #Don't inline into a while condition as it may be evaluated more than once
                        if not isinstance(item2, ast.WhileStatement):
                            expr_roots.append((item2, item2.expr))
                        if item2.getScopes():
                            break
                    success = doReplacement(item, expr_roots)
                    if success:
                        continue
                newstatements.insert(0, item)
            scope.statements = newstatements
        visitReplace(root)

    def _createDeclarations(self, root, predeclared):
        info = findVarDeclInfo(root, predeclared)
        localdefs = collections.defaultdict(list)
        newvars = [var for var in info if isinstance(var, ast.Local) and info[var].declScope is None]
        remaining = set(newvars)

        #The compiler treats statements as if they can throw any exception at any time, so
        #it may think variables are not definitely assigned even when they really are. 
        #Therefore, we give an unused initial value to every variable declaration
        #TODO - find a better way to handle this
        _init_d = {objtypes.BoolTT: ast.Literal.FALSE,
                objtypes.IntTT: ast.Literal.ZERO,
                objtypes.FloatTT: ast.Literal.FZERO,
                objtypes.DoubleTT: ast.Literal.DZERO}
        def mdVisitVarUse(var):
            decl = ast.VariableDeclarator(ast.TypeName(var.dtype), var)
            right = _init_d.get(var.dtype, ast.Literal.NULL)
            localdefs[info[var].scope].append( ast.LocalDeclarationStatement(decl, right) )
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
                    if stmt.expr is not None:
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

    def _simplifyExpressions(self, expr):
        truefalse = (ast.Literal.TRUE, ast.Literal.FALSE)
        expr.params = map(self._simplifyExpressions, expr.params)

        if isinstance(expr, ast.Ternary):
            cond, val1, val2 = expr.params
            if (val1, val2) == truefalse:
                expr = cond 
            elif (val2, val1) == truefalse:
                expr = reverseBoolExpr(cond)
            elif isinstance(cond, ast.UnaryPrefix): # (!x)?y:z -> x?z:y
                expr.params = reverseBoolExpr(cond), val2, val1

        if isinstance(expr, ast.BinaryInfix) and expr.opstr in ('==', '!='):
            v1, v2 = expr.params
            if v1 in truefalse:
                v2, v1 = v1, v2
            if v2 in truefalse:
                match = (v2 == ast.Literal.TRUE) == (expr.opstr == '==')
                expr = v1 if match else reverseBoolExpr(v1)
            # Fix Yoda comparisons (if(null == x), etc.
            elif isinstance(v1, ast.Literal):
                expr.params = v2, v1
        return expr

    def _createTernaries(self, scope, item):
        olditem = item
        if isinstance(item, ast.IfStatement) and len(item.getScopes()) == 2:
            block1, block2 = item.getScopes()
            if (len(block1.statements) == len(block2.statements) == 1):

                jumps = [j for j in block1.jumps if j in block2.jumps]
                if jumps:
                    s1, s2 = block1.statements[0], block2.statements[0]
                    e1, e2 = s1.expr, s2.expr

                    if isinstance(s1, ast.ReturnStatement) and isinstance(s2, ast.ReturnStatement):
                        expr = None if e1 is None else ast.Ternary(item.expr, e1, e2)
                        item = ast.ReturnStatement(expr, s1.tt)
                    if isinstance(s1, ast.ExpressionStatement) and isinstance(s2, ast.ExpressionStatement):
                        if isinstance(e1, ast.Assignment) and isinstance(e2, ast.Assignment):
                            # if e1.params[0] == e2.params[0] and max(e1.params[1].complexity(), e2.params[1].complexity()) <= 1:
                            if e1.params[0] == e2.params[0]:
                                expr = ast.Ternary(item.expr, e1.params[1], e2.params[1])
                                temp = ast.ExpressionStatement(ast.Assignment(e1.params[0], expr))

                                if None not in jumps:
                                    assert((olditem, False) not in jumps)
                                    item = ast.StatementBlock(olditem.func)
                                    item.setBreaks(jumps)
                                    item.statements = [temp]
                                else:
                                    item = temp

                    if item is not olditem:
                        block1.setBreaks([])
                        block2.setBreaks([])

        if item.expr is not None:
            item.expr = self._simplifyExpressions(item.expr)
        return [item]

    def _fixExprStatements(self, scope, item):
        if isinstance(item, ast.ExpressionStatement):
            if not isinstance(item.expr, (ast.Assignment, ast.ClassInstanceCreation, ast.MethodInvocation, ast.Dummy)):
                right = item.expr 
                left = ast.Local(right.dtype, lambda expr:self.namegen.getPrefix('dummy'))
                decl = ast.VariableDeclarator(ast.TypeName(left.dtype), left)
                item = ast.LocalDeclarationStatement(decl, right)
        return [item]

    def _addCastsAndParens(self, scope, item):
        item.addCastsAndParens(self.env)

    def _jumpReduction(self, scope, breakTarget, continueTarget, fallthroughs):
        '''Make breaks and continues unlabeled or remove them where possible. Must be called after all code motion and scope pruning'''
        fallthroughs = fallthroughs + ((scope, False),)
        lastchild_fts = tuple(scope.jumps)
        if None in lastchild_fts:
            lastchild_fts += fallthroughs

        # for jumps in (scope.jumps, fallthroughs):
        #     parts = [('{}_{}'.format(t[0].getLabel(),int(t[1])) if t else 'None') for t in jumps]
        #     scope.statements.insert(0, ast.StringStatement('// ' + ', '.join(parts)))

        if scope.canFallthrough() or (set(fallthroughs) & set(scope.jumps)):
            scope.setBreaks([None])
        else: #see if we can use a bare break or continue
            # add it manually rather than going through addJump so it doesn't try to add a source to None
            if (breakTarget, False) in scope.jumps:
                scope.setBreaks([])
                scope.jumps = [(None, False)]
            elif (continueTarget, True) in scope.jumps:
                scope.setBreaks([])
                scope.jumps = [(None, True)]
            else:
                # Try to find a target that already must be labeled
                for jump in scope.jumps:
                    if jump[0].hasDependents():
                        choice = jump
                        break
                else:
                    choice = scope.jumps[-1]
                scope.setBreaks([choice])

        for i,item in enumerate(scope.statements):
            newbreak = item if isinstance(item, (ast.WhileStatement, ast.SwitchStatement)) else breakTarget
            newcontinue = item if isinstance(item, ast.WhileStatement) else continueTarget

            newft = ()
            if i == len(scope.statements)-1:
                newft = lastchild_fts
                if isinstance(item, (ast.TryStatement, ast.IfStatement)):
                    newft += (item, False),
                elif isinstance(item, ast.WhileStatement):
                    newft = (item, True),

            for subscope in item.getScopes():
                self._jumpReduction(subscope, newbreak, newcontinue, newft)

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
            entryNode, nodes = graphproxy.createGraphProxy(self.graph)
            if not method.static:
                entryNode.invars[0].name = 'this'

            setree = structuring.structure(entryNode, nodes, (method.name == '<clinit>'))
            ast_root, varinfo = astgen.createAST(method, self.graph, setree, self.namegen)

            argsources = [varinfo.var(entryNode, var) for var in entryNode.invars]
            disp_args = argsources if method.static else argsources[1:] 
            for expr, tt in zip(disp_args, tts):
                expr.dtype = tt

            decls = [ast.VariableDeclarator(ast.TypeName(expr.dtype), expr) for expr in disp_args]
            ################################################################################################
            ast_root.bases = (ast_root,) #needed for our setScopeParents later

            # print ast_root.print_()
            self._fixObjectCreations(ast_root)
            self._preorder(ast_root, self._simplifyBlocks)
            self._setScopeParents(ast_root)
            boolize.boolizeVars(ast_root, argsources)

            self._setScopeParents(ast_root)
            self._mergeVariables(ast_root, argsources)
            self._preorder(ast_root, self._createTernaries)

            self._inlineVariables(ast_root)
            self._preorder(ast_root, self._simplifyBlocks)
            self._preorder(ast_root, self._createTernaries)
            self._inlineVariables(ast_root)
            self._preorder(ast_root, self._simplifyBlocks)

            self._setScopeParents(ast_root)
            self._createDeclarations(ast_root, argsources)
            self._preorder(ast_root, self._fixExprStatements)
            self._preorder(ast_root, self._addCastsAndParens)

            self._jumpReduction(ast_root, None, None, ())
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