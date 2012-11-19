import collections, itertools
import struct, operator
import re, math

from . import instructions, tokenize, assembler
from .. import constant_pool
from ..classfile import ClassFile
from ..method import Method
from ..field import Field
from ..binUnpacker import binUnpacker

def isWord(s):
    return s not in tokenize.wordget and re.match(tokenize.T_WORD+'$', s) is not None

class PoolManager(object):
    def __init__(self, pool):
        self.pool = pool
        self.used = set()

    def ref(self, ind):
        self.used.add(ind)
        return '[_{}]'.format(ind)

    def utfref(self, ind, allowRef=True):    
        arg = self.pool[ind][1][0]
        rstr = arg if isWord(arg) else repr(arg)
        if len(rstr) <= 50:
            return rstr
        if allowRef:
            return self.ref(ind)
        return None

    def classref(self, ind):
        if ind == 0:
            return '[0]'    
        uind = self.pool[ind][1][0]
        inline = self.utfref(uind, False) 
        return inline if inline is not None else self.ref(ind)

    # def fmimref(self, ind):
    def ldc(self, ind):
        typen, args = self.pool[ind]
        arg = args[0]
        rstr = repr(arg)

        if typen == 'String':
            return rstr if len(rstr) <= 50 else self.ref(ind)
        elif typen == 'Class':
            return self.ref(ind)
        else:
            rstr = rstr.rstrip("Ll")
            if typen == "Float" or typen == "Long":
                rstr += typen[0]
            return rstr

fmt_lookup = {k:v.format for k,v in assembler._op_structs.items()}


def getInstruction(b, getlbl):
    pos = b.off
    op = b.get('B')

    name = instructions.allinstructions[op]

    if name == 'wide':
        name2 = instructions.allinstructions[b.get('B')]
        if name == 'iinc':
            args = list(b.get('>Hh'))
        else:
            args = [b.get('>H')]

        parts = [name, name2] + map(str, args)
        return '\t' + ' '.join(parts)
    elif name == 'tableswitch' or name == 'lookupswitch':
        padding = assembler.getPadding(pos)
        b.getRaw(padding)

        default = getlbl(b.get('>i')+pos)
        if name == 'lookupswitch':
            num = b.get('>I')
            entries = ['\t'+name]
            entries += ['\t\t{} : {}'.format(b.get('>i'), getlbl(b.get('>i')+pos)) for i in range(num)]
        else:
            low, high = b.get('>ii')
            num = high-low+2
            entries = ['\t{} : {}'.format(name, low)]
            entries += ['\t\t{}'.format(getlbl(b.get('>i')+pos)) for i in range(num)]
        entries += ['\t\tdefault : {}'.format(default)]
        return '\n'.join(entries)
    else:
        args = list(b.get(fmt_lookup[name], forceTuple=True))
        token_t = tokenize.wordget[name]
        if token_t == 'OP_LBL':
            assert(len(args) == 1)
            args[0] = getlbl(args[0]+pos)
        elif token_t[3:] in ('FIELD','METHOD','CLASS','CLASS_INT','METHOD_INT','LDC1','LDC2'):
            args[0] = '[_{}]'.format(args[0])
        elif token_t == 'OP_NEWARR':
            args[0] = 'boolean char float double byte short int long'.split()[args[0]-4]

        parts = [name] + map(str, args)
        return '\t' + ' '.join(parts)

def disMethodCode(code, add, printCPInd):
    if code is None:
        return
    add('\t.limit stack {}'.format(code.stack))
    add('\t.limit locals {}'.format(code.locals))

    lbls = set()
    def getlbl(x):
        lbls.add(x)
        return 'L'+str(x)

    for e in code.except_raw:
        parts = printCPInd(e.type_ind), getlbl(e.start), getlbl(e.end), getlbl(e.handler)
        add('\t.catch {} from {} to {} using {}'.format(*parts))

    instrs = []
    b = binUnpacker(code.bytecode_raw)
    while b.size():
        instrs.append((b.off, getInstruction(b, getlbl)))
    instrs.append((b.off, None))

    for off, instr in instrs:
        if off in lbls:
            add('L{}:'.format(off))
        if instr:
            add(instr)

#Todo - make fields automatically unpack this themselves
def getConstValue(field):
    if not field.static:
        return None
    cpool = field.class_.cpool
    const_attrs = [attr for attr in field.attributes if cpool.getArgsCheck('Utf8', attr[0]) == 'ConstantValue']
    if const_attrs:
        assert(len(const_attrs) == 1)
        data = const_attrs[0][1]
        return struct.unpack('>h', data)[0]

def disassemble(cls):
    lines = []
    add = lines.append

    def printCPInd(i):
        return '[_{}]'.format(i) if i else '[0]'
    poolm = PoolManager(cls.cpool)

    cflags = ' '.join(map(str.lower, cls.flags))
    add('.class {} {}'.format(cflags, printCPInd(cls.this)))
    add('.super {}'.format(printCPInd(cls.super)))
    for ii in cls.interfaces_raw:
        add('.interface {}'.format(printCPInd(ii)))
    add('')

    for i,(t, args) in cls.cpool.getEnumeratePoolIter():
        if t in ('Class','String','NameAndType','Field','Method','InterfaceMethod'):
            args = map(printCPInd, args)
        else:
            args = map(repr, args)
        add('.const [_{}] = {} {}'.format(i, t.lower(), ' '.join(args)))
    add('')

    for field in cls.fields:
        fflags = ' '.join(map(str.lower, field.flags))
        const = getConstValue(field)

        if const is not None:
            add('.field {} {} {} = {}'.format(fflags, printCPInd(field.name_id), printCPInd(field.desc_id), printCPInd(const)))
        else:
            add('.field {} {} {}'.format(fflags, printCPInd(field.name_id), printCPInd(field.desc_id)))
    add('')

    for method in cls.methods:
        mflags = ' '.join(map(str.lower, method.flags))
        add('.method {} {} : {}'.format(mflags, printCPInd(method.name_id), printCPInd(method.desc_id)))
        disMethodCode(method.code, add, printCPInd)
        add('.end method')
        add('')

    return '\n'.join(lines)