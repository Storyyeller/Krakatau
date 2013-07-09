from . import ast
from .setree import SEBlockItem, SEScope, SEIf, SESwitch, SETry, SEWhile
from ..ssa import ssa_types, ssa_ops, ssa_jumps
from ..ssa import objtypes
from ..namegen import LabelGen
from ..verifier.descriptors import parseFieldDescriptor, parseMethodDescriptor
from .. import opnames

#prefixes for name generation
_prefix_map = {objtypes.IntTT:'i', objtypes.LongTT:'j',
            objtypes.FloatTT:'f', objtypes.DoubleTT:'d',
            objtypes.BoolTT:'b', objtypes.StringTT:'s'}

_ssaToTT = {ssa_types.SSA_INT:objtypes.IntTT, ssa_types.SSA_LONG:objtypes.LongTT,
            ssa_types.SSA_FLOAT:objtypes.FloatTT, ssa_types.SSA_DOUBLE:objtypes.DoubleTT}
class VarInfo(object):
    def __init__(self, method, blocks, namegen):
        self.env = method.class_.env
        self.labelgen = LabelGen().next

        returnTypes = parseMethodDescriptor(method.descriptor, unsynthesize=False)[-1]
        self.return_tt = objtypes.verifierToSynthetic(returnTypes[0]) if returnTypes else None
        self.clsname = method.class_.name
        self._namegen = namegen

        self._vars = {}
        self._tts = {}
        for block in blocks:
            for var, uc in block.unaryConstraints.items():
                if var.type == ssa_types.SSA_MONAD:
                    continue

                if var.type == ssa_types.SSA_OBJECT:
                    tt = uc.getSingleTType() #temp hack
                    if tt[1] == objtypes.ObjectTT[1] and uc.types.isBoolOrByteArray():
                        tt = '.bexpr', tt[1]+1
                else:
                    tt = _ssaToTT[var.type]
                self._tts[var] = tt

    def _nameCallback(self, expr):
        prefix = _prefix_map.get(expr.dtype, 'a')
        return self._namegen.getPrefix(prefix)

    def _newVar(self, var, num):
        tt = self._tts[var]
        if var.const is not None:
            return ast.Literal(tt, var.const)
        else:
            if var.name:
                #important to not add num when it is 0, since we currently 
                #use var names to force 'this'
                temp = '{}_{}'.format(var.name, num) if num else var.name
                namefunc = lambda expr:temp
            else:
                namefunc = self._nameCallback
            return ast.Local(tt, namefunc)   

    def var(self, node, var):
        assert(var.type != ssa_types.SSA_MONAD)
        try:
            return self._vars[var, node.num]
        except KeyError:
            self._vars[var, node.num] = new = self._newVar(var, node.num)
            return new

    def customVar(self, tt, prefix): #for use with ignored exceptions
        namefunc = lambda expr: self._namegen.getPrefix(prefix)
        return ast.Local(tt, namefunc)

#########################################################################################
_math_types = (ssa_ops.IAdd, ssa_ops.IDiv, ssa_ops.IMul, ssa_ops.IRem, ssa_ops.ISub)
_math_types += (ssa_ops.IAnd, ssa_ops.IOr, ssa_ops.IShl, ssa_ops.IShr, ssa_ops.IUshr, ssa_ops.IXor)
_math_types += (ssa_ops.FAdd, ssa_ops.FDiv, ssa_ops.FMul, ssa_ops.FRem, ssa_ops.FSub)
_math_symbols = dict(zip(_math_types, '+ / * % - & | << >> >>> ^ + / * % -'.split()))
def _convertJExpr(op, getExpr, clsname):
    params = [getExpr(var) for var in op.params if var.type != ssa_types.SSA_MONAD]
    assert(None not in params)
    expr = None

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

        if op.instruction[0] in (opnames.GETSTATIC, opnames.PUTSTATIC):
            printLeft = (op.target != clsname) #Don't print classname if it is a static field in current class
            tt = op.target, 0
            expr = ast.FieldAccess(ast.TypeName(tt), op.name, dtype, printLeft=printLeft)
        else:
            expr = ast.FieldAccess(params[0], op.name, dtype)

        if op.instruction[0] in (opnames.PUTFIELD, opnames.PUTSTATIC):
            expr = ast.Assignment(expr, params[-1])

    elif isinstance(op, ssa_ops.FNeg):
        expr = ast.UnaryPrefix('-', params[0])    
    elif isinstance(op, ssa_ops.InstanceOf):
        args = params[0], ast.TypeName(op.target_tt)
        expr = ast.BinaryInfix('instanceof', args, dtype=objtypes.BoolTT)
    elif isinstance(op, ssa_ops.Invoke):            
        vtypes, rettypes = parseMethodDescriptor(op.desc, unsynthesize=False)
        tt_types = objtypes.verifierToSynthetic_seq(vtypes)
        ret_type = objtypes.verifierToSynthetic(rettypes[0]) if rettypes else None 

        if op.instruction[0] == opnames.INVOKEINIT and op.isThisCtor:
            name = 'this' if (op.target == clsname) else 'super'
            expr = ast.MethodInvocation(None, name, tt_types, params[1:], op, ret_type)
        elif op.instruction[0] == opnames.INVOKESTATIC: #TODO - fix this for special super calls
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
        if isinstance(op, ssa_ops.TryReturn):
            return None #Don't print out anything
        else:
            return ast.StringStatement('//' + type(op).__name__)
    return ast.ExpressionStatement(expr)

#########################################################################################
def _createASTBlock(info, node, breakmap):
    getExpr = lambda var: info.var(node, var)
    op2expr = lambda op: _convertJExpr(op, getExpr, info.clsname)

    block = node.block
    lines = map(op2expr, block.lines) if block else []
    lines = [x for x in lines if x is not None]

    eassigns = []
    nassigns = []
    for n2 in node.successors:
        assert((n2 in node.outvars) != (n2 in node.eassigns))
        if n2 in node.eassigns:
            for outv, inv in zip(node.eassigns[n2], n2.invars):
                if outv is None: #this is how we mark the thrown exception, which 
                    #obviously doesn't get an explicit assignment statement
                    continue
                expr = ast.Assignment(info.var(n2, inv), info.var(node, outv))
                eassigns.append(ast.ExpressionStatement(expr))        
        else:
            for outv, inv in zip(node.outvars[n2], n2.invars):
                expr = ast.Assignment(info.var(n2, inv), info.var(node, outv))
                nassigns.append(ast.ExpressionStatement(expr))

    #Need to put exception assignments before last statement, which might throw
    #While normal assignments must come last as they may depend on it
    statements = lines[:-1] + eassigns + lines[-1:] + nassigns

    norm_successors = node.normalSuccessors()
    jump = None if block is None else block.jump
    jumps = [None]
    if isinstance(jump, (ssa_jumps.Rethrow, ssa_jumps.Return)):
        assert(not norm_successors)
        if isinstance(jump, ssa_jumps.Rethrow):
            param = info.var(node, jump.params[-1])
            statements.append(ast.ThrowStatement(param))
        else:
            if len(jump.params)>1: #even void returns have a monad param
                param = info.var(node, jump.params[-1])
                statements.append(ast.ReturnStatement(param, info.return_tt))
            else:
                statements.append(ast.ReturnStatement())
    elif len(norm_successors) == 1: #normal successors 
        #explicit or implicit goto (or exception with fallthrough)
        jumps = [y for x,y in breakmap if x == norm_successors[0]]
    #case of if and switch jumps handled in parent scope

    new = ast.StatementBlock(info.labelgen)
    new.statements = statements
    new.setBreaks(jumps)
    assert(None not in statements)
    return new

def _createASTSub(info, seroot):
    # The basic pattern is to create a node, recurse of the children, collect the results,
    # assign them back to the parent AST node, and return. The first boolean in each stack
    # value indicates whether it is before or after recursing

    result = []
    stack = [(True, (seroot, (), None, True, result.append))]
    while stack:
        before, data = stack.pop()
        if before:
            current, targets, ftblock, forceUnlabled, ret_cb = data
            contents = []

            calls = []
            def recurse(item, targets, ftblock, forceUnlabled=False):
                calls.append((True, (item, targets, ftblock, forceUnlabled, contents.append)))

            new = None #catch error if we forget to assign it in one case
            if isinstance(current, SEScope):
                new = ast.StatementBlock(info.labelgen)
                if not forceUnlabled:
                    targets = targets + ((ftblock, (new,False)),)

                fallthroughs = [item.entryBlock for item in current.items[1:]] + [ftblock]
                for item, ft in zip(current.items, fallthroughs):
                    recurse(item, targets, ft)

            elif isinstance(current, SEWhile):
                new = ast.WhileStatement(info.labelgen)
                targets = targets + ((current.entryBlock, (new,True)), (ftblock, (new,False)))
                recurse(current.body, targets, current.entryBlock, True)

            elif isinstance(current, SETry):
                new = ast.TryStatement(info.labelgen)
                targets = targets + ((ftblock, (new,False)),)
                for scope in current.getScopes():
                    recurse(scope, targets, ftblock, True)

            elif isinstance(current, SEIf):
                node = current.head.node
                jump = node.block.jump

                cmp_strs = dict(zip(('eq','ne','lt','ge','gt','le'), "== != < >= > <=".split()))
                cmp_str = cmp_strs[jump.cmp]
                exprs = [info.var(node, var) for var in jump.params]
                ifexpr = ast.BinaryInfix(cmp_str, exprs, objtypes.BoolTT)

                new = ast.IfStatement(info.labelgen, ifexpr)
                targets = targets + ((ftblock, (new,False)),)
                for scope in current.getScopes():
                    recurse(scope, targets, ftblock, True)
                
            elif isinstance(current, SESwitch):
                node = current.head.node
                jump = node.block.jump
                expr = info.var(node, jump.params[0])
                new = ast.SwitchStatement(info.labelgen, expr)
                targets = targets + ((ftblock, (new,False)),)

                fallthroughs = [item.entryBlock for item in current.ordered[1:]] + [ftblock]
                for item, ft in zip(current.ordered, fallthroughs):
                    recurse(item, targets, ft, True)

            elif isinstance(current, SEBlockItem):
                targets = targets + ((ftblock, None),)
                new = _createASTBlock(info, current.node, targets)

            assert(new is not None)
            #stuff to be done after recursive calls return
            stack.append((False, (current, new, contents, ret_cb)))
            stack.extend(calls)
        else: #after recursion
            current, new, contents, ret_cb = data
            contents = list(reversed(contents)) #the results of recursive calls. Has to be reversed since stacks are FILO


            if isinstance(current, SEScope):
                new.statements = contents
                new.jump = None
                assert(all(isinstance(s, ast.JavaStatement) for s in new.statements))
            elif isinstance(current, SEWhile):
                new.parts = tuple(contents)
            elif isinstance(current, SETry):
                parts = contents
                catchnode = current.getScopes()[-1].entryBlock
                declt = ast.CatchTypeNames(info.env, current.toptts)

                if current.catchvar is None: #exception is ignored and hence not referred to by the graph, so we need to make our own
                    catchvar = info.customVar(declt, 'ignoredException')
                else:
                    catchvar = info.var(catchnode, current.catchvar)
                decl = ast.VariableDeclarator(declt, catchvar)
                new.tryb = parts[0]
                new.pairs = [(decl, parts[1])]
            elif isinstance(current, SEIf):
                headscope = _createASTBlock(info, current.head.node, None) #pass none as breakmap so an error occurs if it is used
                new.scopes = tuple(contents)

                #bundle head and if together so we can return as single statement
                new2 = ast.StatementBlock(info.labelgen)
                new2.statements = headscope, new
                new = new2
            elif isinstance(current, SESwitch):
                headscope = _createASTBlock(info, current.head.node, None) #pass none as breakmap so an error occurs if it is used
                new.pairs = zip(current.ordered_keysets, contents)
                new2 = ast.StatementBlock(info.labelgen)
                new2.statements = headscope, new
                new = new2
            elif isinstance(current, SEBlockItem):
                pass

            ret_cb(new) # 'return' from recursive call
    return result[0]

def createAST(method, ssagraph, seroot, namegen):
    info = VarInfo(method, ssagraph.blocks, namegen)
    astroot = _createASTSub(info, seroot)
    return astroot, info