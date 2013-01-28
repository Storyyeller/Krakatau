import collections, itertools
import struct, operator

from . import instructions
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
            error('Recursive constant pool reference: ' + ', '.join(forbidden))
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

_op_structs = {}
for fmt, ops in _format_ops.items():
    s = struct.Struct(fmt)
    for op in ops:
        _op_structs[op] = s

def getPadding(pos):
    return (3-pos) % 4

def getInstrLen(instr, pos):
    op = instr[0]
    if op in _op_structs:
        return 1 + _op_structs[op].size
    elif op == 'wide':
        return 2 * len(instr[1])
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
    if op in _op_structs:
        rest = _op_structs[op].pack(*instr)
        return first+rest
    elif op == 'wide':
        subop, args = instr[0]
        prefix = chr(instructions.allinstructions.index(subop))
        rest = struct.pack('>'+'H'*len(args), args)
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
        
def assembleCodeAttr(statements, pool, version, addLineNumbers, jasmode):
    directives = [x[1] for x in statements if x[0] == 'dir']
    lines = [x[1] for x in statements if x[0] == 'ins']

    offsets = []
    linestarts = []
    labels = {}
    pos = 0
    #first run through to calculate bytecode offsets
    #this is greatly complicated due to the need to
    #handle Jasmine line number directives
    for t, statement in statements:
        if t=='ins':
            lbl, instr = statement
            labels[lbl] = pos
            if instr is not None:
                offsets.append(pos)
                pos += getInstrLen(instr, pos)
        elif t == 'dir' and statement[0] == 'line':
            lnum = statement[1]
            linestarts.append((lnum,pos))
    code_len = pos

    code_bytes = ''
    for lbl, instr in lines:
        if instr is not None:
            code_bytes += assembleInstruction(instr, labels, len(code_bytes), pool)
    assert(len(code_bytes) == code_len)

    directive_dict = collections.defaultdict(list)
    for t, val in directives:
        directive_dict[t].append(val)

    stack = min(directive_dict['stack'] + [65535]) 
    locals_ = min(directive_dict['locals'] + [65535]) 

    excepts = []
    for name, start, end, target in directive_dict['catch']:
        #Hack for compatibility with Jasmin
        if jasmode and name.args and (name.args[1].args == ('Utf8','all')):
            name.index = 0
        vals = labels[start], labels[end], labels[target], name.toIndex(pool)
        excepts.append(struct.pack('>HHHH',*vals))
    
    attributes = []

    #line number attribute
    if addLineNumbers and not linestarts:
        linestarts = [(x,x) for x in offsets]
    if linestarts:
        lntable = [struct.pack('>HH',x,y) for x,y in linestarts]
        ln_attr = struct.pack('>HIH', pool.Utf8("LineNumberTable"), 2+4*len(lntable), len(lntable)) + ''.join(lntable)        
        attributes.append(ln_attr)

    if directive_dict['var']:
        sfunc = Struct('>HHHHH').pack
        vartable = []
        for index, name, desc, start, end in directive_dict['var']:
            start, end = labels[start], labels[end]
            name, desc = name.toIndex(pool), desc.toIndex(pool)
            vartable.append(sfunc(start, end-start, name, desc, index))
        var_attr = struct.pack('>HIH', pool.Utf8("LocalVariableTable"), 2+10*len(vartable), len(vartable)) + ''.join(vartable)        
        attributes.append(var_attr)

    method_attributes = []
    if directive_dict['throws']:
        t_inds = [struct.pack('>H', x.toIndex(pool)) for x in directive_dict['throws']]
        throw_attr = struct.pack('>HIH', pool.Utf8("Exceptions"), 2+2*len(t_inds), len(t_inds)) + ''.join(t_inds)        
        method_attributes = [throw_attr]

    if not code_len:
        return None, method_attributes

    #Old versions use shorter fields for stack, locals, and code length
    header_fmt = '>HHI' if version > (45,2) else '>BBH'

    name_ind = pool.Utf8("Code")
    attr_len = struct.calcsize(header_fmt) + 4 + len(code_bytes) + 8*len(excepts) + sum(map(len, attributes))
    
    assembled_bytes = struct.pack('>HI', name_ind, attr_len)
    assembled_bytes += struct.pack(header_fmt, stack, locals_, len(code_bytes))
    assembled_bytes += code_bytes
    assembled_bytes += struct.pack('>H', len(excepts)) + ''.join(excepts)
    assembled_bytes += struct.pack('>H', len(attributes)) + ''.join(attributes)
    return assembled_bytes, method_attributes

def assemble(tree, addLineNumbers, jasmode, filename):
    pool = PoolInfo()
    version, sourcefile, classdec, superdec, interface_decs, topitems = tree
    if not version: #default to version 49.0 except in Jasmin compatibility mode
        version = (45,3) if jasmode else (49,0)

    #scan topitems, plus statements in each method to get cpool directives
    interfaces = []
    fields = []
    methods = []
    attributes = []

    top_d = collections.defaultdict(list)
    for t, val in topitems:
        top_d[t].append(val)

    for slot, value in top_d['const']:
        if slot.index is not None:
            pool.fixed[slot.index] = value
        else:
            pool.lbls[slot.lbl] = value
    pool.assignFixedSlots()

    for flags, name, desc, const in top_d['field']:
        flagbits = map(Field.flagVals.get, flags)
        flagbits = reduce(operator.__or__, flagbits, 0)
        name = name.toIndex(pool)
        desc = desc.toIndex(pool)

        if const is not None:
            attr = struct.pack('>HIH', pool.Utf8("ConstantValue"), 2, const.toIndex(pool))
            fattrs = [attr]
        else:
            fattrs = []

        field_code = struct.pack('>HHHH', flagbits, name, desc, len(fattrs)) + ''.join(fattrs)
        fields.append(field_code)


    for header, statements in top_d['method']:
        mflags, (name, desc) = header
        name = name.toIndex(pool)
        desc = desc.toIndex(pool)

        flagbits = map(Method.flagVals.get, mflags)
        flagbits = reduce(operator.__or__, flagbits, 0)

        #method attributes processed inside assemble Code since it's easier there
        code_attr, mattrs = assembleCodeAttr(statements, pool, version, addLineNumbers, jasmode)
        if code_attr is not None:
            mattrs.append(code_attr)

        method_code = struct.pack('>HHHH', flagbits, name, desc, len(mattrs)) + ''.join(mattrs)
        methods.append(method_code)

    if pool.bootstrap:
        entries = [struct.pack('>H' + 'H'*len(bsargs), bsargs[0], len(bsargs)-1, *bsargs[1:]) for bsargs in pool.bootstrap]   
        attrbody = ''.join(entries)
        attrhead = struct.pack('>HIH', pool.Utf8("BootstrapMethods"), 2+len(attrbody), len(entries))
        attributes.append(attrhead + attrbody)

    if jasmode and not sourcefile:
        sourcefile = pool.Utf8(filename)
    elif addLineNumbers and not sourcefile:
        sourcefile = pool.Utf8("SourceFile")
    if sourcefile:
        sourceattr = struct.pack('>HIH', pool.Utf8("SourceFile"), 2, sourcefile.toIndex(pool))
        attributes.append(sourceattr)

    interfaces = [x.toIndex(pool) for x in interface_decs]

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
        bytes = struct.pack('>H', len(stuff)) + ''.join(stuff)
        class_code += bytes

    name = pool.pool.getArgs(this)[0]
    return name, class_code