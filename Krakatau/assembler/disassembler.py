import collections, itertools
import struct, operator
import re, math

from . import instructions, tokenize, assembler, codes
from .. import constant_pool
from ..classfile import ClassFile
from ..method import Method
from ..field import Field
from ..binUnpacker import binUnpacker

rhandle_codes = {v:k for k,v in codes.handle_codes.items()}
rnewarr_codes = {v:k for k,v in codes.newarr_codes.items()}

not_word_regex = '(?:{}|{}|{}|;)'.format(tokenize.int_base, tokenize.float_base, tokenize.t_CPINDEX)
not_word_regex = re.compile(not_word_regex, re.VERBOSE)
is_word_regex = re.compile(tokenize.t_WORD+'$')

def isWord(s):
    #if s is in wordget, that means it's a directive or keyword
    if s in tokenize.wordget or (not_word_regex.match(s) is not None):
        return False
    return (is_word_regex.match(s) is not None) and min(s) > ' ' #eliminate unprintable characters below 32

class PoolManager(object):
    def __init__(self, pool):
        self.pool = pool.pool
        self.bootstrap_methods = [] #filled in externally
        self.used = set() #which cp entries are used non inline and so must be printed

        #For each type, store the function needed to generate the rhs of a constant pool specifier
        temp1 = lambda ind: self.rstring(self.cparg1(ind))
        temp2 = lambda ind: self.utfref(self.cparg1(ind))

        self.cpref_table = {
            "Utf8": temp1, 
            
            "Class": temp2, 
            "String": temp2, 
            "MethodType": temp2, 

            "NameAndType": self.multiref, 
            "Field": self.multiref, 
            "Method": self.multiref, 
            "InterfaceMethod": self.multiref,

            "Int": self.ldc,
            "Long": self.ldc,
            "Float": self.ldc,
            "Double": self.ldc,

            "MethodHandle": self.methodhandle_notref, 
            "InvokeDynamic": self.invokedynamic_notref, 
            }

    def cparg1(self, ind):
        return self.pool[ind][1][0]

    def rstring(self, s, allowWord=True):
        '''Returns a representation of the string. If allowWord is true, it will be unquoted if possible'''
        if allowWord and isWord(s):
            return s
        try:
            if s.encode('ascii') == s:
                return repr(str(s))
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            pass 
        return repr(s)

    def inlineutf(self, ind, allowWord=True):
        '''Returns the word if it's short enough to inline, else None'''
        arg = self.cparg1(ind)
        rstr = self.rstring(arg, allowWord=allowWord)
        if len(rstr) <= 50:
            return rstr
        return None

    def ref(self, ind):
        self.used.add(ind)
        return '[_{}]'.format(ind)
    
    def utfref(self, ind):
        inline = self.inlineutf(ind) 
        return inline if inline is not None else self.ref(ind) 

    #Also works for Strings and MethodTypes
    def classref(self, ind):
        if ind == 0:
            return '[0]'    
        inline = self.inlineutf(self.cparg1(ind)) 
        return inline if inline is not None else self.ref(ind)

    #For Field, Method, IMethod, and NameAndType. Effectively notref
    def multiref(self, ind):
        typen, args = self.pool[ind]
        if typen == "Utf8":
            return self.utfref(ind)
        elif typen == "Class":
            return self.classref(ind)
        return ' '.join(map(self.multiref, args))

    #Special case for instruction fieldrefs as a workaround for Jasmin's awful syntax
    def notjasref(self, ind):
        typen, args = self.pool[ind]
        cind = self.cparg1(ind)
        inline = self.inlineutf(self.cparg1(cind)) 
        if inline is None:
            return self.ref(ind)
        return inline + ' ' + self.multiref(args[1])

    def ldc(self, ind):
        typen, args = self.pool[ind]
        arg = args[0]

        if typen == 'String':
            inline = self.inlineutf(arg, allowWord=False)
            return inline if inline is not None else self.ref(ind) 
        elif typen in ('Int','Long','Float','Double'):
            rstr = repr(arg).rstrip("Ll")
            if typen == "Float" or typen == "Long":
                rstr += typen[0]
            return rstr
        else:
            return self.ref(ind)

    def methodhandle_notref(self, ind):
        typen, args = self.pool[ind]
        code = rhandle_codes[args[0]]
        return code + ' ' + self.ref(args[1])    

    def invokedynamic_notref(self, ind):
        typen, args = self.pool[ind]
        bs_args = self.bootstrap_methods[args[0]]

        parts = [self.methodhandle_notref(bs_args[0])]
        parts += map(self.ref, bs_args[1:])
        parts += [':', self.multiref(args[1])]
        return ' '.join(parts)

    def printConstDefs(self, add):
        defs = {}

        while self.used:
            temp, self.used = self.used, set()
            for ind in temp:
                if ind in defs:
                    continue
                typen = self.pool[ind][0]
                defs[ind] = self.cpref_table[typen](ind)

        for ind in sorted(defs):
            add('.const [_{}] = {} {}'.format(ind, self.pool[ind][0], defs[ind]))


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
        #remove extra padding 0
        if name in ('invokeinterface','invokedynamic'):
            args = args[:-1] 

        funcs = {
                'OP_CLASS': poolm.classref, 
                'OP_FIELD': poolm.notjasref, #this is a special case due to the jasmin thing
                'OP_METHOD': poolm.multiref, 
                'OP_METHOD_INT': poolm.multiref, 
                'OP_DYNAMIC': poolm.ref, 
                'OP_LDC1': poolm.ldc, 
                'OP_LDC2': poolm.ldc, 
                'OP_NEWARR': rnewarr_codes.get, 
            }

        token_t = tokenize.wordget[name]
        if token_t == 'OP_LBL':
            assert(len(args) == 1)
            args[0] = getlbl(args[0]+pos)
        elif token_t in funcs:
            args[0] = funcs[token_t](args[0])

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

    add('.version {0[0]} {0[1]}'.format(cls.version))

    class_attributes = {cls.cpool.getArgsCheck('Utf8', name_ind):data for name_ind, data in cls.attributes_raw}
    if 'SourceFile' in class_attributes:
        bytes = binUnpacker(class_attributes['SourceFile'])
        val_ind = bytes.get('>H')
        add('.source {}'.format(poolm.utfref(val_ind)))

    if 'BootstrapMethods' in class_attributes:
        bytes = binUnpacker(class_attributes['BootstrapMethods'])
        count = bytes.get('>H')
        for i in range(count):
            arg1, argc = bytes.get('>HH')
            args = (arg1,) + bytes.get('>'+'H'*argc, forceTuple=True)
            poolm.bootstrap_methods.append(args)

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