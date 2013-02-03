import itertools, collections 

from ..verifier import verifier_types as vtypes
from .. import opnames as vops
from .. import floatutil
from ..verifier.descriptors import parseMethodDescriptor, parseFieldDescriptor
from ..verifier.inference_verifier import genericStackCodes
from ssa_types import *
import ssa_ops, ssa_jumps
import objtypes #for LDC
import subproc

_charToSSAType = {'D':SSA_DOUBLE, 'F':SSA_FLOAT, 'I':SSA_INT, 'L':SSA_LONG,
                'B':SSA_INT, 'C':SSA_INT, 'S':SSA_INT}
def getCategory(c): return 2 if c in 'LD' else 1

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
    def math1(parent, input, iNode):
        cat = getCategory(iNode.instruction[1])
        isfloat = (iNode.instruction[1] in 'DF')
        op = fop if isfloat else iop

        args = input.stack[-cat*2::cat]
        line = op(parent, args)

        newstack = input.stack[:-2*cat] + [line.rval] + [None]*(cat-1)
        return makeDict(line=line, newstack=newstack)
    return math1

def _intMath(op, isShift):
    def math2(parent, input, iNode):
        cat = getCategory(iNode.instruction[1])
        #some ops (i.e. shifts) always take int as second argument
        size = cat+1 if isShift else cat+cat
        args = input.stack[-size::cat]
        line = op(parent, args)
        newstack = input.stack[:-size] + [line.rval] + [None]*(cat-1)
        return makeDict(line=line, newstack=newstack)
    return math2
##############################################################################

def _anewarray(parent, input, iNode):
    name = parent.getConstPoolArgs(iNode.instruction[1])[0]
    tt = parseArrOrClassName(name)
    line = ssa_ops.NewArray(parent, input.stack[-1], tt, input.monad)
    newstack = input.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack, newmonad=line.outMonad)

def _arrlen(parent, input, iNode):
    line = ssa_ops.ArrLength(parent, input.stack[-1:])
    newstack = input.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _arrload(parent, input, iNode):
    type_ = _charToSSAType[iNode.instruction[1]]
    cat = getCategory(iNode.instruction[1])

    line = ssa_ops.ArrLoad(parent, input.stack[-2:], type_, monad=input.monad)
    newstack = input.stack[:-2] + [line.rval] + [None]*(cat-1)
    return makeDict(line=line, newstack=newstack)

def _arrload_obj(parent, input, iNode):
    line = ssa_ops.ArrLoad(parent, input.stack[-2:], SSA_OBJECT, monad=input.monad)
    newstack = input.stack[:-2] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _arrstore(parent, input, iNode):
    if getCategory(iNode.instruction[1]) > 1:
        newstack, args = input.stack[:-4], input.stack[-4:-1]
    else:
        newstack, args = input.stack[:-3], input.stack[-3:]
    line = ssa_ops.ArrStore(parent, args, monad=input.monad)
    return makeDict(line=line, newstack=newstack)

def _arrstore_obj(parent, input, iNode):
    line = ssa_ops.ArrStore(parent, input.stack[-3:], monad=input.monad)
    newstack = input.stack[:-3]
    return makeDict(line=line, newstack=newstack)

def _checkcast(parent, input, iNode):
    index = iNode.instruction[1]
    desc = parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(desc)
    line = ssa_ops.CheckCast(parent, tt, input.stack[-1:])
    return makeDict(line=line)

def _const(parent, input, iNode):
    ctype, val = iNode.instruction[1:]
    cat = getCategory(ctype)
    type_ = _charToSSAType[ctype]
    var = makeConstVar(parent, type_, val)
    newstack = input.stack + [var] + [None]*(cat-1)
    return makeDict(newstack=newstack)

def _constnull(parent, input, iNode):
    var = makeConstVar(parent, SSA_OBJECT, 'null')
    var.decltype = objtypes.NullTT
    newstack = input.stack + [var]
    return makeDict(newstack=newstack)

def _convert(parent, input, iNode):
    src_c, dest_c = iNode.instruction[1:]
    src_cat, dest_cat = getCategory(src_c), getCategory(dest_c)

    stack, arg =  input.stack[:-src_cat], input.stack[-src_cat]
    line = ssa_ops.Convert(parent, arg, _charToSSAType[dest_c])

    newstack = stack + [line.rval] + [None]*(dest_cat-1)
    return makeDict(line=line, newstack=newstack)

def _fcmp(parent, input, iNode):
    op, c, NaN_val = iNode.instruction
    cat = getCategory(c)

    args = input.stack[-cat*2::cat]
    line = ssa_ops.FCmp(parent, args, NaN_val)
    newstack = input.stack[:-cat*2] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _field_access(parent, input, iNode):
    index = iNode.instruction[1]
    target, name, desc = parent.getConstPoolArgs(index)
    cat = len(parseFieldDescriptor(desc))
    
    argcnt = cat if 'put' in iNode.instruction[0] else 0
    if not 'static' in iNode.instruction[0]:
            argcnt += 1
    splitInd = len(input.stack) - argcnt

    args = [x for x in input.stack[splitInd:] if x is not None]
    line = ssa_ops.FieldAccess(parent, iNode.instruction, (target, name, desc), args=args, monad=input.monad)
    newstack = input.stack[:splitInd] + line.returned
    return makeDict(line=line, newstack=newstack, newmonad=line.outMonad)

def _if_a(parent, input, iNode):
    null = makeConstVar(parent, SSA_OBJECT, 'null')
    null.decltype = objtypes.NullTT
    jump = ssa_jumps.If(parent, iNode.instruction[1], iNode.successors, (input.stack[-1], null))
    newstack = input.stack[:-1]
    return makeDict(jump=jump, newstack=newstack)

def _if_i(parent, input, iNode):
    zero = makeConstVar(parent, SSA_INT, 0)
    jump = ssa_jumps.If(parent, iNode.instruction[1], iNode.successors, (input.stack[-1], zero))
    newstack = input.stack[:-1]
    return makeDict(jump=jump, newstack=newstack)

def _if_icmp(parent, input, iNode):
    jump = ssa_jumps.If(parent, iNode.instruction[1], iNode.successors, input.stack[-2:])
    newstack = input.stack[:-2]
    return makeDict(jump=jump, newstack=newstack)

def _iinc(parent, input, iNode):
    junk, index, amount = iNode.instruction
    
    oldval = input.locals[index]
    constval = makeConstVar(parent, SSA_INT, amount)
    line = ssa_ops.IAdd(parent, (oldval, constval))

    newlocals = list(input.locals)
    newlocals[index] = line.rval
    return makeDict(line=line, newlocals=newlocals)

def _instanceof(parent, input, iNode):
    index = iNode.instruction[1]
    desc = parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(desc)
    line = ssa_ops.InstanceOf(parent, tt, input.stack[-1:])
    newstack = input.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _invoke(parent, input, iNode):
    index = iNode.instruction[1]
    target, name, desc = parent.getConstPoolArgs(index)

    argcnt = len(parseMethodDescriptor(desc)[0])
    if not 'static' in iNode.instruction[0]:
            argcnt += 1
    splitInd = len(input.stack) - argcnt

    #If we are an initializer, store a copy of the uninitialized verifier type so the Java decompiler can patch things up later
    unvt = iNode.stack[-argcnt] if iNode.instruction[0] == 'invokeinit' else None

    args = [x for x in input.stack[splitInd:] if x is not None]
    line = ssa_ops.Invoke(parent, iNode.instruction, (target, name, desc), args=args, monad=input.monad, verifier_type=unvt)
    newstack = input.stack[:splitInd] + line.returned
    return makeDict(line=line, newstack=newstack, newmonad=line.outMonad)

def _jsr(parent, input, iNode):
    newstack = input.stack + [None]

    if iNode.returnedFrom is None:
        return makeDict(newstack=newstack)
    else:
        #Simply store the data for now and fix things up once all the blocks are created
        jump = subproc.ProcCallOp(input, iNode)
        return makeDict(jump=jump, newstack=newstack)

def _lcmp(parent, input, iNode):
    args = input.stack[-4::2]
    line = ssa_ops.ICmp(parent, args)
    newstack = input.stack[:-4] + [line.rval]
    return makeDict(line=line, newstack=newstack)

def _ldc(parent, input, iNode):
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
    newstack = input.stack + [var] + [None]*(cat-1)
    return makeDict(newstack=newstack)

def _load(parent, input, iNode):
    cat = getCategory(iNode.instruction[1])
    index = iNode.instruction[2]
    newstack = input.stack + input.locals[index:index+cat]
    return makeDict(newstack=newstack)

def _monitor(parent, input, iNode):
    isExit = 'exit' in iNode.instruction[0]
    line = ssa_ops.Monitor(parent, input.stack[-1:], input.monad, isExit)
    newstack = input.stack[:-1]
    return makeDict(line=line, newstack=newstack, newmonad=line.outMonad)

def _multinewarray(parent, input, iNode):
    op, index, dim = iNode.instruction
    name = parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(name)
    assert(tt[1] >= dim)

    line = ssa_ops.MultiNewArray(parent, input.stack[-dim:], tt, input.monad)
    newstack = input.stack[:-dim] + [line.rval]
    return makeDict(line=line, newstack=newstack, newmonad=line.outMonad)

def _neg(parent, input, iNode):
    cat = getCategory(iNode.instruction[1])
    arg = input.stack[-cat:][0]

    if (iNode.instruction[1] in 'DF'):
        line = ssa_ops.FNeg(parent, [arg])
    else: #for integers, we can just write -x as 0 - x
        zero = makeConstVar(parent, arg.type, 0)
        line = ssa_ops.ISub(parent, [zero,arg])

    newstack = input.stack[:-cat] + [line.rval] + [None]*(cat-1)
    return makeDict(line=line, newstack=newstack)

def _new(parent, input, iNode):
    index = iNode.instruction[1]
    classname = parent.getConstPoolArgs(index)[0]

    #Ugly hack
    stack, locals_, masks, flags = iNode._getNewState()
    verifier_type = stack[-1]
    assert(not verifier_type.isInit)

    line = ssa_ops.New(parent, classname, input.monad, verifier_type)
    newstack = input.stack + [line.rval]
    return makeDict(line=line, newstack=newstack, newmonad=line.outMonad)

def _newarray(parent, input, iNode):
    vtypes = parseFieldDescriptor(iNode.instruction[1], unsynthesize=False)
    tt = objtypes.verifierToSynthetic(vtypes[0])

    line = ssa_ops.NewArray(parent, input.stack[-1], tt, input.monad)
    newstack = input.stack[:-1] + [line.rval]
    return makeDict(line=line, newstack=newstack, newmonad=line.outMonad)

def _nop(parent, input, iNode):
    return makeDict()

def _ret(parent, input, iNode):
    jump = subproc.DummyRet(input, iNode)
    return makeDict(jump=jump)

def _return(parent, input, iNode):
    line = ssa_ops.TryReturn(parent, input.monad)

    #Our special return block expects only the return values on the stack
    rtype = iNode.instruction[1]
    if rtype is None:
        newstack = []
    else:
        newstack = input.stack[-getCategory(rtype):]
    return makeDict(line=line, newstack=newstack)

def _store(parent, input, iNode):
    cat = getCategory(iNode.instruction[1])
    index = iNode.instruction[2]
    
    newlocals = list(input.locals)
    if len(newlocals) < index+cat:
        newlocals += [None] * (index+cat - len(newlocals))

    newlocals[index:index+cat] = input.stack[-cat:]
    newstack = input.stack[:-cat]
    return makeDict(newstack=newstack, newlocals=newlocals)

def _switch(parent, input, iNode):
    junk, default, table = iNode.instruction
    jump = ssa_jumps.Switch(parent, default, table, input.stack[-1:])
    newstack = input.stack[:-1]
    return makeDict(jump=jump, newstack=newstack)

def _throw(parent, input, iNode):
    line = ssa_ops.Throw(parent, input.stack[-1:])
    return makeDict(line=line, newstack=[])

def _truncate(parent, input, iNode):
    dest_c = iNode.instruction[1]
    signed, width = {'B':(True,8), 'C':(False,16), 'S':(True, 16)}[dest_c]

    line = ssa_ops.Truncate(parent, input.stack[-1], signed=signed, width=width)
    newstack = input.stack[:-1] + [line.rval]
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

def getOnNoExceptionTarget(parent, iNode):
    vop = iNode.instruction[0]
    if vop == vops.RETURN:
        return parent.returnKey
    elif vop not in (vops.RET,vops.THROW,vops.RETURN):
        return iNode.successors[0]
    return None

def fromInstruction(parent, iNode):
    assert(iNode.visited)
    instr = iNode.instruction

    monad = parent.makeVariable(SSA_MONAD)
    stack = map(parent.makeVarFromVtype, iNode.stack)
    locals_ = map(parent.makeVarFromVtype, iNode.locals)
    inslots = slots_t(monad=monad, locals=locals_, stack=stack)

    if instr[0] in genericStackCodes:
        vals = _genericStackOperation(instr[0], stack)
    else:
        func = _instructionHandlers[instr[0]]
        vals = func(parent, inslots, iNode)

    line, jump = map(vals.get, ('line','jump'))
    newstack = vals.get('newstack', stack)
    newlocals = vals.get('newlocals', locals_)
    newmonad = line.outMonad if (line and line.outMonad) else monad
    outslot_norm = slots_t(monad=newmonad, locals=newlocals, stack=newstack)    

    lines = [line] if line is not None else []
    successorStates = [((nodekey, False), outslot_norm) for nodekey in iNode.successors]

    #Return iNodes obviously don't have our synethetic return node as a normal successor
    if instr[0] == vops.RETURN:
        successorStates.append(((parent.returnKey, False), outslot_norm))
    elif instr[0] == vops.RET: #temporarily store these fake successors. Will be fixed later
        assert(not successorStates)
        successorStates = [((nodekey, False), outslot_norm) for nodekey in iNode.jsrSources]

    if line and line.outException:
        assert(not jump)
        fallthrough = getOnNoExceptionTarget(parent, iNode)

        jump = ssa_jumps.OnException(parent, iNode.key, line, parent.rawExceptionHandlers(), fallthrough)
        outslot_except = slots_t(monad=newmonad, locals=newlocals, stack=[line.outException])
        successorStates += [((nodekey, True), outslot_except) for nodekey in jump.getExceptSuccessors()]

    if not jump:
        assert(instr[0] == vops.RETURN or len(iNode.successors) == 1)
        jump = ssa_jumps.Goto(parent, getOnNoExceptionTarget(parent, iNode))

    block = BasicBlock(iNode.key, lines=lines, jump=jump)
    block.inslots = inslots
    block.successorStates = collections.OrderedDict(successorStates)
    #store these vars in case we created any constants in the block that won't show up later 
    block.tempvars = [var for var in newstack + newlocals if var is not None]
    return block