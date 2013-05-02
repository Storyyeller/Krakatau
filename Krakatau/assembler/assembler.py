import collections
import struct, operator

from . import instructions, codes
from .. import constant_pool
from ..classfile import ClassFile
from ..method import Method
from ..field import Field

class AssemblerError(Exception):
    def __init__(self, message, data=None):
        super(AssemblerError, self).__init__(message)
        self.data = data

def error(msg):
    raise AssemblerError(msg)

class PoolRef(object):
    def __init__(self, *args, **kwargs):
        self.index = kwargs.get('index')
        self.lbl = kwargs.get('lbl')
        self.args = args

    def toIndex(self, pool, forbidden=(), **kwargs):
        if self.index is not None:
            return self.index
        if self.lbl:
            self.index = pool.getLabel(self.lbl, forbidden, **kwargs)
        else:
            self.args = [(x.toIndex(pool) if isinstance(x, PoolRef) else x) for x in self.args]
            self.index = pool.getItem(*self.args, **kwargs)
        return self.index

class PoolInfo(object):
    def __init__(self):
        self.pool = constant_pool.ConstPool()
        self.lbls = {}
        self.fixed = {} # constant pool entries in a specific slot
        self.bootstrap = [] #entries for the BootstrapMethods attribute if any

    def getLabel(self, lbl, forbidden=(), **kwargs):
        if lbl in forbidden:
            error('Circular constant pool reference: ' + ', '.join(forbidden))
        forbidden = forbidden + (lbl,)
        return self.lbls[lbl].toIndex(self, forbidden, **kwargs)

    def getItem(self, type_, *args, **kwargs):
        if type_ == 'InvokeDynamic':
            self.bootstrap.append(args[:-1])
            args = len(self.bootstrap)-1, args[-1]    
        return self.pool.addItem((type_, tuple(args)), **kwargs)

    def Utf8(self, s):
        return self.getItem('Utf8', s)

    def assignFixedSlots(self):
        self.pool.reserved.update(self.fixed)
        for i,v in self.fixed.items():
            if v.args and v.args[0] in ('Double','Long'):
                self.pool.reserved.add(i+1)
                
        #TODO - order these in terms of dependencies?
        for index, value in self.fixed.items():
            used = value.toIndex(self, index=index)
            if used != index: #we need to copy an existing item
                self.pool.copyItem(used, index)

_format_ops = collections.defaultdict(tuple)
_format_ops[''] = instructions.instrs_noarg
_format_ops['>B'] = 'iload', 'lload', 'fload', 'dload', 'aload', 'istore', 'lstore', 'fstore', 'dstore', 'astore', 'ret'
_format_ops['>h'] = 'ifeq', 'ifne', 'iflt', 'ifge', 'ifgt', 'ifle', 'if_icmpeq', 'if_icmpne', 'if_icmplt', 'if_icmpge', 'if_icmpgt', 'if_icmple', 'if_acmpeq', 'if_acmpne', 'goto', 'jsr', 'ifnull', 'ifnonnull'
_format_ops['>H'] = 'ldc_w', 'ldc2_w', 'getstatic', 'putstatic', 'getfield', 'putfield', 'invokevirtual', 'invokespecial', 'invokestatic', 'new', 'anewarray', 'checkcast', 'instanceof'

_format_ops['>b'] += 'bipush', 
_format_ops['>Bb'] += 'iinc', 
_format_ops['>h'] += 'sipush', 
_format_ops['>HB'] += 'multianewarray',
_format_ops['>HBB'] += 'invokeinterface',
_format_ops['>HH'] += 'invokedynamic',
_format_ops['>B'] += 'ldc', 'newarray'
_format_ops['>i'] += 'goto_w', 'jsr_w'

op_structs = {}
for fmt, ops in _format_ops.items():
    _s = struct.Struct(fmt)
    for _op in ops:
        op_structs[_op] = _s

def getPadding(pos):
    return (3-pos) % 4

def getInstrLen(instr, pos):
    op = instr[0]
    if op in op_structs:
        return 1 + op_structs[op].size
    elif op == 'wide':
        return 2 + 2 * len(instr[1][1])
    else:
        padding = getPadding(pos)
        count = len(instr[1][1])
        if op == 'tableswitch':
            return 13 + padding + 4*count
        else:
            return 9 + padding + 8*count 

def assembleInstruction(instr, labels, pos, pool):
    def lbl2Off(lbl):
        if lbl not in labels:
            del labels[None]
            error('Undefined label: {}\nDefined labels for current method are: {}'.format(lbl, ', '.join(sorted(labels))))
        return labels[lbl] - pos

    op = instr[0]
    first = chr(instructions.allinstructions.index(op))

    instr = [(x.toIndex(pool) if isinstance(x, PoolRef) else x) for x in instr[1:]]
    if op in instructions.instrs_lbl:
        instr[0] = lbl2Off(instr[0])
    if op in op_structs:
        rest = op_structs[op].pack(*instr)
        return first+rest
    elif op == 'wide':
        subop, args = instr[0]
        prefix = chr(instructions.allinstructions.index(subop))
        fmt = '>Hh' if len(args) > 1 else '>H'
        rest = struct.pack(fmt, *args)
        return first + prefix + rest
    else:
        padding = getPadding(pos)
        param, jumps, default = instr[0]
        default = lbl2Off(default)

        if op == 'tableswitch':
            jumps = map(lbl2Off, jumps)
            low, high = param, param + len(jumps)-1
            temp = struct.Struct('>i')
            part1 = first + '\0'*padding + struct.pack('>iii', default, low, high)
            return part1 + ''.join(map(temp.pack, jumps))
        elif op == 'lookupswitch':
            jumps = {k:lbl2Off(lbl) for k,lbl in jumps}
            jumps = sorted(jumps.items())
            temp = struct.Struct('>ii')
            part1 = first + '\0'*padding + struct.pack('>ii', default, len(jumps))
            part2 = ''.join(map(temp.pack, *zip(*jumps))) if jumps else ''
            return part1 + part2

def groupList(pairs):
    d = collections.defaultdict(list)
    for k,v in pairs:
        d[k].append(v)
    return d

def splitList(pairs):
    d = groupList(pairs)
    return d[False], d[True]
       
def assembleCodeAttr(statements, pool, version, addLineNumbers, jasmode):
    directives, lines = splitList(statements)
    dir_offsets = collections.defaultdict(list)

    offsets = []
    labels = {}
    pos = 0
    #first run through to calculate bytecode offsets
    #this is greatly complicated due to the need to
    #handle Jasmine line number directives
    for t, statement in statements:
        if t:
            lbl, instr = statement
            labels[lbl] = pos
            if instr is not None:
                offsets.append(pos)
                pos += getInstrLen(instr, pos)
        #some directives require us to keep track of the corresponding bytecode offset
        elif statement[0] in ('.line','.stackmap'):
            dir_offsets[statement[0]].append(pos)
    code_len = pos

    code_bytes = ''
    for lbl, instr in lines:
        if instr is not None:
            code_bytes += assembleInstruction(instr, labels, len(code_bytes), pool)
    assert(len(code_bytes) == code_len)

    directive_dict = groupList(directives)
    limits = groupList(directive_dict['.limit'])

    stack = min(limits['stack'] + [65535]) 
    locals_ = min(limits['locals'] + [65535]) 

    excepts = []
    for name, start, end, target in directive_dict['.catch']:
        #Hack for compatibility with Jasmin
        if jasmode and name.args and (name.args[1].args == ('Utf8','all')):
            name.index = 0
        vals = labels[start], labels[end], labels[target], name.toIndex(pool)
        excepts.append(struct.pack('>HHHH',*vals))
    
    attributes = []

    #StackMapTable
    def pack_vt(vt):
        s = chr(codes.vt_codes[vt[0]])
        if vt[0] == 'Object':
            s += struct.pack('>H', vt[1].toIndex(pool))        
        elif vt[0] == 'Uninitialized':
            s += struct.pack('>H', labels[vt[1]])
        return s

    if directive_dict['.stackmap']:
        frames = []
        last_pos = -1

        for pos, info in zip(dir_offsets['.stackmap'], directive_dict['.stackmap']):
            offset = pos - last_pos - 1
            last_pos = pos
            assert(offset >= 0)

            tag = info[0]
            if tag == 'same':
                if offset >= 64:
                    error('Max offset on a same frame is 63.')
                frames.append(chr(offset))            
            elif tag == 'same_locals_1_stack_item':
                if offset >= 64:
                    error('Max offset on a same_locals_1_stack_item frame is 63.')
                frames.append(chr(64 + offset) + pack_vt(info[2][0]))            
            elif tag == 'same_locals_1_stack_item_extended':
                frames.append(struct.pack('>BH', 247, offset) + pack_vt(info[2][0]))            
            elif tag == 'chop':
                if not (1 <= info[1] <= 3):
                    error('Chop frame can only remove 1-3 locals')
                frames.append(struct.pack('>BH', 251-info[1], offset))
            elif tag == 'same_extended':
                frames.append(struct.pack('>BH', 251, offset))
            elif tag == 'append':
                local_vts = map(pack_vt, info[2])
                if not (1 <= len(local_vts) <= 3):
                    error('Append frame can only add 1-3 locals')
                frames.append(struct.pack('>BH', 251+len(local_vts), offset) + ''.join(local_vts))
            elif tag == 'full':
                local_vts = map(pack_vt, info[2])
                stack_vts = map(pack_vt, info[3])
                frame = struct.pack('>BH', 255, offset)
                frame += struct.pack('>H', len(local_vts)) + ''.join(local_vts)
                frame += struct.pack('>H', len(stack_vts)) + ''.join(stack_vts)
                frames.append(frame)

        sm_body = ''.join(frames)
        sm_attr = struct.pack('>HIH', pool.Utf8("StackMapTable"), len(sm_body)+2, len(frames)) + sm_body
        attributes.append(sm_attr)

    #line number attribute
    if addLineNumbers and not directive_dict['line']:
        dir_offsets['line'] = directive_dict['line'] = offsets
    if directive_dict['line']:
        lntable = [struct.pack('>HH',x,y) for x,y in zip(dir_offsets['line'], directive_dict['line'])]
        ln_attr = struct.pack('>HIH', pool.Utf8("LineNumberTable"), 2+4*len(lntable), len(lntable)) + ''.join(lntable)        
        attributes.append(ln_attr)

    if directive_dict['.var']:
        sfunc = struct.Struct('>HHHHH').pack
        vartable = []
        for index, name, desc, start, end in directive_dict['.var']:
            start, end = labels[start], labels[end]
            name, desc = name.toIndex(pool), desc.toIndex(pool)
            vartable.append(sfunc(start, end-start, name, desc, index))
        var_attr = struct.pack('>HIH', pool.Utf8("LocalVariableTable"), 2+10*len(vartable), len(vartable)) + ''.join(vartable)        
        attributes.append(var_attr)

    if not code_len:
        return None

    for attrname, data in directive_dict['.codeattribute']:
        attr = struct.pack('>HI', attrname.toIndex(pool), len(data)) + data
        attributes.append(attr)        


    #Old versions use shorter fields for stack, locals, and code length
    header_fmt = '>HHI' if version > (45,2) else '>BBH'

    name_ind = pool.Utf8("Code")
    attr_len = struct.calcsize(header_fmt) + 4 + len(code_bytes) + 8*len(excepts) + sum(map(len, attributes))
    
    assembled_bytes = struct.pack('>HI', name_ind, attr_len)
    assembled_bytes += struct.pack(header_fmt, stack, locals_, len(code_bytes))
    assembled_bytes += code_bytes
    assembled_bytes += struct.pack('>H', len(excepts)) + ''.join(excepts)
    assembled_bytes += struct.pack('>H', len(attributes)) + ''.join(attributes)
    return assembled_bytes

def _assembleEVorAnnotationSub(pool, init_args, isAnnot):
    #call types
    C_ANNOT, C_ANNOT2, C_EV = range(3)
    init_callt = C_ANNOT if isAnnot else C_EV

    stack = [(init_callt, init_args)]
    parts = []
    add = parts.append

    while stack:
        callt, args = stack.pop()

        if callt == C_ANNOT:
            typeref, keylines = args
            add(struct.pack('>HH', typeref.toIndex(pool), len(keylines)))
            for pair in reversed(keylines):
                stack.append((C_ANNOT2, pair))

        elif callt == C_ANNOT2:
            name, val = args
            add(struct.pack('>H', name.toIndex(pool)))
            stack.append((C_EV, val))

        elif callt == C_EV:
            tag, data = args
            assert(tag in codes.et_rtags)
            add(tag)

            if tag in 'BCDFIJSZsc':
                add(struct.pack('>H', data[0].toIndex(pool)))
            elif tag == 'e':
                add(struct.pack('>HH', data[0].toIndex(pool), data[1].toIndex(pool)))
            elif tag == '@':
                stack.append((C_ANNOT, data[0]))
            elif tag == '[':
                add(struct.pack('>H', len(data[1])))
                for arrval in reversed(data[1]):
                    stack.append((C_EV, arrval))
    return ''.join(parts)

def assembleElementValue(val, pool):
    return  _assembleEVorAnnotationSub(pool, val, False)

def assembleAnnotation(annotation, pool):
    return  _assembleEVorAnnotationSub(pool, annotation, True)

def assembleMethod(header, statements, pool, version, addLineNumbers, jasmode):
    mflags, (name, desc) = header
    name = name.toIndex(pool)
    desc = desc.toIndex(pool)

    flagbits = map(Method.flagVals.get, mflags)
    flagbits = reduce(operator.__or__, flagbits, 0)

    meth_statements, code_statements = splitList(statements)

    method_attributes = []
    code_attr = assembleCodeAttr(code_statements, pool, version, addLineNumbers, jasmode)
    if code_attr is not None:
        method_attributes.append(code_attr)

    directive_dict = groupList(meth_statements)
    if directive_dict['.throws']:
        t_inds = [struct.pack('>H', x.toIndex(pool)) for x in directive_dict['.throws']]
        throw_attr = struct.pack('>HIH', pool.Utf8("Exceptions"), 2+2*len(t_inds), len(t_inds)) + ''.join(t_inds)        
        method_attributes.append(throw_attr)

    #Runtime annotations
    for vis in ('Invisible','Visible'):
        paramd = groupList(directive_dict['.runtime'+vis.lower()])

        if None in paramd:
            del paramd[None]

        if paramd:
            parts = []
            for i in range(max(paramd)):
                annotations = [assembleAnnotation(a, pool) for a in paramd[i]]
                part = struct.pack('>H', len(annotations)) + ''.join(annotations)
                parts.append(part)
            attrlen = 1+sum(map(len, parts))
            attr = struct.pack('>HIB', pool.Utf8("Runtime{}ParameterAnnotations".format(vis)), attrlen, len(parts)) + ''.join(parts)
            method_attributes.append(attr)

    if '.annotationdefault' in directive_dict:
        val = directive_dict['.annotationdefault'][0]
        data = assembleElementValue(val, pool)
        attr = struct.pack('>HI', pool.Utf8("AnnotationDefault"), len(data)) + data        
        method_attributes.append(attr)

    assembleClassFieldMethodAttributes(method_attributes.append, directive_dict, pool)
    return struct.pack('>HHHH', flagbits, name, desc, len(method_attributes)) + ''.join(method_attributes)

def getLdcRefs(statements):
    lines = [x[1][1] for x in statements if x[0] and x[1][0]]
    instructions = [x[1] for x in lines if x[1] is not None]

    for instr in instructions:
        op = instr[0]
        if op == 'ldc':
            yield instr[1]
 
def addLdcRefs(methods, pool):
    def getRealRef(ref, forbidden=()):
        '''Get the root PoolRef associated with a given PoolRef, following labels'''
        if ref.index is None and ref.lbl:
            if ref.lbl in forbidden:
                error('Circular constant pool reference: ' + ', '.join(forbidden))
            forbidden = forbidden + (ref.lbl,)
            return getRealRef(pool.lbls[ref.lbl], forbidden) #recursive call
        return ref

    #We attempt to estimate how many slots are needed after merging identical entries
    #So we can reserve the correct number of slots without leaving unused gaps
    #However, in complex cases, such as string/class/mt referring to an explicit
    #reference, we may overestimate
    ldc_refs = collections.defaultdict(set)

    for header, statements in methods:
        for ref in getLdcRefs(statements):
            ref = getRealRef(ref)
            if ref.index is not None:
                continue

            type_ = ref.args[0]
            if type_ in ('Int','Float'):
                key = ref.args[1]
            elif type_ in ('String','Class','MethodType'): 
                uref = getRealRef(ref.args[1])
                key = uref.index, uref.args[1:]
            else: #for MethodHandles, don't even bother trying to estimate merging
                key = ref.args[1:] 
            ldc_refs[type_].add(key)    

    #TODO - make this a little cleaner so we don't have to mess with the ConstantPool internals
    num = sum(map(len, ldc_refs.values()))
    slots = [pool.pool.getAvailableIndex() for _ in range(num)]
    pool.pool.reserved.update(slots)

    for type_ in ('Int','Float'):
        for arg in ldc_refs[type_]:
            pool.getItem(type_, arg, index=slots.pop())
    for type_ in ('String','Class','MethodType'):
        for ind,args in ldc_refs[type_]:
            arg = ind if ind is not None else pool.Utf8(*args)
            pool.getItem(type_, arg, index=slots.pop())
    for type_ in ('MethodHandle',):
        for code, ref in ldc_refs[type_]:
            pool.getItem(type_, code, ref.toIndex(pool), index=slots.pop())
    assert(not slots)
    assert(not pool.pool.reserved)

def assembleClassFieldMethodAttributes(addcb, directive_dict, pool):
    for vis in ('Invisible','Visible'):
        paramd = groupList(directive_dict['.runtime'+vis.lower()])
        if None in paramd:
            annotations = [assembleAnnotation(a, pool) for a in paramd[None]]
            attrlen = 2+sum(map(len, annotations))
            attr = struct.pack('>HIH', pool.Utf8("Runtime{}Annotations".format(vis)), attrlen, len(annotations)) + ''.join(annotations)
            addcb(attr)

    for name in directive_dict['.signature']:
        attr = struct.pack('>HIH', pool.Utf8("Signature"), 2, name.toIndex(pool))
        addcb(attr)

    #.innerlength directive overrides the normal attribute length calculation
    hasoverride = len(directive_dict['.innerlength']) > 0

    for name, data in directive_dict['.attribute']:    
        name_ind = name.toIndex(pool)

        if hasoverride and pool.pool.getArgsCheck('Utf8', name_ind) == 'InnerClasses':
            attrlen = directive_dict['.innerlength'][0]
        else:
            attrlen = len(data)

        attr = struct.pack('>HI', name_ind, attrlen) + data
        addcb(attr)

def assembleClassAttributes(addcb, directive_dict, pool, addLineNumbers, jasmode, filename):

    sourcefile = directive_dict.get('.source',[None])[0] #PoolRef or None
    if jasmode and not sourcefile:
        sourcefile = pool.Utf8(filename)
    elif addLineNumbers and not sourcefile:
        sourcefile = pool.Utf8("SourceFile")
    if sourcefile:
        attr = struct.pack('>HIH', pool.Utf8("SourceFile"), 2, sourcefile.toIndex(pool))
        addcb(attr)

    if '.inner' in directive_dict:
        parts = []
        for inner, outer, name, flags in directive_dict['.inner']:
            flagbits = map(ClassFile.flagVals.get, flags)
            flagbits = reduce(operator.__or__, flagbits, 0)
            part = struct.pack('>HHHH', inner.toIndex(pool), outer.toIndex(pool), name.toIndex(pool), flagbits)
            parts.append(part)

        #.innerlength directive overrides the normal attribute length calculation
        innerlen = 2+8*len(parts) if '.innerlength' not in directive_dict else directive_dict['.innerlength'][0]
        attr = struct.pack('>HIH', pool.Utf8("InnerClasses"), innerlen, len(parts)) + ''.join(parts)
        addcb(attr)

    if '.enclosing' in directive_dict:
        class_, nat = directive_dict['.enclosing'][0]
        attr = struct.pack('>HIHH', pool.Utf8("EnclosingMethod"), 4, class_.toIndex(pool), nat.toIndex(pool))
        addcb(attr)

    assembleClassFieldMethodAttributes(addcb, directive_dict, pool)


def assemble(tree, addLineNumbers, jasmode, filename):
    pool = PoolInfo()
    version, cattrs1, classdec, superdec, interface_decs, cattrs2, topitems = tree
    if not version: #default to version 49.0 except in Jasmin compatibility mode
        version = (45,3) if jasmode else (49,0)

    #scan topitems, plus statements in each method to get cpool directives
    interfaces = []
    fields = []
    methods = []
    attributes = []

    directive_dict = groupList(cattrs1 + cattrs2)
    top_d = groupList(topitems)

    for slot, value in top_d['const']:
        if slot.index is not None:
            pool.fixed[slot.index] = value
        else:
            pool.lbls[slot.lbl] = value
    pool.assignFixedSlots()

    #Now find all cp references used in an ldc instruction
    #Since they must be <=255, we give them priority in assigning slots
    #to maximize the chance of a successful assembly
    addLdcRefs(top_d['method'], pool)

    for flags, name, desc, const, field_directives in top_d['field']:
        flagbits = map(Field.flagVals.get, flags)
        flagbits = reduce(operator.__or__, flagbits, 0)
        name = name.toIndex(pool)
        desc = desc.toIndex(pool)

        fattrs = []
        if const is not None:
            attr = struct.pack('>HIH', pool.Utf8("ConstantValue"), 2, const.toIndex(pool))
            fattrs.append(attr)

        assembleClassFieldMethodAttributes(fattrs.append, groupList(field_directives), pool)

        field_code = struct.pack('>HHHH', flagbits, name, desc, len(fattrs)) + ''.join(fattrs)
        fields.append(field_code)

    for header, statements in top_d['method']:
        methods.append(assembleMethod(header, statements, pool, version, addLineNumbers, jasmode))

    if pool.bootstrap:
        entries = [struct.pack('>H' + 'H'*len(bsargs), bsargs[0], len(bsargs)-1, *bsargs[1:]) for bsargs in pool.bootstrap]   
        attrbody = ''.join(entries)
        attrhead = struct.pack('>HIH', pool.Utf8("BootstrapMethods"), 2+len(attrbody), len(entries))
        attributes.append(attrhead + attrbody)

    #Explicit class attributes
    assembleClassAttributes(attributes.append, directive_dict, pool, addLineNumbers, jasmode, filename)

    interfaces = [struct.pack('>H', x.toIndex(pool)) for x in interface_decs]
    intf, cflags, this = classdec
    cflags = set(cflags)
    if intf:
        cflags.add('INTERFACE')
    if jasmode:
        cflags.add('SUPER')

    flagbits = map(ClassFile.flagVals.get, cflags)
    flagbits = reduce(operator.__or__, flagbits, 0)
    this = this.toIndex(pool)
    super_ = superdec.toIndex(pool)

    major, minor = version
    class_code = '\xCA\xFE\xBA\xBE' + struct.pack('>HH', minor, major)
    class_code += pool.pool.bytes()
    class_code += struct.pack('>HHH', flagbits, this, super_)
    for stuff in (interfaces, fields, methods, attributes):
        bytes_ = struct.pack('>H', len(stuff)) + ''.join(stuff)
        class_code += bytes_

    name = pool.pool.getArgs(this)[0]
    return name, class_code