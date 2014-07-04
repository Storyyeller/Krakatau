import collections, itertools

from . import ssa_ops, ssa_jumps, objtypes, subproc
from .. import opnames as vops
from ..verifier import verifier_types
from ..verifier.descriptors import parseMethodDescriptor, parseFieldDescriptor
from .ssa_types import SSA_INT, SSA_LONG, SSA_FLOAT, SSA_DOUBLE, SSA_OBJECT, SSA_MONAD
from .ssa_types import slots_t, BasicBlock

#keys for special blocks created at the cfg entry and exit. Negative keys ensures they don't collide
ENTRY_KEY, RETURN_KEY, RETHROW_KEY = -1, -2, -3

_charToSSAType = {'D':SSA_DOUBLE, 'F':SSA_FLOAT, 'I':SSA_INT, 'J':SSA_LONG,
                'B':SSA_INT, 'C':SSA_INT, 'S':SSA_INT}
def getCategory(c): return 2 if c in 'JD' else 1

class ResultDict(object):
    def __init__(self, line=None, jump=None, newstack=None, newlocals=None):
        self.line = line
        self.jump = jump
        self.newstack = newstack
        self.newlocals = newlocals

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

def _floatOrIntMath(fop, iop):
    def math1(maker, input_, iNode):
        cat = getCategory(iNode.instruction[1])
        isfloat = (iNode.instruction[1] in 'DF')
        op = fop if isfloat else iop

        args = input_.stack[-cat*2::cat]
        line = op(maker.parent, args)

        newstack = input_.stack[:-2*cat] + [line.rval] + [None]*(cat-1)
        return ResultDict(line=line, newstack=newstack)
    return math1

def _intMath(op, isShift):
    def math2(maker, input_, iNode):
        cat = getCategory(iNode.instruction[1])
        #some ops (i.e. shifts) always take int as second argument
        size = cat+1 if isShift else cat+cat
        args = input_.stack[-size::cat]
        line = op(maker.parent, args)
        newstack = input_.stack[:-size] + [line.rval] + [None]*(cat-1)
        return ResultDict(line=line, newstack=newstack)
    return math2
##############################################################################

def _anewarray(maker, input_, iNode):
    name = maker.parent.getConstPoolArgs(iNode.instruction[1])[0]
    tt = parseArrOrClassName(name)
    line = ssa_ops.NewArray(maker.parent, input_.stack[-1], tt, input_.monad)
    newstack = input_.stack[:-1] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _arrlen(maker, input_, iNode):
    line = ssa_ops.ArrLength(maker.parent, input_.stack[-1:])
    newstack = input_.stack[:-1] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _arrload(maker, input_, iNode):
    type_ = _charToSSAType[iNode.instruction[1]]
    cat = getCategory(iNode.instruction[1])

    line = ssa_ops.ArrLoad(maker.parent, input_.stack[-2:], type_, monad=input_.monad)
    newstack = input_.stack[:-2] + [line.rval] + [None]*(cat-1)
    return ResultDict(line=line, newstack=newstack)

def _arrload_obj(maker, input_, iNode):
    line = ssa_ops.ArrLoad(maker.parent, input_.stack[-2:], SSA_OBJECT, monad=input_.monad)
    newstack = input_.stack[:-2] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _arrstore(maker, input_, iNode):
    if getCategory(iNode.instruction[1]) > 1:
        newstack, args = input_.stack[:-4], input_.stack[-4:-1]
    else:
        newstack, args = input_.stack[:-3], input_.stack[-3:]
    line = ssa_ops.ArrStore(maker.parent, args, monad=input_.monad)
    return ResultDict(line=line, newstack=newstack)

def _arrstore_obj(maker, input_, iNode):
    line = ssa_ops.ArrStore(maker.parent, input_.stack[-3:], monad=input_.monad)
    newstack = input_.stack[:-3]
    return ResultDict(line=line, newstack=newstack)

def _checkcast(maker, input_, iNode):
    index = iNode.instruction[1]
    desc = maker.parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(desc)
    line = ssa_ops.CheckCast(maker.parent, tt, input_.stack[-1:])
    return ResultDict(line=line)

def _const(maker, input_, iNode):
    ctype, val = iNode.instruction[1:]
    cat = getCategory(ctype)
    type_ = _charToSSAType[ctype]
    var = makeConstVar(maker.parent, type_, val)
    newstack = input_.stack + [var] + [None]*(cat-1)
    return ResultDict(newstack=newstack)

def _constnull(maker, input_, iNode):
    var = makeConstVar(maker.parent, SSA_OBJECT, 'null')
    var.decltype = objtypes.NullTT
    newstack = input_.stack + [var]
    return ResultDict(newstack=newstack)

def _convert(maker, input_, iNode):
    src_c, dest_c = iNode.instruction[1:]
    src_cat, dest_cat = getCategory(src_c), getCategory(dest_c)

    stack, arg =  input_.stack[:-src_cat], input_.stack[-src_cat]
    line = ssa_ops.Convert(maker.parent, arg, _charToSSAType[src_c], _charToSSAType[dest_c])

    newstack = stack + [line.rval] + [None]*(dest_cat-1)
    return ResultDict(line=line, newstack=newstack)

def _fcmp(maker, input_, iNode):
    op, c, NaN_val = iNode.instruction
    cat = getCategory(c)

    args = input_.stack[-cat*2::cat]
    line = ssa_ops.FCmp(maker.parent, args, NaN_val)
    newstack = input_.stack[:-cat*2] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _field_access(maker, input_, iNode):
    index = iNode.instruction[1]
    target, name, desc = maker.parent.getConstPoolArgs(index)
    cat = len(parseFieldDescriptor(desc))

    argcnt = cat if 'put' in iNode.instruction[0] else 0
    if not 'static' in iNode.instruction[0]:
        argcnt += 1
    splitInd = len(input_.stack) - argcnt

    args = [x for x in input_.stack[splitInd:] if x is not None]
    line = ssa_ops.FieldAccess(maker.parent, iNode.instruction, (target, name, desc), args=args, monad=input_.monad)
    newstack = input_.stack[:splitInd] + line.returned
    return ResultDict(line=line, newstack=newstack)

def _goto(maker, input_, iNode):
    jump = ssa_jumps.Goto(maker.parent, maker.blockd[iNode.successors[0]])
    return ResultDict(jump=jump)

def _if_a(maker, input_, iNode):
    null = makeConstVar(maker.parent, SSA_OBJECT, 'null')
    null.decltype = objtypes.NullTT
    jump = ssa_jumps.If(maker.parent, iNode.instruction[1], map(maker.blockd.get, iNode.successors), (input_.stack[-1], null))
    newstack = input_.stack[:-1]
    return ResultDict(jump=jump, newstack=newstack)

def _if_i(maker, input_, iNode):
    zero = makeConstVar(maker.parent, SSA_INT, 0)
    jump = ssa_jumps.If(maker.parent, iNode.instruction[1], map(maker.blockd.get, iNode.successors), (input_.stack[-1], zero))
    newstack = input_.stack[:-1]
    return ResultDict(jump=jump, newstack=newstack)

def _if_cmp(maker, input_, iNode):
    jump = ssa_jumps.If(maker.parent, iNode.instruction[1], map(maker.blockd.get, iNode.successors), input_.stack[-2:])
    newstack = input_.stack[:-2]
    return ResultDict(jump=jump, newstack=newstack)

def _iinc(maker, input_, iNode):
    _, index, amount = iNode.instruction

    oldval = input_.locals[index]
    constval = makeConstVar(maker.parent, SSA_INT, amount)
    line = ssa_ops.IAdd(maker.parent, (oldval, constval))

    newlocals = list(input_.locals)
    newlocals[index] = line.rval
    return ResultDict(line=line, newlocals=newlocals)

def _instanceof(maker, input_, iNode):
    index = iNode.instruction[1]
    desc = maker.parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(desc)
    line = ssa_ops.InstanceOf(maker.parent, tt, input_.stack[-1:])
    newstack = input_.stack[:-1] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _invoke(maker, input_, iNode):
    index = iNode.instruction[1]
    target, name, desc = maker.parent.getConstPoolArgs(index)
    target_tt = parseArrOrClassName(target)

    argcnt = len(parseMethodDescriptor(desc)[0])
    if not 'static' in iNode.instruction[0]:
        argcnt += 1
    splitInd = len(input_.stack) - argcnt

    #If we are an initializer, store a copy of the uninitialized verifier type so the Java decompiler can patch things up later
    isThisCtor = iNode.isThisCtor if iNode.op == vops.INVOKEINIT else False

    args = [x for x in input_.stack[splitInd:] if x is not None]
    line = ssa_ops.Invoke(maker.parent, iNode.instruction, (target, name, desc),
        args=args, monad=input_.monad, isThisCtor=isThisCtor, target_tt=target_tt)
    newstack = input_.stack[:splitInd] + line.returned
    return ResultDict(line=line, newstack=newstack)

def _jsr(maker, input_, iNode):
    newstack = input_.stack + [None]
    if iNode.returnedFrom is None:
        jump = ssa_jumps.Goto(maker.parent, maker.blockd[iNode.successors[0]])
        return ResultDict(newstack=newstack, jump=jump)

    #create output variables from callop to represent vars received from ret.
    #We can use {} for initMap since there will never be unintialized types here
    retnode = maker.iNodeD[iNode.returnedFrom]
    monad = maker.parent.makeVariable(SSA_MONAD)
    stack, locals = [[maker.parent.makeVarFromVtype(vt, {}) for vt in part] for part in retnode.out_state]
    out_slots = slots_t(monad=monad, locals=locals, stack=stack)

    #Simply store the data for now and fix things up once all the blocks are created
    jump = subproc.ProcCallOp(maker.blockd[iNode.successors[0]], maker.blockd[iNode.next_instruction], input_, out_slots)
    return ResultDict(jump=jump, newstack=newstack)

def _lcmp(maker, input_, iNode):
    args = input_.stack[-4::2]
    line = ssa_ops.ICmp(maker.parent, args)
    newstack = input_.stack[:-4] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _ldc(maker, input_, iNode):
    index, cat = iNode.instruction[1:]
    entry_type = maker.parent.getConstPoolType(index)
    args = maker.parent.getConstPoolArgs(index)

    var = None
    if entry_type == 'String':
        var = makeConstVar(maker.parent, SSA_OBJECT, args[0])
        var.decltype = objtypes.StringTT
    elif entry_type == 'Int':
        var = makeConstVar(maker.parent, SSA_INT, args[0])
    elif entry_type == 'Long':
        var = makeConstVar(maker.parent, SSA_LONG, args[0])
    elif entry_type == 'Float':
        var = makeConstVar(maker.parent, SSA_FLOAT, args[0])
    elif entry_type == 'Double':
        var = makeConstVar(maker.parent, SSA_DOUBLE, args[0])
    elif entry_type == 'Class':
        tt = args[0], 0 #todo - make this handle arrays and primatives
        var = makeConstVar(maker.parent, SSA_OBJECT, tt)
        var.decltype = objtypes.ClassTT
    #Todo - handle MethodTypes and MethodHandles?

    assert(var)
    newstack = input_.stack + [var] + [None]*(cat-1)
    return ResultDict(newstack=newstack)

def _load(maker, input_, iNode):
    cat = getCategory(iNode.instruction[1])
    index = iNode.instruction[2]
    newstack = input_.stack + input_.locals[index:index+cat]
    return ResultDict(newstack=newstack)

def _monitor(maker, input_, iNode):
    isExit = 'exit' in iNode.instruction[0]
    line = ssa_ops.Monitor(maker.parent, input_.stack[-1:], input_.monad, isExit)
    newstack = input_.stack[:-1]
    return ResultDict(line=line, newstack=newstack)

def _multinewarray(maker, input_, iNode):
    op, index, dim = iNode.instruction
    name = maker.parent.getConstPoolArgs(index)[0]
    tt = parseArrOrClassName(name)
    assert(tt[1] >= dim)

    line = ssa_ops.MultiNewArray(maker.parent, input_.stack[-dim:], tt, input_.monad)
    newstack = input_.stack[:-dim] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _neg(maker, input_, iNode):
    cat = getCategory(iNode.instruction[1])
    arg = input_.stack[-cat:][0]

    if (iNode.instruction[1] in 'DF'):
        line = ssa_ops.FNeg(maker.parent, [arg])
    else: #for integers, we can just write -x as 0 - x
        zero = makeConstVar(maker.parent, arg.type, 0)
        line = ssa_ops.ISub(maker.parent, [zero,arg])

    newstack = input_.stack[:-cat] + [line.rval] + [None]*(cat-1)
    return ResultDict(line=line, newstack=newstack)

def _new(maker, input_, iNode):
    index = iNode.instruction[1]
    classname = maker.parent.getConstPoolArgs(index)[0]

    line = ssa_ops.New(maker.parent, classname, input_.monad, iNode.key)
    newstack = input_.stack + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _newarray(maker, input_, iNode):
    vtypes = parseFieldDescriptor(iNode.instruction[1], unsynthesize=False)
    tt = objtypes.verifierToSynthetic(vtypes[0])

    line = ssa_ops.NewArray(maker.parent, input_.stack[-1], tt, input_.monad)
    newstack = input_.stack[:-1] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def _nop(maker, input_, iNode):
    return ResultDict()

def _ret(maker, input_, iNode):
    jump = subproc.DummyRet(input_, maker.blockd[iNode.jsrTarget])
    return ResultDict(jump=jump)

def _return(maker, input_, iNode):
    line = ssa_ops.TryReturn(maker.parent, input_.monad, canthrow=maker.hasmonenter)

    #Our special return block expects only the return values on the stack
    rtype = iNode.instruction[1]
    if rtype is None:
        newstack = []
    else:
        newstack = input_.stack[-getCategory(rtype):]
    return ResultDict(line=line, newstack=newstack)

def _store(maker, input_, iNode):
    cat = getCategory(iNode.instruction[1])
    index = iNode.instruction[2]

    newlocals = list(input_.locals)
    if len(newlocals) < index+cat:
        newlocals += [None] * (index+cat - len(newlocals))

    newlocals[index:index+cat] = input_.stack[-cat:]
    newstack = input_.stack[:-cat]
    return ResultDict(newstack=newstack, newlocals=newlocals)

def _switch(maker, input_, iNode):
    default, raw_table = iNode.instruction[1:3]
    table = [(k, maker.blockd[v]) for k,v in raw_table]
    jump = ssa_jumps.Switch(maker.parent, maker.blockd[default], table, input_.stack[-1:])
    newstack = input_.stack[:-1]
    return ResultDict(jump=jump, newstack=newstack)

def _throw(maker, input_, iNode):
    line = ssa_ops.Throw(maker.parent, input_.stack[-1:])
    return ResultDict(line=line, newstack=[])

def _truncate(maker, input_, iNode):
    dest_c = iNode.instruction[1]
    signed, width = {'B':(True,8), 'C':(False,16), 'S':(True, 16)}[dest_c]

    line = ssa_ops.Truncate(maker.parent, input_.stack[-1], signed=signed, width=width)
    newstack = input_.stack[:-1] + [line.rval]
    return ResultDict(line=line, newstack=newstack)

def genericStackUpdate(maker, input_, iNode):
    b = iNode.before.replace('+','')
    a = iNode.after
    assert(b and set(b+a) <= set('1234'))

    replace = {c:v for c,v in zip(b, input_.stack[-len(b):])}
    newstack = input_.stack[:-len(b)]
    newstack += [replace[c] for c in a]
    return ResultDict(newstack=newstack)

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
                        vops.GOTO: _goto,
                        vops.IF_A: _if_a,
                        vops.IF_ACMP: _if_cmp, #cmp works on ints or objs
                        vops.IF_I: _if_i,
                        vops.IF_ICMP: _if_cmp,
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

                        vops.SWAP: genericStackUpdate,
                        vops.POP: genericStackUpdate,
                        vops.POP2: genericStackUpdate,
                        vops.DUP: genericStackUpdate,
                        vops.DUPX1: genericStackUpdate,
                        vops.DUPX2: genericStackUpdate,
                        vops.DUP2: genericStackUpdate,
                        vops.DUP2X1: genericStackUpdate,
                        vops.DUP2X2: genericStackUpdate,
                        }

def processArrayInfo(env, newarray_info, iNode, vals):
    #There is an unfortunate tendency among Java programmers to hardcode large arrays
    #resulting in the generation of thousands of instructions simply initializing an array
    #With naive analysis, all of the stores can throw and so won't be merged until later
    #Optimize for this case by keeping track of all arrays created in the block with a
    #statically known size and type so we can mark all related instructions as nothrow and
    #hence don't have to end the block prematurely
    op = iNode.instruction[0]
    line = vals.line

    if op == vops.NEWARRAY or op == vops.ANEWARRAY:
        lenvar = line.params[1]
        assert(lenvar.type == SSA_INT)
        if lenvar.const is not None and lenvar.const >= 0:
            #has known, positive dim
            newarray_info[line.rval] = lenvar.const, line.baset
            line.outException = None
    elif op == vops.ARRSTORE or op == vops.ARRSTORE_OBJ:
        m, a, i, x = line.params
        if a not in newarray_info:
            return
        arrlen, baset = newarray_info[a]
        if i.const is None or not 0 <= i.const < arrlen:
            return
        #array element type test to make sure we don't have potential array store exceptions
        if '.' not in baset[0] and not objtypes.isSubtype(env, x.decltype, baset):
            return
        line.outException = None

def slotsRvals(inslots):
    stack = [(None if phi is None else phi.rval) for phi in inslots.stack]
    locals = [(None if phi is None else phi.rval) for phi in inslots.locals]
    return slots_t(monad=inslots.monad.rval, stack=stack, locals=locals)

_jump_instrs = frozenset([vops.GOTO, vops.IF_A, vops.IF_ACMP, vops.IF_I, vops.IF_ICMP, vops.JSR, vops.SWITCH])
class BlockMaker(object):
    def __init__(self, parent, iNodes, inputTypes, returnTypes, except_raw):
        self.parent = parent
        self.blocks = []
        self.blockd = {}

        self.iNodes = [n for n in iNodes if n.visited]
        self.iNodeD = {n.key:n for n in self.iNodes}

        #create map of uninitialized -> initialized types so we can convert them
        self.initMap = {}
        for node in self.iNodes:
            if node.op == vops.NEW:
                self.initMap[node.push_type] = node.target_type
        self.initMap[verifier_types.T_UNINIT_THIS] = verifier_types.T_OBJECT(parent.class_.name)
        self.hasmonenter = any(node.instruction[0] == vops.MONENTER for node in self.iNodes)

        self.entryBlock = self.makeBlockWithInslots(ENTRY_KEY, locals=inputTypes, stack=[])
        self.returnBlock = self.makeBlockWithInslots(RETURN_KEY, locals=[], stack=returnTypes)
        self.returnBlock.jump = ssa_jumps.Return(self, [phi.rval for phi in self.returnBlock.phis])
        self.rethrowBlock = self.makeBlockWithInslots(RETHROW_KEY, locals=[], stack=[verifier_types.THROWABLE_INFO])
        self.rethrowBlock.jump = ssa_jumps.Rethrow(self, [phi.rval for phi in self.rethrowBlock.phis])

        temp = slotsRvals(self.entryBlock.inslots)
        self.inputArgs = [temp.monad] + temp.locals #for ssagraph to copy
        self.entryBlock.phis = []

        #We need to create stub blocks for every jump target so we can add them as successors during creation
        jump_targets = [eh.handler for eh in except_raw]
        for node in iNodes:
            if node.instruction[0] in _jump_instrs:
                jump_targets += node.successors
            if node.instruction[0] == vops.JSR: #add jsr fallthroughs too
                jump_targets.append(node.next_instruction)

        #for simplicity, keep jsr stuff in individual instruction blocks.
        #Note that subproc.py will need to be modified if this is changed
        for node in iNodes:
            if node.instruction[0] in (vops.JSR, vops.RET):
                jump_targets.append(node.key)
        for key in jump_targets:
            if key not in self.blockd:
                self.makeBlock(key)

        self.exceptionhandlers = []
        for (start, end, handler, index) in except_raw:
            catchtype = parent.getConstPoolArgs(index)[0] if index else 'java/lang/Throwable'
            self.exceptionhandlers.append((start, end, self.blockd[handler], catchtype))
        self.exceptionhandlers.append((0, 65536, self.rethrowBlock, 'java/lang/Throwable'))

        #pseudocode loop
        block = self.entryBlock
        curslots = slotsRvals(block.inslots)
        newarray_info = {}
        for node in self.iNodes:
            if not self.continueBlock(node, block):
                if node.key not in self.blockd:
                    self.makeBlock(node.key)

                if block.jump is None:
                    block.jump = ssa_jumps.Goto(parent, self.blockd[node.key])
                oldblock, block = block, self.blockd[node.key]
                if curslots is not None:
                    self.mergeIn((oldblock, False), node.key, curslots)
                curslots = slotsRvals(block.inslots)
                newarray_info = {}
            curslots = self.appendInstrToBlock(block, node, curslots, newarray_info) #arrinfo modified in place

        assert(len(self.blocks) == len(self.blockd))
        for block in self.blocks:
            assert(block.jump is not None and block.phis is not None)
            assert(len(block.predecessors) == len(set(block.predecessors)))
            block.inslots = None

    def _makePhiFromVType(self, block, vt):
        var = self.parent.makeVarFromVtype(vt, self.initMap)
        return None if var is None else ssa_ops.Phi(block, var)

    def makeBlockWithInslots(self, key, locals, stack):
        assert(key not in self.blockd)
        block = BasicBlock(key)
        self.blocks.append(block)
        self.blockd[key] = block

        #create inslot phis
        monad = ssa_ops.Phi(block, self.parent.makeVariable(SSA_MONAD))
        stack = [self._makePhiFromVType(block, vt) for vt in stack]
        locals = [self._makePhiFromVType(block, vt) for vt in locals]
        block.inslots = slots_t(monad=monad, locals=locals, stack=stack)
        block.phis = [phi for phi in [monad] + stack + locals if phi is not None]
        return block

    def makeBlock(self, key):
        node = self.iNodeD[key]
        return self.makeBlockWithInslots(key, node.locals, node.stack)

    def mergeIn(self, from_key, target_key, outslots):
        inslots = self.blockd[target_key].inslots
        assert(len(inslots.stack) == len(outslots.stack) and len(inslots.locals) <= len(outslots.locals))
        phis = [inslots.monad] + inslots.locals + inslots.stack
        vars = [outslots.monad] + outslots.locals[:len(inslots.locals)] + outslots.stack
        for phi, var in zip(phis, vars):
            if phi is not None:
                phi.add(from_key, var)
        self.blockd[target_key].predecessors.append(from_key)

    ###########################################################
    def continueBlock(self, node, block):
        '''Can we continue appending to current block?'''
        return (node.key not in self.blockd) and block.jump is None #fallthrough goto left as None

    def getExceptFallthrough(self, iNode):
        vop = iNode.instruction[0]
        if vop == vops.RETURN:
            return self.blockd[RETURN_KEY]
        elif vop == vops.THROW:
            return None
        key = iNode.successors[0]
        if key not in self.blockd:
            self.makeBlock(key)
        return self.blockd[key]

    def appendInstrToBlock(self, block, iNode, inslots, newarray_info):
        parent, initMap = self.parent, self.initMap
        instr = iNode.instruction

        # internal variables won't have any preset type info associated, so we should add in the info from the verifier
        assert(len(inslots.stack) == len(iNode.stack) and len(inslots.locals) == len(iNode.locals))
        for ivar, vt in zip(inslots.stack + inslots.locals, iNode.stack + iNode.locals):
            if ivar and ivar.type == SSA_OBJECT and ivar.decltype is None:
                parent.setObjVarData(ivar, vt, initMap)

        vals = _instructionHandlers[instr[0]](self, inslots, iNode)
        processArrayInfo(parent.env, newarray_info, iNode, vals) #modifies newarray_info and vals

        line, jump = vals.line, vals.jump
        newstack = vals.newstack if vals.newstack is not None else inslots.stack
        newlocals = vals.newlocals if vals.newlocals is not None else inslots.locals
        newmonad = line.outMonad if (line and line.outMonad) else inslots.monad
        outslot_norm = slots_t(monad=newmonad, locals=newlocals, stack=newstack)

        if line is not None:
            block.lines.append(line)

        if line is not None and line.outException is not None:
            assert(jump is None)
            fallthrough = self.getExceptFallthrough(iNode)
            jump = ssa_jumps.OnException(parent, iNode.key, line, self.exceptionhandlers, fallthrough)

            outslot_except = slots_t(monad=newmonad, locals=newlocals, stack=[line.outException])
            for suc in jump.getExceptSuccessors():
                self.mergeIn((block, True), suc.key, outslot_except)

        block.jump = jump
        if jump is None:
            unmerged_slots = outslot_norm
        else:
            unmerged_slots = None
            #Make sure that branch targets are distinct, since this is assumed everywhere
            #Only necessary for if statements as the other jumps merge targets automatically
            #If statements with both branches jumping to same target are replaced with gotos
            block.jump = jump = jump.reduceSuccessors([])

            if isinstance(jump, subproc.ProcCallOp):
                self.mergeJSROut(iNode, block, outslot_norm)
            else:
                for suc in jump.getNormalSuccessors():
                    self.mergeIn((block, False), suc.key, outslot_norm)
        return unmerged_slots

    def mergeJSROut(self, jsrnode, block, outslot_norm):
        retnode = self.iNodeD[jsrnode.returnedFrom]
        jump = block.jump
        target_key, ft_key = jump.target.key, jump.fallthrough.key
        assert(ft_key == jsrnode.next_instruction)

        #first merge regular jump to target
        self.mergeIn((block, False), target_key, outslot_norm)
        #create merged outslots for fallthrough
        fromcall = jump.output
        localoff = jump.out_localoff
        monad, stack, locals = fromcall[0], fromcall[1:localoff], fromcall[localoff:]

        mask = [mask for key, mask in retnode.masks if key == target_key][0]
        zipped = itertools.izip_longest(outslot_norm.locals, locals, fillvalue=None)
        merged = [(y if i in mask else x) for i,(x,y) in enumerate(zipped)]
        jump.debug_skipvars = set(merged) - set(locals)

        outslot_merged = slots_t(monad=monad, locals=merged, stack=stack)
        #merge merged outputs with fallthrough
        self.mergeIn((block, False), ft_key, outslot_merged)
