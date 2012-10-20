import itertools

import error as error_types
import opnames
import bytecode
from verifier_types import *

def parseFieldDescriptors(desc_str, unsynthesize=True):
    baseTypes = {'B':[T_BYTE], 'C':[T_CHAR], 'D':T_DOUBLE, 'F':[T_FLOAT],
                 'I':[T_INT], 'J':T_LONG, 'S':[T_SHORT], 'Z':[T_BOOL]}

    fields = []
    while desc_str:
        dim = 0
        while desc_str[0] == '[':
            desc_str = desc_str[1:]
            dim += 1
            
        if desc_str[0] == 'L':
            end = desc_str.index(';')
            name = desc_str[1:end]
            desc_str = desc_str[end+1:]
            baset = [T_OBJECT(name)]
        else:
            baset = baseTypes[desc_str[0]]
            desc_str = desc_str[1:]

        if dim:
            #Hotspot considers byte[] and bool[] identical for type checking purposes
            if unsynthesize and baset[0] == T_BOOL:
                baset = [T_BYTE]
            baset = [T_ARRAY(baset[0], dim)]
        elif len(baset) == 1:
            #synthetics are only meaningful as basetype of an array
            #if they are by themselves, convert to int.
            baset = [unSynthesizeType(baset[0])] if unsynthesize else [baset[0]]
        
        fields += baset
    return fields

#get a single descriptor
def parseFieldDescriptor(desc_str, unsynthesize=True):
    rval = parseFieldDescriptors(desc_str, unsynthesize)
    if rval[0].cat2:
        rval, extra = rval[:2], rval[2:]
    else:
        rval, extra = rval[:1], rval[1:]
    assert(not extra)
    return rval

#Parse a string to get a Java Method Descriptor
def parseMethodDescriptor(desc_str, unsynthesize=True):
    assert(desc_str[0] == '(')
    arg_end = desc_str.index(')')

    args, rval = desc_str[1:arg_end], desc_str[arg_end+1:]
    args = parseFieldDescriptors(args, unsynthesize)

    if rval == 'V':
        rval = []
    else:
        rval = parseFieldDescriptor(rval, unsynthesize)
    return args, rval

#Adds self argument for nonstatic. Constructors must be handled seperately
def parseUnboundMethodDescriptor(desc_str, target, isstatic):
    args, rval = parseMethodDescriptor(desc_str)
    if not isstatic:
        args = [T_OBJECT(target)] + args
    return args, rval

def isUnsplit(vals, i):
    v = vals[i]
    if not v.top:
        other = vals[i+1]
    else:
        if i <= 0: #without this check the index would silently wrap around
            return False
        other = vals[i-1]
    return (v.type == other.type and v.top != other.top)

#Instruction stack changes

#Type agnostic stack operations
genericStackCodes = {opnames.POP:(1,()), opnames.POP2:(2,()), opnames.DUP:(1,(0,0)),
                      opnames.DUPX1:(2,(0,1,0)), opnames.DUPX2:(3,(0,2,1,0)),
                      opnames.DUP2:(2,(1,0,1,0)), opnames.DUP2X1:(3,(1,0,2,1,0)),
                      opnames.DUP2X2:(4,(1,0,3,2,1,0)),
                      opnames.SWAP:(2,(0,1))}

#ex dup2x2 is coded as 3210 -> 103210
def genericStackUpdate((num, replaceCodes), stack):
    vals = stack[-num:]
    assert(len(vals) == num)
    
    newvals = tuple(vals[num-i-1] for i in replaceCodes)
    if newvals != vals: 
        stack = stack[:-num] + newvals
        #make sure we didn't split any longs

        for i,v in enumerate(stack):
            if v.cat2:
                assert(isUnsplit(stack, i))
    return stack

stackCharPatterns = {opnames.NOP:'-', opnames.CONSTNULL:'-N', opnames.LCMP:'LL-I',
                     opnames.ARRLEN:'Y-I',opnames.MONENTER:'A-',opnames.MONEXIT:'A-',
                     opnames.INSTANCEOF:'A-I',opnames.CONST:'-{0}',
                     opnames.CONVERT:'{0}-{1}',opnames.TRUNCATE:'I-I',
                     opnames.FCMP:'{0}{0}-I', opnames.IF_I:'I-',
                     opnames.IF_ICMP:'II-',opnames.IF_A:'A-',opnames.IF_ACMP:'AA-',
                     opnames.GOTO:'-', opnames.SWITCH:'I-', opnames.IINC:'-',
                     
                     opnames.ADD:'{0}{0}-{0}', opnames.SUB:'{0}{0}-{0}',
                     opnames.MUL:'{0}{0}-{0}', opnames.DIV:'{0}{0}-{0}',
                     opnames.REM:'{0}{0}-{0}', opnames.XOR:'{0}{0}-{0}',
                     opnames.AND:'{0}{0}-{0}', opnames.OR:'{0}{0}-{0}',
                     opnames.SHL:'{0}I-{0}', opnames.SHR:'{0}I-{0}',
                     opnames.USHR:'{0}I-{0}', opnames.NEG:'{0}-{0}',}

_decode_char = {'N':(T_NULL,), 'I':(T_INT,), 'F':(T_FLOAT,), 'L':T_LONG,
                'D':T_DOUBLE, 'B':(T_BYTE,), 'C':(T_CHAR,), 'S':(T_SHORT,),
                'Z':(T_BYTE,), 'Y':(T_WILDCARD_ARRAY,),
                'A':(T_OBJECT('java/lang/Object'),)}

def decodePatternString(s):
    vals = []
    for c in s:
        vals += _decode_char[c]
    return tuple(vals)

def getSpecificStackCode(code, instr):
    op = instr[0]
    cpool = code.class_.cpool

    if op in (opnames.PUTSTATIC,opnames.GETSTATIC,opnames.PUTFIELD,opnames.GETFIELD):
        target, name, desc = cpool.getArgsCheck('Field', instr[1])
        vals = tuple(parseFieldDescriptor(desc))
        
        if 'put' in op:
            before, after = vals, ()
        else:
            before, after = (), vals
        if not 'static' in op:
            before = (T_OBJECT(target),) + before
            
    elif op in (opnames.INVOKESPECIAL,opnames.INVOKESTATIC,opnames.INVOKEVIRTUAL,opnames.INVOKEINTERFACE):
        methType = 'InterfaceMethod' if op == opnames.INVOKEINTERFACE else 'Method'

        target, name, desc = cpool.getArgsCheck(methType, instr[1])
        #If we specifiy a method on an array, it's easier to just replace that with Object
        if target[0] == '[':
            target = 'java/lang/Object'
        before, after = map(tuple, parseUnboundMethodDescriptor(desc, target, ('static' in op)))
    elif op in (opnames.ANEWARRAY,opnames.CHECKCAST,opnames.LDC,opnames.MULTINEWARRAY):
        index = instr[1]
        if op == opnames.LDC:
            constantTypes =  {'Int':(T_INT,), 'Float':(T_FLOAT,),
                              'Long':T_LONG, 'Double':T_DOUBLE,
                              'String':(T_OBJECT('java/lang/String'),),
                              'Class':(T_OBJECT('java/lang/Class'),)}
            typen = cpool.getType(index)
            before, after = (), constantTypes[typen]
            assert(len(after) == instr[2])
            if typen == 'Class':
                assert(code.class_.version >= (49,0))
        else:
            target = cpool.getArgsCheck('Class', instr[1])
            if target[0] == '[':
                target = parseFieldDescriptor(target)[0]
            else:
                target = T_OBJECT(target)
            
            if op == opnames.ANEWARRAY:
                before, after = (T_INT,), (T_ARRAY(target),)
            elif op == opnames.CHECKCAST:
                before, after = (T_OBJECT('java/lang/Object'),), (target,)
            elif op == opnames.MULTINEWARRAY:
                dim = instr[2]
                assert(dim != 0 and dim <= target.dim)
                before, after = (T_INT,)*dim, (target,)
    elif op == opnames.ARRSTORE or op == opnames.ARRLOAD:
        typen = instr[1]
        baset = _decode_char[typen]
        
        arrayt = (T_ARRAY(baset[0]), T_INT)
        elemt = (unSynthesizeType(baset[0]),) + baset[1:]
        
        if op == opnames.ARRSTORE:
            before, after = arrayt + elemt, ()
        else:
            before, after = arrayt, elemt
    elif op == opnames.NEWARRAY:
        typen = instr[1]
        baset = _decode_char[typen]
        before, after = (T_INT,), (T_ARRAY(baset[0]),)
    elif op == opnames.THROW:
        before, after = (T_OBJECT('java/lang/Throwable'),), ()
    elif op == opnames.RETURN:
        typen = instr[1]
        if typen is None:
            before = ()
        else:
            before = decodePatternString(typen)
        after = ()
    else: #normal instruction which uses hardcoded template string
        s = stackCharPatterns[op]
        if op == opnames.CONVERT:
            s = s.format(instr[1], instr[2])
        elif '{0}' in s:
            s = s.format(instr[1])

        b, sep, a = s.partition('-')
        before = decodePatternString(b)
        after = decodePatternString(a)
    assert(not before or isinstance(before[-1], tuple))
    return before, after

def isUninitNonthis(x):
    return x.isObject and not x.isInit and x.origin is not None

class InstructionNode(object):
    NO_RETURN = 1<<0
    NEED_CONSTRUCTOR = 1<<1
    NOT_CONSTRUCTED = 1<<2
    #These are used only in __str__
    _flag_vals = {1<<0:'NO_RETURN', 1<<1:'NEED_CONSTRUCTOR', 
        1<<2:'NOT_CONSTRUCTED'}

    def __init__(self, code, successorTable, key):
        self.key = key
        assert(self.key is not None) #if it is this will cause problems with origin tracking

        self.code = code
        self.env = code.class_.env
        cpool = self.code.class_.cpool

        self.instruction = code.bytecode[key]
        self.op = self.instruction[0]
        op = self.op

        #initial state
        self.visited, self.changed = False,False
        
        #get successors
        self.successors = []
        if op not in (opnames.GOTO,opnames.JSR,opnames.RET,opnames.SWITCH,opnames.THROW,opnames.RETURN):
            next_ = successorTable.get(key, None) #It's ok to fall off as long 
            #as this instruction is never reached. If so, None will force an error later
            self.successors.append(next_)

        if op in (opnames.GOTO,opnames.JSR):
            self.successors.append(self.instruction[1])
        elif op in (opnames.IF_I,opnames.IF_ICMP,opnames.IF_A,opnames.IF_ACMP):
            self.successors.append(self.instruction[2])
        elif op == opnames.SWITCH:
            opname, default, jumps = self.instruction
            targets = (default,)
            if jumps:
                targets += zip(*jumps)[1]
            self.successors = sorted(set(targets))

        #precalc values
        if op == opnames.JSR:
            self.returnPoint = successorTable[key]
            self.returnedFrom = None #keep track of which rets can return here - There Can Only Be One!
        elif op == opnames.INVOKEINIT :
            index = self.instruction[1]
            target, name, desc = cpool.getArgsCheck('Method', index)
            assert(name == '<init>' and desc[-1] == 'V')
            #we don't add unint this param since we have to check it specially anyway
            before, after = map(tuple, parseMethodDescriptor(desc)) 
            assert(not after)
            self.before, self.target = before, target
        elif op == opnames.NEW:
            index = self.instruction[1]
            target = cpool.getArgsCheck('Class', index)
            self.newt = T_UNINIT_OBJECT(target, self.key)
        elif op not in genericStackCodes:
            if op not in (opnames.STORE ,opnames.JSR, opnames.RET, 
                        opnames.INVOKEINIT, opnames.LOAD, opnames.NEW, 
                        opnames.IINC, opnames.ARRLOAD_OBJ, opnames.ARRSTORE_OBJ):
                self.before, self.after = getSpecificStackCode(code, self.instruction)

    def error(self, msg, *args):
        msg = msg.format(*args, self=self)
        raise error_types.VerificationError(msg)

    def _assertStackTop(self, needed):
        if needed and not isAssignableSeq(self.env, self.stack[-len(needed):], needed):
            self.error('Invalid arguments on stack\nExpected: {}\nFound: {}\n\n{self}', map(str, needed), map(str, self.stack[-len(needed):]))

    def update(self, iNodes, exceptions):
        assert(self.visited)
        self.changed = False
        self._checkFlags()

        newstate = self._getNewState()
        newstack, newlocals, newmasks, newflags = newstate

        if self.op == opnames.JSR and self.returnedFrom is not None:
            iNodes[self.returnedFrom].changed = True

        #Merge into exception handlers first
        for (start,end),(handler,execStack) in exceptions:
            if start <= self.key < end:
                if self.op != opnames.INVOKEINIT:
                    handler.mergeNewState((execStack, newlocals, newmasks, newflags))
                else: #two cases since the ctor may suceed or fail before throwing
                    #If ctor is being invoked on this, update flags appropriately
                    if self.isThisConstructor:
                        flags1 = self.flags | InstructionNode.NO_RETURN
                        flags2 = self.flags & ~InstructionNode.NEED_CONSTRUCTOR
                    else:
                        flags1 = flags2 = self.flags

                    failState = execStack, self.locals, self.masks, flags1
                    sucessState = execStack, newlocals, newmasks, flags2
                    handler.mergeNewState(failState)
                    handler.mergeNewState(sucessState)

        #Now regular successors
        if self.op == opnames.RET: #ret needs special handling because the new state depends on the successor
            for k in self.jsrSources:
                node1 = iNodes[k]

                if node1.returnedFrom is not None and node1.returnedFrom != self.key:
                    assert(0) #multiple returns to single jsr
                node1.returnedFrom = self.key

                #Note, it is important to set node.returnedFrom even if we're skipping it
                #Because if/when that node does become reached, we need to know which ret
                #instruction to mark as changed since the changed bit might not propogate
                #through the whole subroutine
                if not node1.visited:
                    continue
                templocals = self._mergeRetMask(node1.locals, newlocals)

                node2 = iNodes[node1.returnPoint]
                node2.mergeNewState((newstack, templocals, newmasks, newflags))
        else:
            for node in [iNodes[k] for k in self.successors]:
                node.mergeNewState(newstate)
                    
    def _checkFlags(self):
        if self.op == opnames.RETURN:
            inc = InstructionNode
            if (self.flags & inc.NEED_CONSTRUCTOR) and (self.flags & inc.NOT_CONSTRUCTED):
                self.error('Invalid flags at return\n\n{self}')    
            if (self.flags & (inc.NO_RETURN)):
                self.error('Invalid flags at return\n\n{self}')    

    def _getNewState(self): #this is actually called externally over in ssa.blockmaker as a temporary hack
        newstack, newlocals, newmasks, newflags = self.stack, self.locals, self.masks, self.flags
        op = self.op
        env = self.code.class_.env
        assert(type(self.stack) == tuple)

        #check if instruction needs to modify locals (or merely read them, which also marks them modified)
        if op in (opnames.STORE,opnames.JSR,opnames.RET,opnames.INVOKEINIT,opnames.LOAD,opnames.NEW,opnames.IINC):
            newstack, newlocals, newmasks, newflags = self._updateLocals()        
        elif op in (opnames.ARRLOAD_OBJ, opnames.ARRSTORE_OBJ):
            if op == opnames.ARRLOAD_OBJ:
                t = self.stack[-2].baset 
                before, after = (T_ARRAY(t), T_INT), (t,)
            else:
                t = self.stack[-3].baset 
                before, after = (T_ARRAY(t), T_INT, t), ()
            self._assertStackTop(before)
            newstack = self.stack[:-len(before)] + after
        elif op in genericStackCodes:
            newstack = genericStackUpdate(genericStackCodes[op], newstack)
        else:
            b,a = self.before, self.after
            if len(b):
                #Temp hack to workaround that this might be uninitialized if accessing fields defined in same class
                if op not in (opnames.PUTFIELD,opnames.GETFIELD):
                    self._assertStackTop(b)
                newstack = self.stack[:-len(b)] + a
            else: #special code required if len=0 since slice[-0:] doesn't do what we want
                newstack = self.stack + a

        return newstack, newlocals, newmasks, newflags
        
    def _updateLocals(self):
        mutlocals = list(self.locals)
        changed = set()
        op = self.op

        if op == opnames.STORE:
            typen, i = self.instruction[1:]

            if typen == 'A': #special handling for objects and return addresses
                t, size = self.stack[-1], 1
                if not (t.isObject or t.type == 'address'):
                    self.error('Object or address expected on stack\n{self}')
                t = (t,)
            else:
                t = _decode_char[typen]
                size = len(t) #1 or 2 depending on category
                self._assertStackTop(t)
            newstack = self.stack[:-size]
            mutlocals += [T_INVALID]* (i+size - len(mutlocals))    
            mutlocals[i:i+size] = t
            changed = set(range(i, i+size))

        elif op == opnames.LOAD:
            typen, i = self.instruction[1:]
            t = _decode_char[typen]
            size = len(t)
            
            if typen == 'A':
                t = (self.locals[i],)
                if not (t[0].isObject):
                    self.error('Expected object in locals but got {0}\n{self}', t[0])
            else:
                x = self.locals[i:i+size]
                if not (self.locals[i:i+size] == t):
                    self.error('Invalid types in locals\n{self}')
            newstack = self.stack + t
            #Apparently, even accessing the varaible sets the mask
            changed = set(range(i, i+size))

        elif op == opnames.IINC:
            index = self.instruction[1]
            if not (self.locals[index] == T_INT):
                self.error('Expected integer in locals but got {0}\n{self}', self.locals[index])
            newstack = self.stack
            changed.add(index)
        
        elif (op == opnames.INVOKEINIT or op == opnames.NEW):
            if op == opnames.INVOKEINIT:
                env = self.code.class_.env
                argcnt = len(self.before)
                self._assertStackTop(self.before)

                old = self.stack[-argcnt-1]
                assert(old.isObject and not old.isInit)
                #If origin is None, it is this, so we can invoke superclass ctors
                self.isThisConstructor = old.origin is None
                assert(old.baset == self.target or old.origin is None and self.target in env.getSupers(old.baset))
                new = T_OBJECT(old.baset)
                newstack = self.stack[:-argcnt-1]
            else: #for new, mark all existing unit objects from this instruction as invalid
                old = self.newt
                new = T_INVALID
                newstack = self.stack

            for i,x in enumerate(mutlocals):
                if x == old:
                    mutlocals[i] = new
                    changed.add(i)

            newstack = tuple((new if x == old else x) for x in newstack)
            if op == opnames.NEW:
                newstack += (self.newt,)

        elif op == opnames.JSR or op == opnames.RET:
            for i,x in enumerate(mutlocals):
                #uninit this is apparently allowed
                if isUninitNonthis(x):
                    mutlocals[i] = T_INVALID
                    changed.add(i)
            nsi = ((T_INVALID if isUninitNonthis(x) else x) for x in self.stack)
            newstack = tuple(nsi)
        
        masks = [(entry,(cset | changed)) for entry,cset in self.masks]

        if op == opnames.JSR:
            entry = self.instruction[1]
            assert(all(ec[0] != entry for ec in masks))
            if not masks or entry not in zip(*masks)[0]:
                masks.append((entry,frozenset()))
            newstack += (T_ADDRESS(entry),)
        elif op == opnames.RET:
            index = self.instruction[1]
            item = self.locals[index]
            assert(item.type == 'address')
            entry = item.entryPoint
            self.jsrTarget = entry #store for later convienence in SSA creation

            #ret requires special merging code so just store this stuff for later
            self.jsrSources = [k for k,v in self.code.bytecode.items() if v[0]==opnames.JSR and v[1]==entry] 
            self.mask = None
            while masks:
                e, cset = masks.pop()
                if e == entry:
                    self.mask = cset
                    break
            assert(self.mask is not None)
        newlocals = tuple(mutlocals)            
        newmasks = tuple(masks)            

        if op == opnames.INVOKEINIT and self.isThisConstructor:
            newflags = self.flags & ~InstructionNode.NOT_CONSTRUCTED
        else:
            newflags = self.flags
        return newstack, newlocals, newmasks, newflags


    def mergeNewState(self, newstate):
        if not self.visited:
            self.stack, self.locals, self.masks, self.flags = newstate
            self.visited, self.changed = True, True
            return
        
        newstack, newlocals, newmasks, newflags = newstate
        env = self.code.class_.env

        #merge stack
        old_newstack = newstack
        newstack = mergeTypeSequences(env, newstack, self.stack, False)
        if newstack is None:
            self.error('Inconsistent stack height\nCurrent: {}\nNew: {}\n\n{self}', map(str, self.stack), map(str, old_newstack))
        elif T_INVALID in newstack:
            self.error('Inconsistent stack types\nCurrent: {}\nNew: {}\n\n{self}', map(str, self.stack), map(str, old_newstack))

        #merge locals
        newlocals = mergeTypeSequences(env, newlocals, self.locals, True)

        #merge masks
        last_match = -1
        mergedmasks = []
        for entry1, mask1 in self.masks:
            for j,(entry2,mask2) in enumerate(newmasks):
                if j>last_match and entry1 == entry2:
                    item = entry1, (mask1 | mask2)
                    mergedmasks.append(item)
                    last_match = j
        newmasks = tuple(mergedmasks)
        newflags = self.flags | newflags
        
        if newstack != self.stack:
            self.stack, self.changed = newstack, True
        if newlocals != self.locals:
            self.locals, self.changed = newlocals, True
        if newmasks != self.masks:
            self.masks, self.changed = newmasks, True
        if newflags != self.flags:
            self.flags, self.changed = newflags, True           

    def _mergeRetMask(self, oldlocals, newlocals):
        mask = self.mask
        zipped = itertools.izip_longest(oldlocals, newlocals, fillvalue=T_INVALID)
        mergedlocals = tuple((new if i in mask else old) for i,(old,new)
                               in enumerate(zipped))
        return mergedlocals

    def __str__(self):
        lines = ['{}: {}'.format(self.key, bytecode.printInstruction(self.instruction))]
        if self.visited:
            flags = [v for k,v in InstructionNode._flag_vals.items() if k & self.flags]
            if flags:
                lines.append('Flags: ' + ', '.join(flags))
            lines.append('Stack: ' + ', '.join(map(str, self.stack)))
            lines.append('Locals: ' + ', '.join(map(str, self.locals)))
            if self.masks:
                lines.append('Masks:')
                lines += ['\t{}: {}'.format(entry, sorted(cset)) for entry,cset in self.masks]
        else:
            lines.append('\tunvisited')
        return '\n'.join(lines) + '\n'

def verifyBytecode(code):
    method, class_ = code.method, code.class_
    args, rval = parseUnboundMethodDescriptor(method.descriptor, class_.name, method.static)
    env = class_.env
    
    startFlags = 0
    #Object has no superclass to construct, so it doesn't get an uninit this
    if method.isConstructor and class_.name != 'java/lang/Object':
        assert(args[0] == T_OBJECT(class_.name))
        args[0] = T_UNINIT_THIS(class_.name)
        startFlags |= InstructionNode.NEED_CONSTRUCTOR
        startFlags |= InstructionNode.NOT_CONSTRUCTED
    assert(len(args) <= 255)
    args = tuple(args)
    
    maxstack, maxlocals = code.stack, code.locals
    assert(len(args) <= maxlocals)

    offsets = sorted(code.bytecode)
    successorTable = dict(zip(offsets[:-1],offsets[1:]))

    iNodes = [InstructionNode(code, successorTable, key) for key in offsets]
    iNodeLookup = {n.key:n for n in iNodes}

    keys = frozenset(iNodeLookup)
    for raw in code.except_raw:
        if not ((0 <= raw.start < raw.end) and (raw.start in keys) and 
            (raw.handler in keys) and (raw.end in keys or raw.end == code.codelen)):

            keylist = sorted(keys) + [code.codelen]
            msg = "Illegal exception handler: {}\nValid offsets are: {}".format(raw, ', '.join(map(str, keylist)))
            raise error_types.VerificationError(msg)

    def makeException(rawdata):
        if rawdata.type_ind:        
            typen = class_.cpool.getArgsCheck('Class', rawdata.type_ind)
        else:
            typen = 'java/lang/Throwable'
        t = T_OBJECT(typen);
        if not (isAssignable(env, t, T_OBJECT('java/lang/Throwable'))):
            error_types.VerificationError('Invalid exception handler type: ' + typen)
        return (rawdata.start, rawdata.end), (iNodeLookup[rawdata.handler], (t,))
    exceptions = map(makeException, code.except_raw)

    start = iNodes[0]
    start.stack, start.locals, start.masks, start.flags = (), args, (), startFlags   
    start.visited, start.changed = True, True

    done = False
    while not done:
        done = True
        for node in iNodes:
            if node.changed:
                node.update(iNodeLookup, exceptions)
                done = False
    return iNodes