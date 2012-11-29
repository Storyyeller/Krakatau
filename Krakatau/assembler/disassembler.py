import collections, itertools
import struct, operator
import re, math

from . import instructions, tokenize, assembler
from .. import constant_pool
from ..classfile import ClassFile
from ..method import Method
from ..field import Field
from ..binUnpacker import binUnpacker

not_word_regex = '(?:{}|{}|{}|;)'.format(tokenize.int_base, tokenize.float_base, tokenize.t_CPINDEX)
not_word_regex = re.compile(not_word_regex, re.VERBOSE)
is_word_regex = re.compile(tokenize.t_WORD+'$')

def isWord(s):
    if s in tokenize.wordget or (not_word_regex.match(s) is not None):
        return False
    return (is_word_regex.match(s) is not None) and min(s) > ' ' #eliminate unprintable characters below 32

class PoolManager(object):
    def __init__(self, pool):
        self.pool = pool.pool
        self.used = set()

    def rstring(self, s, allowWord=True):
        if allowWord and isWord(s):
            return s
        try:
            if s.encode('ascii') == s:
                return repr(str(s))
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            pass 
        return repr(s)

    def ref(self, ind):
        self.used.add(ind)
        return '[_{}]'.format(ind)

    def utfref(self, ind, allowRef=True):    
        arg = self.pool[ind][1][0]
        rstr = self.rstring(arg)
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

    def multiref(self, ind):
        typen, args = self.pool[ind]
        if typen == "Utf8":
            return self.utfref(ind)
        elif typen == "Class":
            return self.classref(ind)
        return ' '.join(map(self.multiref, args))

    def ldc(self, ind):
        typen, args = self.pool[ind]
        arg = args[0]

        if typen == 'String':
            arg = self.pool[arg][1][0]
            rstr = self.rstring(arg, allowWord=False)
            return rstr if len(rstr) <= 50 else self.ref(ind)
        elif typen == 'Class':
            return self.ref(ind)
        else:
            rstr = repr(arg).rstrip("Ll")
            if typen == "Float" or typen == "Long":
                rstr += typen[0]
            return rstr

    def printConstDefs(self, add):
        defs = {}

        while self.used:
            temp, self.used = self.used, set()
            for ind in temp:
                if ind in defs:
                    continue

                typen, args = self.pool[ind]
                if typen in ('Int','Float','Long','Double'):
                    defs[ind] = self.ldc(ind)
                elif typen in ('Class','String'):
                    uind = self.pool[ind][1][0]
                    defs[ind] = self.utfref(uind)
                elif typen == 'Utf8':
                    #can't have a ref here
                    arg = self.pool[ind][1][0]
                    defs[ind] = self.rstring(arg)
                else:
                    defs[ind] = self.multiref(ind)

        for ind in sorted(defs):
            add('.const [_{}] = {} {}'.format(ind, self.pool[ind][0].lower(), defs[ind]))


fmt_lookup = {k:v.format for k,v in assembler._op_structs.items()}
def getInstruction(b, getlbl, poolm):
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
            num = high-low+1
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
            func = poolm.ldc if token_t[3:6] == "LDC" else poolm.multiref
            args[0] = func(args[0])
        elif token_t == 'OP_NEWARR':
            args[0] = 'boolean char float double byte short int long'.split()[args[0]-4]

        parts = [name] + map(str, args)
        return '\t' + ' '.join(parts)

def disMethodCode(code, add, poolm):
    if code is None:
        return
    add('\t.limit stack {}'.format(code.stack))
    add('\t.limit locals {}'.format(code.locals))

    lbls = set()
    def getlbl(x):
        lbls.add(x)
        return 'L'+str(x)

    for e in code.except_raw:
        parts = poolm.classref(e.type_ind), getlbl(e.start), getlbl(e.end), getlbl(e.handler)
        add('\t.catch {} from {} to {} using {}'.format(*parts))

    instrs = []
    b = binUnpacker(code.bytecode_raw)
    while b.size():
        instrs.append((b.off, getInstruction(b, getlbl, poolm)))
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
    poolm = PoolManager(cls.cpool)

    cflags = ' '.join(map(str.lower, cls.flags))
    add('.class {} {}'.format(cflags, poolm.classref(cls.this)))
    add('.super {}'.format(poolm.classref(cls.super)))
    for ii in cls.interfaces_raw:
        add('.interface {}'.format(poolm.classref(ii)))
    add('')

    for field in cls.fields:
        fflags = ' '.join(map(str.lower, field.flags))
        const = getConstValue(field)

        if const is not None:
            add('.field {} {} {} = {}'.format(fflags, poolm.utfref(field.name_id), poolm.utfref(field.desc_id), poolm.ldc(const)))
        else:
            add('.field {} {} {}'.format(fflags, poolm.utfref(field.name_id), poolm.utfref(field.desc_id)))
    add('')

    for method in cls.methods:
        mflags = ' '.join(map(str.lower, method.flags))
        add('.method {} {} : {}'.format(mflags, poolm.utfref(method.name_id), poolm.utfref(method.desc_id)))
        
        throw_attrs = [a for a in method.attributes if cls.cpool.getArgsCheck('Utf8', a[0]) == 'Exceptions']
        for a in throw_attrs:
            bytes = binUnpacker(a[1])
            for i in range(bytes.get('>H')):
                add('.throws ' + poolm.classref(bytes.get('>H')))


        disMethodCode(method.code, add, poolm)
        add('.end method')
        add('')

    poolm.printConstDefs(add)
    return '\n'.join(lines)