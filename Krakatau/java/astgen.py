from . import ast
from .setree import SEBlockItem, SEScope, SEIf, SESwitch, SETry, SEWhile
from ..ssa import ssa_types, ssa_ops, ssa_jumps
from ..ssa import objtypes
from ..namegen import NameGen, LabelGen
from .reserved import reserved_identifiers
from ..verifier.descriptors import parseFieldDescriptor, parseMethodDescriptor
from .. import opnames

#prefixes for name generation
_prefix_map = {objtypes.IntTT:'i', objtypes.LongTT:'j',
            objtypes.FloatTT:'f', objtypes.DoubleTT:'d',
            objtypes.BoolTT:'b', objtypes.StringTT:'s'}

_ssaToTT = {ssa_types.SSA_INT:'.int', ssa_types.SSA_LONG:'.long',
            ssa_types.SSA_FLOAT:'.float', ssa_types.SSA_DOUBLE:'.double'}
class VarInfo(object):
    def __init__(self, method, blocks):
        self.env = method.class_.env
        self.labelgen = LabelGen().next

        returnTypes = parseMethodDescriptor(method.descriptor, unsynthesize=False)[-1]
        self.return_tt = objtypes.verifierToSynthetic(returnTypes[0]) if returnTypes else None
        self.clsname = method.class_.name

        self._namegen = NameGen(reserved_identifiers)
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
                    tt = _ssaToTT[var.type], 0
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
            tt = op.target, 0
            expr = ast.FieldAccess(ast.TypeName(tt), op.name, dtype)
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
    jump_tup = None
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
        jump_tup = breakmap[norm_successors[0]]      
    #case of if and switch jumps handled in parent scope

    new = ast.StatementBlock(info.labelgen)
    new.statements = statements
    new.setBreak(jump_tup)
    assert(None not in statements)
    return new

def _createASTSub(info, current, targets, ftblock, forceUnlabled=False):
    if isinstance(current, SEScope):
        new = ast.StatementBlock(info.labelgen)
        if not forceUnlabled and ftblock is not None:
            targets = targets + ((ftblock, (new,False)),)

        #todo - is sorting required here?
        last = ftblock
        contents = []
        for item in reversed(current.items):
            contents.append(_createASTSub(info, item, targets, last))
            last = item.entryBlock()

        new.statements = list(reversed(contents))
        new.jump = None
        assert(all(isinstance(s, ast.JavaStatement) for s in new.statements))
    elif isinstance(current, SEWhile):
        new = ast.WhileStatement(info.labelgen)
        targets = targets + ((current.entryBlock(), (new,True)),)
        if ftblock is not None:
            targets = targets + ((ftblock, (new,False)),)
        new.parts = _createASTSub(info, current.body, targets, None),
    elif isinstance(current, SETry):
        new = ast.TryStatement(info.labelgen)
        if ftblock is not None:
            targets = targets + ((ftblock, (new,False)),)
        parts = [_createASTSub(info, scope, targets, None) for scope in current.getScopes()]
        catchnode = current.getScopes()[-1].entryBlock()

        declt = ast.CatchTypeNames(info.env, current.toptts)
        if current.catchvar is None: #exception is ignored and hence not referred to by the graph, so we need to make our own
            catchvar = info.customVar(declt, 'ignoredException')
        else:
            catchvar = info.var(catchnode, current.catchvar)

        decl = ast.VariableDeclarator(declt, catchvar)
        new.parts = parts[0], decl, parts[1]

    elif isinstance(current, SEIf):
        node = current.head.node
        headscope = _createASTBlock(info, node, None) #pass none as breakmap so an error occurs if it is used
        jump = node.block.jump

        symbols = "== != < >= > <=".split()
        cmp_strs = dict(zip(('eq','ne','lt','ge','gt','le'), symbols))
        cmp_str = cmp_strs[jump.cmp]
        exprs = [info.var(node, var) for var in jump.params]
        ifexpr = ast.BinaryInfix(cmp_str, exprs, objtypes.BoolTT)

        newif = ast.IfStatement(info.labelgen, ifexpr)
        if ftblock is not None:
            targets = targets + ((ftblock, (newif,False)),)

        scopes = [_createASTSub(info, scope, targets, ftblock, forceUnlabled=True) for scope in current.getScopes()]
        newif.scopes = scopes

        #bundle head and if together so we can return as single statement
        new = ast.StatementBlock(info.labelgen)
        new.statements = headscope, newif
        
    elif isinstance(current, SESwitch):
        node = current.head.node
        headscope = _createASTBlock(info, node, None) #pass none as breakmap so an error occurs if it is used
        jump = node.block.jump

        exprs = [info.var(node, var) for var in jump.params]
        newswitch = ast.SwitchStatement(info.labelgen, exprs[0])
        if ftblock is not None:
            targets = targets + ((ftblock, (newswitch,False)),)

        keysets = {node.blockdict[b.key,False]:jump.reverse.get(b) for b in jump.getNormalSuccessors()}
        assert(keysets.values().count(None) == 1)

        pairs = []
        newft = ftblock
        for scope in reversed(current.ordered):
            temp = _createASTSub(info, scope, targets, newft, forceUnlabled=True)
            newft = scope.entryBlock()
            pairs.append((keysets[scope.entryBlock()], temp))
            del keysets[scope.entryBlock()]
        assert(not keysets)

        newswitch.pairs = list(reversed(pairs))
        new = ast.StatementBlock(info.labelgen)
        new.statements = headscope, newswitch

    elif isinstance(current, SEBlockItem):
        if ftblock is not None:
            targets = targets + ((ftblock, None),)
        gotoMap = dict(targets) #more recent keys override, as desired

        new = _createASTBlock(info, current.node, gotoMap)
    return new

def createAST(method, ssagraph, seroot):
    info = VarInfo(method, ssagraph.blocks)
    astroot = _createASTSub(info, seroot, (), None)
    return astroot, info