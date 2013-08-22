import itertools

from .. import error as error_types
from .. import opnames
from .. import bytecode
from .verifier_types import *
from .descriptors import *

#This verifier is intended to closely replicate the behavior of Hotspot's inference verifier
#http://hg.openjdk.java.net/jdk7/jdk7/jdk/file/tip/src/share/native/common/check_code.c

stackCharPatterns = {opnames.NOP:'-',
                    opnames.CONSTNULL:'-A', opnames.CONST:'-{0}',
                    opnames.LDC:'-?',
                    opnames.LOAD:'-{0}', opnames.STORE:'{0}-',
                    # opnames.ARRLOAD:'[{0}]I-{1}', opnames.ARRSTORE:'[{0}]I{1}-',
                    opnames.ARRLOAD_OBJ:'[A]I-A', opnames.ARRSTORE_OBJ:'[A]IA-',
                    opnames.IINC:'-',

                    #Stack manip handled elsewhere
                    opnames.POP:'1-', opnames.POP2:'2+1-',
                    opnames.DUP:'1-11', opnames.DUPX1:'21-121', opnames.DUPX2:'3+21-1321',
                    opnames.DUP2:'2+1-2121', opnames.DUP2X1:'32+1-21321', opnames.DUP2X2:'4+32+1-214321',
                    opnames.SWAP:'12-21',

                    opnames.ADD:'{0}{0}-{0}', opnames.SUB:'{0}{0}-{0}',
                    opnames.MUL:'{0}{0}-{0}', opnames.DIV:'{0}{0}-{0}',
                    opnames.REM:'{0}{0}-{0}', opnames.XOR:'{0}{0}-{0}',
                    opnames.AND:'{0}{0}-{0}', opnames.OR:'{0}{0}-{0}',
                    opnames.SHL:'{0}I-{0}', opnames.SHR:'{0}I-{0}',
                    opnames.USHR:'{0}I-{0}', opnames.NEG:'{0}-{0}',

                    opnames.CONVERT:'{0}-{1}',opnames.TRUNCATE:'I-I',
                    opnames.LCMP:'JJ-I', opnames.FCMP:'{0}{0}-I',
                    opnames.IF_I:'I-', opnames.IF_ICMP:'II-',
                    opnames.IF_A:'A-', opnames.IF_ACMP:'AA-', #under standard ordering, if_a comes much later

                    opnames.GOTO:'-', opnames.JSR:'-R', opnames.RET:'-',
                    opnames.SWITCH:'I-',
                    #return
                    #field, invoke

                    opnames.NEW:'-A', opnames.NEWARRAY:'I-A', opnames.ANEWARRAY:'I-A',
                    opnames.ARRLEN:'[?]-I',
                    opnames.THROW:'A-', #Hotspot uses special code 'O', but it doesn't actually matter
                    opnames.CHECKCAST:'A-A', opnames.INSTANCEOF:'A-I',
                    opnames.MONENTER:'A-',opnames.MONEXIT:'A-',
                    #multinewarray
                }

_invoke_ops = (opnames.INVOKESPECIAL,opnames.INVOKESTATIC,opnames.INVOKEVIRTUAL,opnames.INVOKEINTERFACE,opnames.INVOKEINIT,opnames.INVOKEDYNAMIC)

def getSpecificStackCode(code, instr):
    op = instr[0]
    cpool = code.class_.cpool

    #special cases, which either don't have a before or an after
    if op in (opnames.PUTSTATIC,opnames.GETSTATIC,opnames.PUTFIELD,opnames.GETFIELD,opnames.MULTINEWARRAY) + _invoke_ops:
        before = {opnames.GETSTATIC:'', opnames.GETFIELD:'A'}.get(op)
        after = {opnames.PUTSTATIC:'', opnames.PUTFIELD:'', opnames.MULTINEWARRAY:'A'}.get(op)
        #before, after may be None if unused
    elif op == opnames.ARRSTORE or op == opnames.ARRLOAD:
        typen = instr[1]
        type2 = 'I' if typen in 'BCS' else typen
        assert(typen in 'IFJDABCS')
        arrpart = '[{}]I'.format(typen)

        if op == opnames.ARRSTORE:
            before, after = arrpart+type2, ''
        else:
            before, after = arrpart, type2
    elif op == opnames.RETURN:
        typen = instr[1]
        before = '' if typen is None else typen
        after = ''
    else: #normal instruction which uses hardcoded template string
        s = stackCharPatterns[op]
        s = s.format(*instr[1:])
        before, sep, after = s.partition('-')
    return before, after

def _loadFieldDesc(cpool, ind):
    try:
        target, name, desc = cpool.getArgsCheck('Field', ind)
    except (IndexError, KeyError) as e: #TODO: find a way to make sure we aren't catching unexpected exceptions
        return None
    try:
        return parseFieldDescriptor(desc)
    except ValueError as e:
        return None

def _loadMethodDesc(cpool, ind):
    try:
        if cpool.getType(ind) not in ('Method','InterfaceMethod'):
            return None
        target, name, desc = cpool.getArgs(ind)
    except (IndexError, KeyError) as e: #TODO: find a way to make sure we aren't catching unexpected exceptions
        return None
    try:
        return parseMethodDescriptor(desc)
    except ValueError as e:
        return None

def _indexToCFMInfo(cpool, ind, typen):
    actual = cpool.getType(ind)
    #JVM_GetCPMethodClassNameUTF accepts both
    assert(actual == typen or actual == 'InterfaceMethod' and typen == 'Method')

    cname = cpool.getArgs(ind)[0]
    if cname.startswith('['):
        try:
            return parseFieldDescriptor(cname)[0]
        except ValueError as e:
            return T_INVALID
    else:
        return T_OBJECT(cname)

_vtypeMap = {T_INT:'I',T_FLOAT:'F',T_LONG:'J',T_DOUBLE:'D',T_LONG2:'',T_DOUBLE2:''}
def vtype2Char(fi):
    return _vtypeMap.get(fi, 'A')

class InstructionNode(object):
    #Difference from Hotspot: We use seperate variable for REACHED and change and flag CONSTRUCTED to or flag NOT_CONSTRUCTED
    NO_RETURN = 1<<0
    NEED_CONSTRUCTOR = 1<<1
    NOT_CONSTRUCTED = 1<<2

    #These are used only in __str__ for display purposes
    _flag_vals = {1<<0:'NO_RETURN', 1<<1:'NEED_CONSTRUCTOR',
        1<<2:'NOT_CONSTRUCTED'}

    def __init__(self, code, offsetList, key):
        self.key = key
        assert(self.key is not None) #if it is this will cause problems with origin tracking

        self.code = code
        self.env = code.class_.env
        self.class_ = code.class_
        self.cpool = self.class_.cpool

        self.instruction = code.bytecode[key]
        self.op = self.instruction[0]

        self.visited, self.changed = False, False
        self.offsetList = offsetList #store for usage calculating JSRs and the like
        self._verifyOpcodeOperands()
        self._precomputeValues()

        #Field correspondences
        # invoke*: op2.fi -> target_type
        # new, checkcast, newarray, anewarray, multinewarray, instanceof:
        #   op.fi -> push_type
        # new: op2.fi -> target_type

    def _verifyOpcodeOperands(self):

        def isTargetLegal(addr):
            return addr is not None and addr in self.offsetList
        def verifyCPType(ind, types):
            if ind < 0 or ind >= self.cpool.size():
                self.error('Invalid constant pool index {}', ind)
            t = self.cpool.getType(ind)
            if t not in types:
                self.error('Invalid constant pool type at {}.\nFound {} but expected {}', ind, t, types)

        op = self.op
        major = self.class_.version[0]

        if op == opnames.JSR:
            self.returnedFrom = None #keep track of which rets can return here - There Can Only Be One!

        if op in (opnames.IF_A, opnames.IF_I, opnames.IF_ICMP, opnames.IF_ACMP, opnames.JSR, opnames.GOTO):
            if not isTargetLegal(self.instruction[-1]):
                self.error('Illegal jump target')
        elif op == opnames.SWITCH:
            default, jumps, padding = self.instruction[1:]
            if padding != '\0'*len(padding):
                self.error('Padding must be 0 in switch instruction')

            keys, targets = zip(*jumps) if jumps else ([],[])
            if list(keys) != sorted(keys):
                self.error('Lookupswitch keys must be in sorted order')
            if not all(isTargetLegal(x) for x in targets):
                self.error('Illegal jump target')

        elif op == opnames.LDC:
            ind, cat = self.instruction[1:]
            if cat == 1:
                types = 'Int','Float','String'
                if major >= 49:
                    types += 'Class',
                if major >= 51:
                    types += 'MethodHandle','MethodType'
            else:
                types = 'Long','Double'
            verifyCPType(ind, types)

        elif op in (opnames.PUTFIELD, opnames.PUTSTATIC, opnames.GETFIELD, opnames.GETSTATIC):
            ind = self.instruction[1]
            verifyCPType(ind, ['Field'])
            if op in (opnames.PUTFIELD, opnames.GETFIELD):
                self._setProtected(True)
        elif op in _invoke_ops:
            ind = self.instruction[1]
            expected = {opnames.INVOKEINTERFACE:'InterfaceMethod', opnames.INVOKEDYNAMIC:'NameAndType'}.get(op, 'Method')
            verifyCPType(ind, [expected])

            target, name, desc = self.cpool.getArgs(ind)
            isctor = (name == '<init>')
            isinternal = name.startswith('<')

            classz = _indexToCFMInfo(self.cpool, ind, 'Method') if op != opnames.INVOKEDYNAMIC else OBJECT_INFO
            self.target_type = classz

            if isctor:
                if op != opnames.INVOKEINIT:
                    assert(op != opnames.INVOKESPECIAL) #should have been converted already
                    self.error('Initializers must be called with invokespecial')
            else:
                if isinternal: #I don't think this is actually reachable in Hotspot due to earlier checks
                    self.error('Attempt to call internal method')
                if op == opnames.INVOKESPECIAL:
                    if classz.extra not in self.class_.getSuperclassHierarchy():
                        self.error('Illegal use of invokespecial on nonsuperclass')
            if op == opnames.INVOKEINTERFACE:
                parsed_desc = _loadMethodDesc(self.cpool, ind)[0]
                if parsed_desc is None or len(parsed_desc)+1 != self.instruction[2]:
                    self.error('Argument count mismatch in invokeinterface')
            if op in (opnames.INVOKEINTERFACE, opnames.INVOKEDYNAMIC):
                if self.instruction[3] != 0:
                    self.error('Final bytes must be zero in {}', op)
            elif op in (opnames.INVOKEVIRTUAL, opnames.INVOKESPECIAL, opnames.INVOKEINIT):
                self._setProtected(False)

        elif op in (opnames.INSTANCEOF, opnames.CHECKCAST, opnames.NEW, opnames.ANEWARRAY, opnames.MULTINEWARRAY):
            ind = self.instruction[1]
            verifyCPType(ind, ['Class'])
            target = _indexToCFMInfo(self.cpool, ind, 'Class')
            if target == T_INVALID:
                self.error('Invalid class entry', op)

            self.push_type = target
            if op == opnames.ANEWARRAY:
                if target.dim >= 256:
                    self.error('Too many array dimensions')
                self.push_type = T_ARRAY(target)
            elif op == opnames.NEW:
                if target.tag != '.obj' or target.dim > 0:
                    self.error('New can only create nonarrays')
                self.push_type = T_UNINIT_OBJECT(self.key)
                self.target_type = target
            elif op == opnames.MULTINEWARRAY:
                count = self.instruction[2]
                if count > target.dim or count <= 0:
                    self.error('Illegal dimensions in multinewarray')

        elif op == opnames.NEWARRAY:
            target = parseFieldDescriptor('[' + self.instruction[1])[0]
            if target is None:
                self.error('Bad typecode for newarray')
            self.push_type = target

        elif op in (opnames.STORE, opnames.LOAD, opnames.IINC, opnames.RET):
            if op in (opnames.IINC, opnames.RET):
                ind = self.instruction[1]
            else:
                t, ind = self.instruction[1:]
                if t in 'JD':
                    ind += 1
            if ind >= self.code.locals:
                self.error('Local index {} exceeds max local count for method ({})', ind, self.code.locals)

    def _precomputeValues(self):
        #local_tag, local_ind, parsed_desc, successors
        off_i = self.offsetList.index(self.key)
        self.next_instruction = self.offsetList[off_i+1] #None if end of code

        #cache these, since they're not state dependent  and don't produce errors anyway
        self.before, self.after = getSpecificStackCode(self.code, self.instruction)
        op = self.op
        if op == opnames.LOAD:
            self.local_tag = {'I':'.int','F':'.float','J':'.long','D':'.double','A':'.obj'}[self.instruction[1]]
            self.local_ind = self.instruction[2]
        elif op == opnames.IINC:
            self.local_tag = '.int'
            self.local_ind = self.instruction[1]
        elif op == opnames.RET:
            self.local_tag = '.address'
            self.local_ind = self.instruction[1]
        elif op in (opnames.PUTFIELD, opnames.PUTSTATIC):
            self.parsed_desc = _loadFieldDesc(self.cpool, self.instruction[1])
            if self.parsed_desc is not None:
                prefix = 'A' if op == opnames.PUTFIELD else ''
                self.before = prefix + ''.join(map(vtype2Char, self.parsed_desc))
        elif op in (opnames.GETFIELD, opnames.GETSTATIC):
            self.parsed_desc = _loadFieldDesc(self.cpool, self.instruction[1])
            if self.parsed_desc is not None:
                self.after = ''.join(map(vtype2Char, self.parsed_desc))
        elif op in _invoke_ops:
            self.parsed_desc = _loadMethodDesc(self.cpool, self.instruction[1])
            if self.parsed_desc is not None:
                prefix = ''
                if op == opnames.INVOKEINIT:
                    prefix = '@'
                elif op in (opnames.INVOKEINTERFACE, opnames.INVOKEVIRTUAL, opnames.INVOKESPECIAL):
                    prefix = 'A'
                self.before = prefix + ''.join(map(vtype2Char, self.parsed_desc[0]))
                self.after = ''.join(map(vtype2Char, self.parsed_desc[1]))

        elif op == opnames.MULTINEWARRAY:
            self.before = 'I' * self.instruction[2]

        #Now get successors
        next_ = self.next_instruction

        if op in (opnames.IF_A, opnames.IF_I, opnames.IF_ICMP, opnames.IF_ACMP):
            self.successors = next_, self.instruction[2]
        elif op in (opnames.JSR, opnames.GOTO):
            self.successors = self.instruction[1],
        elif op in (opnames.RETURN, opnames.THROW):
            self.successors = ()
        elif op == opnames.RET:
            self.successors = None #calculate it when the node is reached
        elif op == opnames.SWITCH:
            opname, default, jumps, padding = self.instruction
            targets = (default,)
            if jumps:
                targets += zip(*jumps)[1]
            self.successors = targets
        else:
            self.successors = next_,

    def _setProtected(self, isfield):
        self.protected = False
        target, name, desc = self.cpool.getArgsCheck(('Field' if isfield else 'Method'), self.instruction[1])

        # Not sure what Hotspot actually does here, but this is hopefully close enough
        if '[' in target:
            return
        cname = target
        if cname in self.class_.getSuperclassHierarchy():
            while cname is not None:
                cls = self.env.getClass(cname)
                members = cls.fields if isfield else cls.methods
                for m in members:
                    if m.name == name and m.descriptor == desc:
                        if 'PROTECTED' in m.flags:
                            #Unfortunately, we have no way to tell if the classes are in the same runtime package
                            #We can be conservative and accept if they have the same static package though
                            pack1 = self.class_.name.rpartition('/')[0]
                            pack2 = cname.rpartition('/')[0]
                            self.protected = (pack1 != pack2)
                        return
                cname = cls.supername

    def _checkLocals(self):
        if self.op not in (opnames.LOAD, opnames.IINC, opnames.RET):
            return

        t,i = self.local_tag, self.local_ind
        cat2 = t in ('.long','.double')

        locs = self.locals
        if i >= len(locs) or cat2 and i >= len(locs)-1:
            self.error("Read from unintialized local {}", i)

        reg = locs[i]
        if not (reg.tag == t and reg.dim == 0):
            if t == '.obj':
                if objOrArray(reg) or reg == T_UNINIT_THIS:
                    return
                #Return address case will fallthrough and error anyway
                elif reg.tag == '.new' and reg.dim == 0:
                    return
            self.error("Invalid local at {}, expected {}", i, t)

        if cat2:
            reg = locs[i+1]
            if reg.tag != t+'2':
                self.error("Invalid local top at {}, expected {}", i+1, t)

    def _checkFlags(self):
        if self.op == opnames.RETURN:
            inc = InstructionNode
            #Hotspot only checks this for void return as it only occurs in ctors
            if (self.flags & inc.NEED_CONSTRUCTOR) and (self.flags & inc.NOT_CONSTRUCTED):
                self.error('Invalid flags at return')
            if (self.flags & (inc.NO_RETURN)):
                self.error('Invalid flags at return')

    def _popStack(self, iNodes):
        #part1, get the stack code
        #Normally, put*, multinewarray, and invoke* would be calculated at this point
        #but we precompute them
        op = self.op
        scode = self.before
        curclass_fi = T_OBJECT(self.class_.name)

        if op in _invoke_ops:
            if self.parsed_desc is None:
                self.error('Invalid method descriptor at index {}', self.instruction[1])
            elif len(self.before) >= 256:
                self.error('Method has too many arguments (max 255)')
        elif op in (opnames.PUTFIELD, opnames.PUTSTATIC):
            if self.parsed_desc is None: #Todo - make this more like what Hotspot does
                self.error('Invalid field descriptor at index {}', self.instruction[1])
        assert(scode is not None)

        #part2, check stack code
        stack = self.stack
        swap = {} #used for dup, pop, etc.
        si = len(stack)
        ci = len(scode)
        while ci > 0:
            if si <= 0:
                self.error('Cannot pop off empty stack')

            si -= 1
            ci -= 1
            top = stack[si]
            char = scode[ci]

            if char in 'IF':
                et = T_FLOAT if char == 'F' else T_INT
                if et != top:
                    self.error('Expecting {} on stack', et.tag)
            elif char in 'JD':
                et = T_DOUBLE if char == 'D' else T_LONG
                et2 = T_DOUBLE2 if char == 'D' else T_LONG2
                if stack[si-1:si+1] != (et,et2):
                    self.error('Expecting {} on stack', et.tag)
                si -= 1
            elif char == 'A':
                if not objOrArray(top):
                    #check for special exceptions
                    if top.tag == '.address' and op == opnames.STORE:
                        continue
                    #can it use uninitialized objects? Note that if_acmp is NOT included
                    uninitops = (opnames.STORE, opnames.LOAD, opnames.IF_A)
                    if top.tag in ('.new','.init') and op in uninitops:
                        continue
                    if top.tag == '.init' and op == opnames.PUTFIELD:
                        #If the index were invalid, we would have raised an error in part 1
                        ind = self.instruction[1]
                        target, name, desc = self.cpool.getArgsCheck('Field', ind)
                        for field in self.class_.fields:
                            if field.name == name and field.descriptor == desc:
                                stack = stack[:si] + (curclass_fi,) + stack[si+1:]
                                continue
            elif char == '@':
                if top.tag not in ('.new','.init'):
                    self.error('Expecting an uninitialized or new object')
            #'O' and 'a' cases omitted as unecessary
            elif char == ']':
                if top != T_NULL:
                    char2 = scode[ci-1]
                    tempMap = {'B':T_BYTE, 'C':T_CHAR, 'D':T_DOUBLE, 'F':T_FLOAT,
                                'I':T_INT, 'J':T_LONG, 'S':T_SHORT}
                    if char2 in tempMap:
                        if top != T_ARRAY(tempMap[char2]):
                            self.error('Expecting an array of {}s on stack', tempMap[char2].tag[1:])
                    elif char2 == 'A':
                        if top.dim <= 0 or (top.dim == 1 and top.tag != '.obj'):
                            self.error('Expecting an array of objects on stack')
                    elif char2 == '?':
                        if top.dim <= 0:
                            self.error('Expecting an array on stack')
                ci -= 2 #skip past [x part
            elif char in '1234':
                if top.tag in ('.double2','.long2'):
                    if ci and scode[ci-1] == '+':
                        swap[char] = top
                        swap[scode[ci-2]] = stack[si-1]
                        ci -= 2 #skip + and bottom half
                        si -= 1
                    else:
                        self.error('Attempting to split double or long on the stack')
                else:
                    swap[char] = top
                    if ci and scode[ci-1] == '+':
                        ci -= 1 #skip +

        #part3, check objects
        assert(si == 0 or stack[:si] == self.stack[:si]) #popped may differ due to putfield on uninit's editing of the stack
        stack, popped = stack[:si], stack[si:]

        if op == opnames.ARRSTORE_OBJ:
            arrt, objt = popped[0], popped[2]
            target = decrementDim(arrt)
            if not objOrArray(objt) or not objOrArray(target):
                self.error('Non array or object in aastore')
        elif op in (opnames.PUTFIELD, opnames.PUTSTATIC, opnames.GETFIELD):
            if op != opnames.PUTSTATIC: # *field
                #target: class field is defined in, and hence what the implicit object arg must be
                target = _indexToCFMInfo(self.cpool, self.instruction[1], 'Field')
                if not isAssignable(self.env, popped[0], target):
                    self.error('Accessing field on object of the incorrect type')
                elif self.protected and not isAssignable(self.env, popped[0], curclass_fi):
                    self.error('Illegal access to protected field')
            if op != opnames.GETFIELD: # put*
                if not isAssignable(self.env, popped[-1], self.parsed_desc[-1]): #Note, will only check second half for cat2
                    self.error('Storing invalid object type into field')
        elif op == opnames.THROW:
            if not isAssignable(self.env, popped[0], T_OBJECT('java/lang/Throwable')):
                self.error('Thrown object not subclass of Throwable')
        elif op == opnames.ARRLOAD_OBJ: #store array type for push_stack
            swap[op] = decrementDim(popped[0])
        elif op in _invoke_ops:
            offset = 1
            if op == opnames.INVOKEINIT:
                swap[False] = objt = popped[0]

                #Store this for use with blockmaker later on
                self.isThisCtor = (objt.tag == '.init')

                if objt.tag == '.new':
                    new_inode = iNodes[objt.extra]
                    swap[True] = target = new_inode.target_type
                    if target != self.target_type:
                        self.error('Call to constructor for wrong class')
                    if self.protected and self.class_.version >= (50,0):
                        if not isAssignable(self.env, objt, curclass_fi):
                            self.error('Illegal call to protected constructor')
                else: # .init
                    if self.target_type not in (curclass_fi, T_OBJECT(self.class_.supername)):
                        self.error('Must call current or immediate superclass constructor')
                    swap[True] = curclass_fi
            elif op in (opnames.INVOKEVIRTUAL, opnames.INVOKEINTERFACE, opnames.INVOKESPECIAL):
                objt = popped[0]
                if not isAssignable(self.env, objt, self.target_type):
                    self.error('Calling method on object of incorrect type')
                if op == opnames.INVOKESPECIAL and not isAssignable(self.env, objt, curclass_fi):
                    self.error('Calling private or super method on different class')
                # Note: this will never happen under our current implementation, but Hotspot
                # contains code for it. TODO: figure out what exactly it's doing
                # if self.protected and not isAssignable(self.env, objt, curclass_fi):
                #     #special exception for arrays pretending to implement clone()
            else:
                offset = 0 #no this for static or dynamic

            for act, expected in zip(popped[offset:], self.parsed_desc[0]):
                #Hotspot only checks for 'A' codes, but primatives should match anyway
                if not isAssignable(self.env, act, expected):
                    self.error('Incompatible argument to method call')
        elif op == opnames.RETURN:
            rvals = parseMethodDescriptor(self.code.method.descriptor)[1]
            if len(popped) != len(rvals):
                self.error('Incorrect return type')
            elif popped and not isAssignable(self.env, popped[0], rvals[0]):
                self.error('Incorrect return type')
        elif op == opnames.NEW:
            if self.push_type in stack:
                self.error('Stale uninitialized object at new instruction')
            swap[False] = self.push_type
            swap[True] = T_INVALID

        #Sanity check on swap keys
        assert(not swap or swap.keys() == [op] or set(swap.keys()) == set([False,True]) or set(swap.keys()) <= set('1234'))
        return stack, swap

    def _updateLocals(self, swap):
        op = self.op
        newlocs = list(self.locals) #mutable copies
        newmasks = list(self.masks)

        # Hotspot does things a bit strangely due to optimizations, which
        # we don't really care about. So we save all the new bits and
        # apply them at the end
        newbits = set()
        if op in (opnames.STORE, opnames.LOAD):
            cat = 2 if self.instruction[1] in 'JD' else 1
            ind = self.instruction[2]
            newbits.update(range(ind,ind+cat))

            if op == opnames.STORE:
                newlocs += [T_INVALID] * (ind+cat-len(newlocs))
                #Get the values off the old stack, since they've been popped
                newlocs[ind:ind+cat] = self.stack[-cat:]
        elif op in (opnames.IINC, opnames.RET):
            newbits.add(self.instruction[1])
        elif op == opnames.JSR:
            target = self.instruction[1]
            if newmasks and target in zip(*newmasks)[0]:
                self.error('Recursive call to JSR')
            newmasks.append((target, frozenset()))

        elif op in (opnames.INVOKEINIT, opnames.NEW):
            old, replace = swap[False], swap[True]

            for i, val in enumerate(newlocs[:]):
                if val == old:
                    newlocs[i] = replace
                    newbits.add(i)

        newmasks = [(addr,bits | newbits) for addr,bits in newmasks]
        locals_ = tuple(newlocs) if newbits else self.locals
        return locals_, tuple(newmasks)

    def _updateFlags(self, swap):
        flags = self.flags
        if self.op == opnames.INVOKEINIT and swap[False] == T_UNINIT_THIS:
            flags = flags & ~InstructionNode.NOT_CONSTRUCTED
        return flags

    def _pushStack(self, stack, swap):
        op = self.op
        curclass_fi = T_OBJECT(self.class_.name)

        scode = self.after
        new_fi = T_INVALID

        if op == opnames.LDC:
            #Hotspot appears to precompute this
            ind, cat = self.instruction[1:]
            cp_typen = self.cpool.getType(ind)
            scode = {'Int':'I','Long':'J','Double':'D','Float':'F'}.get(cp_typen, 'A')
            if scode == 'A':
                if cp_typen == 'String':
                    new_fi = T_OBJECT('java/lang/String')
                elif cp_typen == 'Class':
                    assert(self.class_.version >= (49,0)) #presuambly, this stuff should be verified during parsing
                    new_fi = T_OBJECT('java/lang/Class')
                elif cp_typen == 'MethodType':
                    assert(self.class_.version >= (51,0))
                    new_fi = T_OBJECT('java/lang/invoke/MethodType')
                elif cp_typen == 'MethodHandle':
                    assert(self.class_.version >= (51,0))
                    new_fi = T_OBJECT('java/lang/invoke/MethodHandle')
                else:
                    assert(0)
        elif op in (opnames.GETFIELD, opnames.GETSTATIC):
            if self.parsed_desc is None: #Todo - make this more like what Hotspot does
                self.error('Invalid field descriptor at index {}', self.instruction[1])
            new_fi = self.parsed_desc[0] if scode else T_INVALID
        elif op in _invoke_ops:
            if self.parsed_desc is None:
                self.error('Invalid method descriptor at index {}', self.instruction[1])
            new_fi = self.parsed_desc[-1][0] if scode else T_INVALID
        elif op == opnames.CONSTNULL:
            new_fi = T_NULL
        #Hotspot precomputes this
        elif op in (opnames.NEW, opnames.CHECKCAST, opnames.ANEWARRAY, opnames.MULTINEWARRAY, opnames.NEWARRAY):
            new_fi = self.push_type
        elif op == opnames.ARRLOAD_OBJ:
            new_fi = swap[op]
        elif op == opnames.LOAD and self.instruction[1] == 'A':
            new_fi = self.locals[self.instruction[2]]

        for char in scode:
            if char in 'IF':
                et = T_FLOAT if char == 'F' else T_INT
                stack += et,
            elif char in 'JD':
                et = T_DOUBLE if char == 'D' else T_LONG
                et2 = T_DOUBLE2 if char == 'D' else T_LONG2
                stack += et, et2
            elif char == 'R': #JSR
                et = T_ADDRESS(self.instruction[1])
                stack += et,
            elif char in '1234':
                stack += swap[char],
            elif char == 'A':
                stack += new_fi,
            else:
                assert(0)

        if op == opnames.INVOKEINIT:
            old, replace = swap[False], swap[True]
            stack = tuple((replace if x == old else x) for x in stack)

        return stack

    def _getNewState(self, iNodes):
        self._checkLocals()
        self._checkFlags()
        stack, swap = self._popStack(iNodes)
        locals_, masks = self._updateLocals(swap)
        flags = self._updateFlags(swap)
        stack = self._pushStack(stack, swap)

        assert(all(isinstance(vt, fullinfo_t) for vt in stack))
        assert(all(isinstance(vt, fullinfo_t) for vt in locals_))
        return (stack, locals_, masks, flags), swap

    def _mergeSingleSuccessor(self, other, newstate, iNodes, isException):
        newstack, newlocals, newmasks, newflags = newstate
        if self.op in (opnames.RET, opnames.JSR):
            # Note: In most cases, this will cause an error later
            # as INVALID is not allowed on the stack after merging
            # but if the stack is never merged afterwards, it's ok
            newstack = tuple((T_INVALID if x.tag == '.new' else x) for x in newstack)
            newlocals = tuple((T_INVALID if x.tag == '.new' else x) for x in newlocals)

        if self.op == opnames.RET and not isException:
            #Get the instruction before other
            off_i = self.offsetList.index(other.key)
            jsrnode = iNodes[self.offsetList[off_i-1]]

            if jsrnode.returnedFrom is not None and jsrnode.returnedFrom != self.key:
                jsrnode.error('Multiple returns to jsr')
            jsrnode.returnedFrom = self.key

            if jsrnode.visited: #if not, skip for later
                called = jsrnode.instruction[1]
                newmasks = list(newmasks)
                while newmasks and newmasks[-1][0] != called:
                    newmasks.pop()
                if not newmasks:
                    self.error('Returning to jsr not in current call stack')
                mask = newmasks.pop()[1]

                #merge locals using mask
                zipped = itertools.izip_longest(newlocals, jsrnode.locals, fillvalue=T_INVALID)
                newlocals = tuple((x if i in mask else y) for i,(x,y) in enumerate(zipped))
                newmasks = tuple(newmasks)
            else:
                return

        if not other.visited:
            other.stack, other.locals, other.masks, other.flags = newstack, newlocals, newmasks, newflags
            other.visited = other.changed = True
        else:
            #Merge stack
            oldstack = other.stack
            if len(oldstack) != len(newstack):
                other.error('Inconsistent stack height {} != {}', len(oldstack), len(newstack))
            if any(not isAssignable(self.env, new, old) for new,old in zip(newstack, oldstack)):
                other.changed = True
                other.stack = tuple(mergeTypes(self.env, new, old) for new,old in zip(newstack, oldstack))
                if T_INVALID in other.stack:
                    other.error('Incompatible types in merged stack')

            #Merge locals
            if len(newlocals) < len(other.locals):
                other.locals = other.locals[:len(newlocals)]
                other.changed = True

            zipped = list(itertools.izip_longest(newlocals, other.locals, fillvalue=T_INVALID))
            okcount = 0
            for x,y in zipped:
                if isAssignable(self.env, x, y):
                    okcount += 1
                else:
                    break

            if okcount < len(other.locals):
                merged = list(other.locals[:okcount])
                merged += [mergeTypes(self.env, new, old) for new,old in zipped[okcount:]]
                while merged and merged[-1] == T_INVALID:
                    merged.pop()
                other.locals = tuple(merged)
                other.changed = True

            #Merge Masks
            last_match = -1
            mergedmasks = []
            for entry1, mask1 in other.masks:
                for j,(entry2,mask2) in enumerate(newmasks):
                    if j>last_match and entry1 == entry2:
                        item = entry1, (mask1 | mask2)
                        mergedmasks.append(item)
                        last_match = j
            newmasks = tuple(mergedmasks)
            if other.masks != newmasks:
                other.masks = newmasks
                other.changed = True

            #Merge flags
            if other.flags != newflags:
                other.flags = newflags
                other.changed = True

    ###################################################################
    def error(self, msg, *args):
        msg = msg.format(*args, self=self)
        msg = msg + '\n\n' + str(self)
        raise error_types.VerificationError(msg)

    def update(self, iNodes, exceptions):
        assert(self.visited)
        self.changed = False

        newstate, swap = self._getNewState(iNodes)
        newstack, newlocals, newmasks, newflags = newstate

        successors = self.successors
        if self.op == opnames.JSR:
            if self.returnedFrom is not None:
                iNodes[self.returnedFrom].changed = True
        if successors is None:
            assert(self.op == opnames.RET)
            called = self.locals[self.instruction[1]].extra
            temp = [n.next_instruction for n in iNodes.values() if (n.op == opnames.JSR and n.instruction[1] == called)]
            successors = self.successors = tuple(temp)
            self.jsrTarget = called #store for later use in ssa creation

        #Merge into exception handlers first
        for (start,end),(handler,execStack) in exceptions:
            if start <= self.key < end:
                if self.op != opnames.INVOKEINIT:
                    self._mergeSingleSuccessor(handler, (execStack, newlocals, newmasks, newflags), iNodes, True)
                else: #two cases since the ctor may suceed or fail before throwing
                    #If ctor is being invoked on this, update flags appropriately
                    tempflags = newflags
                    if swap[False] == T_UNINIT_THIS:
                        tempflags |= InstructionNode.NO_RETURN

                    self._mergeSingleSuccessor(handler, (execStack, self.locals, self.masks, self.flags), iNodes, True)
                    self._mergeSingleSuccessor(handler, (execStack, newlocals, newmasks, tempflags), iNodes, True)

        #Now regular successors
        for k in self.successors:
            self._mergeSingleSuccessor(iNodes[k], (newstack, newlocals, newmasks, newflags), iNodes, False)

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
        args[0] = T_UNINIT_THIS
        startFlags |= InstructionNode.NEED_CONSTRUCTOR
        startFlags |= InstructionNode.NOT_CONSTRUCTED
    assert(len(args) <= 255)
    args = tuple(args)

    maxstack, maxlocals = code.stack, code.locals
    assert(len(args) <= maxlocals)

    offsets = tuple(sorted(code.bytecode.keys())) + (None,) #sentinel at end as invalid index
    iNodes = [InstructionNode(code, offsets, key) for key in offsets[:-1]]
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
        t = T_OBJECT(typen)
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