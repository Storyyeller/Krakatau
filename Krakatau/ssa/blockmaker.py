import collections

from . import ssa_ops, ssa_jumps, objtypes, subproc
from .. import opnames as vops
from ..verifier import verifier_types
from ..verifier.descriptors import parseMethodDescriptor, parseFieldDescriptor
from .ssa_types import SSA_INT, SSA_LONG, SSA_FLOAT, SSA_DOUBLE, SSA_OBJECT, SSA_MONAD
from .ssa_types import slots_t, BasicBlock

_charToSSAType = {'D':SSA_DOUBLE, 'F':SSA_FLOAT, 'I':SSA_INT, 'J':SSA_LONG,
                'B':SSA_INT, 'C':SSA_INT, 'S':SSA_INT}
def getCategory(c): return 2 if c in 'JD' else 1

def makeDict(**kwargs): return kwargs

##############################################################################
def makeConstVar(parent, type_, val):
    var = parent.makeVariable(type_)
    var.const = val
    return var

def parseArrOrClassName(desc):
    if desc[0] == '[':
        vtypes = parseFieldDescriptor(desc, unsynthesize=False)
        tt = objtypes.verifierToSynthetic(vtypes[0])
    else:
        tt = desc, 0
    return tt

def _genericStackOperation(op, stack):
    num, replaceCodes = genericStackCodes[op]

    vals = stack[-num:]
    newvals = [vals[num-i-1] for i in replaceCodes]
    newstack = stack[:-num] + newvals
    return makeDict(newstack=newstack)

def _floatOrIntMath(fop, iop):
    def math1(parent, input_, iNode):
        cat = getCategory(iNode.instruction[1])
        isfloat = (iNode.instruction[1] in 'DF')
        op = fop if isfloat else iop

        args = input_.stack[-cat*2::cat]
        line = op(parent, args)

        newstack = input_.stack[:-2*cat] + [line.rval] + [None]*(cat-1)
        return makeDict(line=line, newstack=newstack)
    return math1

def _intMath(op, isShift):
    def math2(parent, input_, iNode):
        cat = getCategory(iNode.instruction[1])
        #some ops (i.e. shifts) always take int as second argument
        size = cat+1 if isShift else cat+cat
        args = input_.stack[-size::cat]
        line = op(parent, args)
        newstack = input_.stack[:-size] + [line.rval] + [None]*(cat-1)
        return makeDict(line=line, newstack=newstack)
    return math2
##############################################################################

def _anewarray(parent, input_, iNode):
    name = parent.getConstPoolArgs(iNode.instruction[1])[0]
    tt = parseArrOrClassName(name)
    line = ssa_ops.NewArray(parent, input_.stack[-1], tt, input_.monad)
    newstack = input_.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _arrlen(parent, input_, iNode):
    line = ssa_ops.ArrLength(parent, input_.stack[-1:])
    newstack = input_.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _arrload(parent, input_, iNode):
    type_ = _charToSSAType[iNode.instruction[1]]
    cat = getCategory(iNode.instruction[1])

    line = ssa_ops.ArrLoad(parent, input_.stack[-2:], type_, monad=input_.monad)
    newstack = input_.stack[:-2] + [line.rval] + [None]*(cat-1)
    return makeDict(line=line, newstack=newstack)

def _arrload_obj(parent, input_, iNode):
    line = ssa_ops.ArrLoad(parent, input_.stack[-2:], SSA_OBJECT, monad=input_.monad)
    newstack = input_.stack[:-2] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _arrstore(parent, input_, iNode):
    if getCategory(iNode.instruction[1]) > 1:
        newstack, args = input_.stack[:-4], input_.stack[-4:-1]
    else:
        newstack, args = input_.stack[:-3], input_.stack[-3:]
    line = ssa_ops.ArrStore(parent, args, monad=input_.monad)
    return makeDict(line=line, newstack=newstack)

def _arrstore_obj(parent, input_, iNode):
    line = ssa_ops.ArrStore(parent, input_.stack[-3:], monad=input_.monad)
    newstack = input_.stack[:-3]
    return makeDict(line=line, newstack=newstack)

def _checkcast(parent, input_, iNode):
    index = iNode.instruction[1]
    desc = parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(desc)
    line = ssa_ops.CheckCast(parent, tt, input_.stack[-1:])
    return makeDict(line=line)

def _const(parent, input_, iNode):
    ctype, val = iNode.instruction[1:]
    cat = getCategory(ctype)
    type_ = _charToSSAType[ctype]
    var = makeConstVar(parent, type_, val)
    newstack = input_.stack + [var] + [None]*(cat-1)
    return makeDict(newstack=newstack)

def _constnull(parent, input_, iNode):
    var = makeConstVar(parent, SSA_OBJECT, 'null')
    var.decltype = objtypes.NullTT
    newstack = input_.stack + [var]
    return makeDict(newstack=newstack)

def _convert(parent, input_, iNode):
    src_c, dest_c = iNode.instruction[1:]
    src_cat, dest_cat = getCategory(src_c), getCategory(dest_c)

    stack, arg =  input_.stack[:-src_cat], input_.stack[-src_cat]
    line = ssa_ops.Convert(parent, arg, _charToSSAType[src_c], _charToSSAType[dest_c])

    newstack = stack + [line.rval] + [None]*(dest_cat-1)
    return makeDict(line=line, newstack=newstack)

def _fcmp(parent, input_, iNode):
    op, c, NaN_val = iNode.instruction
    cat = getCategory(c)

    args = input_.stack[-cat*2::cat]
    line = ssa_ops.FCmp(parent, args, NaN_val)
    newstack = input_.stack[:-cat*2] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _field_access(parent, input_, iNode):
    index = iNode.instruction[1]
    target, name, desc = parent.getConstPoolArgs(index)
    cat = len(parseFieldDescriptor(desc))

    argcnt = cat if 'put' in iNode.instruction[0] else 0
    if not 'static' in iNode.instruction[0]:
        argcnt += 1
    splitInd = len(input_.stack) - argcnt

    args = [x for x in input_.stack[splitInd:] if x is not None]
    line = ssa_ops.FieldAccess(parent, iNode.instruction, (target, name, desc), args=args, monad=input_.monad)
    newstack = input_.stack[:splitInd] + line.returned
    return makeDict(line=line, newstack=newstack)

def _if_a(parent, input_, iNode):
    null = makeConstVar(parent, SSA_OBJECT, 'null')
    null.decltype = objtypes.NullTT
    jump = ssa_jumps.If(parent, iNode.instruction[1], iNode.successors, (input_.stack[-1], null))
    newstack = input_.stack[:-1]
    return makeDict(jump=jump, newstack=newstack)

def _if_i(parent, input_, iNode):
    zero = makeConstVar(parent, SSA_INT, 0)
    jump = ssa_jumps.If(parent, iNode.instruction[1], iNode.successors, (input_.stack[-1], zero))
    newstack = input_.stack[:-1]
    return makeDict(jump=jump, newstack=newstack)

def _if_icmp(parent, input_, iNode):
    jump = ssa_jumps.If(parent, iNode.instruction[1], iNode.successors, input_.stack[-2:])
    newstack = input_.stack[:-2]
    return makeDict(jump=jump, newstack=newstack)

def _iinc(parent, input_, iNode):
    junk, index, amount = iNode.instruction

    oldval = input_.locals[index]
    constval = makeConstVar(parent, SSA_INT, amount)
    line = ssa_ops.IAdd(parent, (oldval, constval))

    newlocals = list(input_.locals)
    newlocals[index] = line.rval
    return makeDict(line=line, newlocals=newlocals)

def _instanceof(parent, input_, iNode):
    index = iNode.instruction[1]
    desc = parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(desc)
    line = ssa_ops.InstanceOf(parent, tt, input_.stack[-1:])
    newstack = input_.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _invoke(parent, input_, iNode):
    index = iNode.instruction[1]
    target, name, desc = parent.getConstPoolArgs(index)

    argcnt = len(parseMethodDescriptor(desc)[0])
    if not 'static' in iNode.instruction[0]:
        argcnt += 1
    splitInd = len(input_.stack) - argcnt

    #If we are an initializer, store a copy of the uninitialized verifier type so the Java decompiler can patch things up later
    isThisCtor = iNode.isThisCtor if iNode.op == vops.INVOKEINIT else False

    args = [x for x in input_.stack[splitInd:] if x is not None]
    line = ssa_ops.Invoke(parent, iNode.instruction, (target, name, desc), args=args, monad=input_.monad, isThisCtor=isThisCtor)
    newstack = input_.stack[:splitInd] + line.returned
    return makeDict(line=line, newstack=newstack)

def _jsr(parent, input_, iNode):
    newstack = input_.stack + [None]

    if iNode.returnedFrom is None:
        return makeDict(newstack=newstack)
    else:
        #Simply store the data for now and fix things up once all the blocks are created
        jump = subproc.ProcCallOp(input_, iNode)
        return makeDict(jump=jump, newstack=newstack)

def _lcmp(parent, input_, iNode):
    args = input_.stack[-4::2]
    line = ssa_ops.ICmp(parent, args)
    newstack = input_.stack[:-4] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _ldc(parent, input_, iNode):
    index, cat = iNode.instruction[1:]
    entry_type = parent.getConstPoolType(index)
    args = parent.getConstPoolArgs(index)

    var = None
    if entry_type == 'String':
        var = makeConstVar(parent, SSA_OBJECT, args[0])
        var.decltype = objtypes.StringTT
    elif entry_type == 'Int':
        var = makeConstVar(parent, SSA_INT, args[0])
    elif entry_type == 'Long':
        var = makeConstVar(parent, SSA_LONG, args[0])
    elif entry_type == 'Float':
        var = makeConstVar(parent, SSA_FLOAT, args[0])
    elif entry_type == 'Double':
        var = makeConstVar(parent, SSA_DOUBLE, args[0])
    elif entry_type == 'Class':
        tt = args[0], 0 #todo - make this handle arrays and primatives
        var = makeConstVar(parent, SSA_OBJECT, tt)
        var.decltype = objtypes.ClassTT
    #Todo - handle MethodTypes and MethodHandles?

    assert(var)
    newstack = input_.stack + [var] + [None]*(cat-1)
    return makeDict(newstack=newstack)

def _load(parent, input_, iNode):
    cat = getCategory(iNode.instruction[1])
    index = iNode.instruction[2]
    newstack = input_.stack + input_.locals[index:index+cat]
    return makeDict(newstack=newstack)

def _monitor(parent, input_, iNode):
    isExit = 'exit' in iNode.instruction[0]
    line = ssa_ops.Monitor(parent, input_.stack[-1:], input_.monad, isExit)
    newstack = input_.stack[:-1]
    return makeDict(line=line, newstack=newstack)

def _multinewarray(parent, input_, iNode):
    op, index, dim = iNode.instruction
    name = parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(name)
    assert(tt[1] >= dim)

    line = ssa_ops.MultiNewArray(parent, input_.stack[-dim:], tt, input_.monad)
    newstack = input_.stack[:-dim] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _neg(parent, input_, iNode):
    cat = getCategory(iNode.instruction[1])
    arg = input_.stack[-cat:][0]

    if (iNode.instruction[1] in 'DF'):
        line = ssa_ops.FNeg(parent, [arg])
    else: #for integers, we can just write -x as 0 - x
        zero = makeConstVar(parent, arg.type, 0)
        line = ssa_ops.ISub(parent, [zero,arg])

    newstack = input_.stack[:-cat] + [line.rval] + [None]*(cat-1)
    return makeDict(line=line, newstack=newstack)

def _new(parent, input_, iNode):
    index = iNode.instruction[1]
    classname = parent.getConstPoolArgs(index)[0]

    line = ssa_ops.New(parent, classname, input_.monad)
    newstack = input_.stack + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _newarray(parent, input_, iNode):
    vtypes = parseFieldDescriptor(iNode.instruction[1], unsynthesize=False)
    tt = objtypes.verifierToSynthetic(vtypes[0])

    line = ssa_ops.NewArray(parent, input_.stack[-1], tt, input_.monad)
    newstack = input_.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _nop(parent, input_, iNode):
    return makeDict()

def _ret(parent, input_, iNode):
    jump = subproc.DummyRet(input_, iNode)
    return makeDict(jump=jump)

def _return(parent, input_, iNode):
    line = ssa_ops.TryReturn(parent, input_.monad)

    #Our special return block expects only the return values on the stack
    rtype = iNode.instruction[1]
    if rtype is None:
        newstack = []
    else:
        newstack = input_.stack[-getCategory(rtype):]
    return makeDict(line=line, newstack=newstack)

def _store(parent, input_, iNode):
    cat = getCategory(iNode.instruction[1])
    index = iNode.instruction[2]

    newlocals = list(input_.locals)
    if len(newlocals) < index+cat:
        newlocals += [None] * (index+cat - len(newlocals))

    newlocals[index:index+cat] = input_.stack[-cat:]
    newstack = input_.stack[:-cat]
    return makeDict(newstack=newstack, newlocals=newlocals)

def _switch(parent, input_, iNode):
    default, table = iNode.instruction[1:3]
    jump = ssa_jumps.Switch(parent, default, table, input_.stack[-1:])
    newstack = input_.stack[:-1]
    return makeDict(jump=jump, newstack=newstack)

def _throw(parent, input_, iNode):
    line = ssa_ops.Throw(parent, input_.stack[-1:])
    return makeDict(line=line, newstack=[])

def _truncate(parent, input_, iNode):
    dest_c = iNode.instruction[1]
    signed, width = {'B':(True,8), 'C':(False,16), 'S':(True, 16)}[dest_c]

    line = ssa_ops.Truncate(parent, input_.stack[-1], signed=signed, width=width)
    newstack = input_.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack)

_instructionHandlers = {
                        vops.ADD: _floatOrIntMath(ssa_ops.FAdd, ssa_ops.IAdd),
                        vops.AND: _intMath(ssa_ops.IAnd, isShift=False),
                        vops.ANEWARRAY: _anewarray,
                        vops.ARRLEN: _arrlen,
                        vops.ARRLOAD: _arrload,
                        vops.ARRLOAD_OBJ: _arrload_obj,
                        vops.ARRSTORE: _arrstore,
                        vops.ARRSTORE_OBJ: _arrstore_obj,
                        vops.CHECKCAST: _checkcast,
                        vops.CONST: _const,
                        vops.CONSTNULL: _constnull,
                        vops.CONVERT: _convert,
                        vops.DIV: _floatOrIntMath(ssa_ops.FDiv, ssa_ops.IDiv),
                        vops.FCMP: _fcmp,
                        vops.GETSTATIC: _field_access,
                        vops.GETFIELD: _field_access,
                        vops.GOTO: _nop, #since gotos are added by default, this is a nop
                        vops.IF_A: _if_a,
                        vops.IF_ACMP: _if_icmp, #icmp works on objs too
                        vops.IF_I: _if_i,
                        vops.IF_ICMP: _if_icmp,
                        vops.IINC: _iinc,
                        vops.INSTANCEOF: _instanceof,
                        vops.INVOKEINIT: _invoke,
                        vops.INVOKEINTERFACE: _invoke,
                        vops.INVOKESPECIAL: _invoke,
                        vops.INVOKESTATIC: _invoke,
                        vops.INVOKEVIRTUAL: _invoke,
                        vops.JSR: _jsr,
                        vops.LCMP: _lcmp,
                        vops.LDC: _ldc,
                        vops.LOAD: _load,
                        vops.MONENTER: _monitor,
                        vops.MONEXIT: _monitor,
                        vops.MULTINEWARRAY: _multinewarray,
                        vops.MUL: _floatOrIntMath(ssa_ops.FMul, ssa_ops.IMul),
                        vops.NEG: _neg,
                        vops.NEW: _new,
                        vops.NEWARRAY: _newarray,
                        vops.NOP: _nop,
                        vops.OR: _intMath(ssa_ops.IOr, isShift=False),
                        vops.PUTSTATIC: _field_access,
                        vops.PUTFIELD: _field_access,
                        vops.REM: _floatOrIntMath(ssa_ops.FRem, ssa_ops.IRem),
                        vops.RET: _ret,
                        vops.RETURN: _return,
                        vops.SHL: _intMath(ssa_ops.IShl, isShift=True),
                        vops.SHR: _intMath(ssa_ops.IShr, isShift=True),
                        vops.STORE: _store,
                        vops.SUB: _floatOrIntMath(ssa_ops.FSub, ssa_ops.ISub),
                        vops.SWITCH: _switch,
                        vops.THROW: _throw,
                        vops.TRUNCATE: _truncate,
                        vops.USHR: _intMath(ssa_ops.IUshr, isShift=True),
                        vops.XOR: _intMath(ssa_ops.IXor, isShift=False),
                        }

def genericStackUpdate(parent, input_, iNode):
    b = iNode.before.replace('+','')
    a = iNode.after
    assert(b and set(b+a) <= set('1234'))

    replace = {c:v for c,v in zip(b, input_.stack[-len(b):])}
    newstack = input_.stack[:-len(b)]
    newstack += [replace[c] for c in a]
    return makeDict(newstack=newstack)

def getOnNoExceptionTarget(parent, iNode):
    vop = iNode.instruction[0]
    if vop == vops.RETURN:
        return parent.returnKey
    elif vop not in (vops.RET,vops.THROW,vops.RETURN):
        return iNode.successors[0]
    return None

def processArrayInfo(newarray_info, iNode, vals):
    #There is an unfortunate tendency among Java programmers to hardcode large arrays
    #resulting in the generation of thousands of instructions simply initializing an array
    #With naive analysis, all of the stores can throw and so won't be merged until later
    #Optimize for this case by keeping track of all arrays created in the block with a
    #statically known size and type so we can mark all related instructions as nothrow and
    #hence don't have to end the block prematurely
    op = iNode.instruction[0]

    if op == vops.NEWARRAY or op == vops.ANEWARRAY:
        line = vals['line']
        lenvar = line.params[1]
        assert(lenvar.type == SSA_INT)

        if lenvar.const is not None and lenvar.const >= 0:
            #has known, positive dim
            newarray_info[line.rval] = lenvar.const, line.baset
            line.outException = None

    elif op == vops.ARRSTORE or op == vops.ARRSTORE_OBJ:
        line = vals['line']
        m, a, i, x = line.params
        if a not in newarray_info:
            return
        arrlen, baset = newarray_info[a]
        if i.const is None or not 0 <= i.const < arrlen:
            return
        #array element type test. For objects we check an exact match on decltype
        #which is highly conservative but should be enough to handle string literals
        if '.' not in baset[0] and baset != x.decltype:
            return

        line.outException = None

def fromInstruction(parent, block, newarray_info, iNode, initMap):
    assert(iNode.visited)
    instr = iNode.instruction

    if block is None:
        #create new partially constructed block (jump is none)
        block = BasicBlock(iNode.key, [], None)

        #now make inslots for the block
        monad = parent.makeVariable(SSA_MONAD)
        stack = [parent.makeVarFromVtype(vt, initMap) for vt in iNode.stack]
        locals_ = [parent.makeVarFromVtype(vt, initMap) for vt in iNode.locals]
        inslots = block.inslots = slots_t(monad=monad, locals=locals_, stack=stack)
    else:
        skey, inslots = block.successorStates[0]
        assert(skey == (iNode.key, False) and len(block.successorStates) == 1)
        block.successorStates = None #make sure we don't accidently access stale data
        #have to keep track of internal keys for predecessor tracking later
        block.keys.append(iNode.key)



    if iNode.before is not None and '1' in iNode.before:
        func = genericStackUpdate
    else:
        func = _instructionHandlers[instr[0]]

    vals = func(parent, inslots, iNode)
    processArrayInfo(newarray_info, iNode, vals)


    line, jump = map(vals.get, ('line','jump'))
    newstack = vals.get('newstack', inslots.stack)
    newlocals = vals.get('newlocals', inslots.locals)
    newmonad = line.outMonad if (line and line.outMonad) else inslots.monad
    outslot_norm = slots_t(monad=newmonad, locals=newlocals, stack=newstack)


    if line is not None:
        block.lines.append(line)
    block.successorStates = [((nodekey, False), outslot_norm) for nodekey in iNode.successors]

    #Return iNodes obviously don't have our synethetic return node as a normal successor
    if instr[0] == vops.RETURN:
        block.successorStates.append(((parent.returnKey, False), outslot_norm))

    if line and line.outException:
        assert(not jump)
        fallthrough = getOnNoExceptionTarget(parent, iNode)

        jump = ssa_jumps.OnException(parent, iNode.key, line, parent.rawExceptionHandlers(), fallthrough)
        outslot_except = slots_t(monad=newmonad, locals=newlocals, stack=[line.outException])
        block.successorStates += [((nodekey, True), outslot_except) for nodekey in jump.getExceptSuccessors()]

    if not jump:
        assert(instr[0] == vops.RETURN or len(iNode.successors) == 1)
        jump = ssa_jumps.Goto(parent, getOnNoExceptionTarget(parent, iNode))
    block.jump = jump

    block.tempvars.extend(newstack + newlocals + [newmonad])
    return block

_jump_instrs = frozenset([vops.GOTO, vops.IF_A, vops.IF_ACMP, vops.IF_I, vops.IF_ICMP, vops.JSR, vops.SWITCH])
def makeBlocks(parent, iNodes, myclsname):
    iNodes = [n for n in iNodes if n.visited]

    #create map of uninitialized -> initialized types so we can convert them
    initMap = {}
    for node in iNodes:
        if node.op == vops.NEW:
            initMap[node.push_type] = node.target_type
    initMap[verifier_types.T_UNINIT_THIS] = verifier_types.T_OBJECT(myclsname)

    #The purpose of this function is to create blocks containing multiple instructions
    #of linear code where possible. Blocks for invidual instructions will get merged
    #by later analysis anyway but it's a lot faster to merge them during creation
    jump_targets = set()
    for node in iNodes:
        if node.instruction[0] in _jump_instrs:
            jump_targets.update(node.successors)

    newarray_info = {} #store info about newly created arrays in current block
    blocks = []
    curblock = None
    for node in iNodes:
        #check if we need to start a new block
        if curblock is not None:
            keep = node.key not in jump_targets
            keep = keep and isinstance(curblock.jump, ssa_jumps.Goto)
            keep = keep and node.key == curblock.jump.getNormalSuccessors()[0]
            #for simplicity, keep jsr stuff in individual instruction blocks.
            #Note that subproc.py will need to be modified if this is changed
            keep = keep and node.instruction[0] not in (vops.JSR, vops.RET)

            if not keep:
                blocks.append(curblock)
                curblock = None
                newarray_info = {}

        curblock = fromInstruction(parent, curblock, newarray_info, node, initMap)
        assert(curblock.jump)
    blocks.append(curblock)

    for block in blocks:
        block.successorStates = collections.OrderedDict(block.successorStates)
        block.tempvars = [t for t in block.tempvars if t is not None]
    return blocks