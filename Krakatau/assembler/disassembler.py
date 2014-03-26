import collections
import re

from . import instructions, tokenize, parse, assembler, codes
from ..binUnpacker import binUnpacker
from ..classfile import ClassFile

MAX_INLINE_LENGTH = 50

rhandle_codes = {v:k for k,v in codes.handle_codes.items()}
rnewarr_codes = {v:k for k,v in codes.newarr_codes.items()}

not_word_regex = '(?:{}|{}|{}|;)'.format(tokenize.int_base, tokenize.float_base, tokenize.t_CPINDEX)
not_word_regex = re.compile(not_word_regex, re.VERBOSE)
is_word_regex = re.compile(tokenize.t_WORD.__doc__+'$')
assert(is_word_regex.match("''") is None)

def isWord(s):
    '''Determine if s can be used as an inline word'''
    if s in parse.badwords or (not_word_regex.match(s) is not None):
        return False
    #eliminate unprintable characters below 32
    #also, don't allow characters above 127 to keep things simpler
    return (is_word_regex.match(s) is not None) and min(s) > ' ' and max(s) <= '\x7f'

def rstring(s, allowWord=True):
    '''Returns a representation of the string. If allowWord is true, it will be unquoted if possible'''
    if allowWord and isWord(s):
        return s
    try:
        if s.encode('ascii') == s:
            return repr(str(s))
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return repr(s)

class PoolManager(object):
    def __init__(self, pool):
        self.const_pool = pool #keep this around for the float conversion function
        self.pool = pool.pool
        self.bootstrap_methods = [] #filled in externally
        self.used = set() #which cp entries are used non inline and so must be printed

        #For each type, store the function needed to generate the rhs of a constant pool specifier
        temp1 = lambda ind: rstring(self.cparg1(ind))
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

    def inlineutf(self, ind, allowWord=True):
        '''Returns the word if it's short enough to inline, else None'''
        arg = self.cparg1(ind)
        rstr = rstring(arg, allowWord=allowWord)
        if len(rstr) <= MAX_INLINE_LENGTH:
            return rstr
        return None

    def ref(self, ind):
        self.used.add(ind)
        return '[_{}]'.format(ind)

    def utfref(self, ind):
        if ind == 0:
            return '[0]'
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
        if ind == 0:
            return '[0]'
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
            if typen == "Float" or typen == "Double":
                arg = self.const_pool.getArgs(ind)[0]

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

def getAttributeTriples(obj): #name_ind, name, data
    return [(name_ind, name, data1) for (name_ind, data1), (name, data2) in zip(obj.attributes_raw, obj.attributes)]

def getAttributesDict(obj):
    d = collections.defaultdict(list)
    for ind, name, attr in getAttributeTriples(obj):
        d[name].append((ind, attr))
    return d

fmt_lookup = {k:v.format for k,v in assembler.op_structs.items()}
def getInstruction(b, getlbl, poolm):
    pos = b.off
    op = b.get('B')

    name = instructions.allinstructions[op]
    if name == 'wide':
        name2 = instructions.allinstructions[b.get('B')]
        if name2 == 'iinc':
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
            entries += ['\t\t{} : {}'.format(b.get('>i'), getlbl(b.get('>i')+pos)) for _ in range(num)]
        else:
            low, high = b.get('>ii')
            num = high-low+1
            entries = ['\t{} {}'.format(name, low)]
            entries += ['\t\t{}'.format(getlbl(b.get('>i')+pos)) for _ in range(num)]
        entries += ['\t\tdefault : {}'.format(default)]
        return '\n'.join(entries)
    else:
        args = list(b.get(fmt_lookup[name], forceTuple=True))
        #remove extra padding 0
        if name in ('invokeinterface','invokedynamic'):
            args = args[:-1]

        funcs = {
                'OP_CLASS': poolm.classref,
                'OP_CLASS_INT': poolm.classref,
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
    add('\t; method code size: {} bytes'.format(code.codelen))
    add('\t.limit stack {}'.format(code.stack))
    add('\t.limit locals {}'.format(code.locals))

    lbls = set()
    def getlbl(x):
        lbls.add(x)
        return 'L'+str(x)

    for e in code.except_raw:
        parts = poolm.classref(e.type_ind), getlbl(e.start), getlbl(e.end), getlbl(e.handler)
        add('\t.catch {} from {} to {} using {}'.format(*parts))

    code_attributes = getAttributesDict(code)
    frames = getStackMapTable(code_attributes, poolm, getlbl)

    instrs = []
    b = binUnpacker(code.bytecode_raw)
    while b.size():
        instrs.append((b.off, getInstruction(b, getlbl, poolm)))
    instrs.append((b.off, None))

    for off, instr in instrs:
        if off in lbls:
            add('L{}:'.format(off))
        if off in frames:
            add(frames[off])
        if instr:
            add(instr)

    #Generic code attributes
    for name in code_attributes:
        #We can't disassemble these because Jasmin's format for these attributes
        #is overly cumbersome and not easy to disassemble into, but we can't just
        #leave them as binary blobs either as they are verified by the JVM and the
        #later two contain constant pool references which won't be preserved even
        #if the bytecode isn't changed. For now, we just ommit them entirely.
        #TODO - find a better solution
        if name in ("LineNumberTable","LocalVariableTable","LocalVariableTypeTable"):
            continue

        for name_ind, attr in code_attributes[name]:
            add('.codeattribute {} {!r}'.format(poolm.utfref(name_ind), attr))

def getVerificationType(bytes_, poolm, getLbl):
    s = codes.vt_keywords[bytes_.get('>B')]
    if s == 'Object':
        s += ' ' + poolm.classref(bytes_.get('>H'))
    elif s == 'Uninitialized':
        s += ' ' + getLbl(bytes_.get('>H'))
    return s

def getStackMapTable(code_attributes, poolm, getLbl):
    smt_attrs = code_attributes['StackMapTable']

    frames = {}
    offset = 0

    if smt_attrs:
        assert(len(smt_attrs) == 1)
        bytes_ = binUnpacker(smt_attrs.pop()[1])
        count = bytes_.get('>H')
        getVT = lambda: getVerificationType(bytes_, poolm, getLbl)

        for _ in range(count):
            tag = bytes_.get('>B')
            header, contents = None, []

            if 0 <= tag <= 63:
                offset += tag
                header = 'same'
            elif 64 <= tag <= 127:
                offset += tag - 64
                header = 'same_locals_1_stack_item'
                contents.append('\tstack ' + getVT())
            elif tag == 247:
                offset += bytes_.get('>H')
                header = 'same_locals_1_stack_item_extended'
                contents.append('\tstack ' + getVT())
            elif 248 <= tag <= 250:
                offset += bytes_.get('>H')
                header = 'chop ' + str(251-tag)
            elif tag == 251:
                offset += bytes_.get('>H')
                header = 'same_extended'
            elif 252 <= tag <= 254:
                offset += bytes_.get('>H')
                header = 'append'
                contents.append('\tlocals ' + ' '.join(getVT() for _ in range(tag-251)))
            elif tag == 255:
                offset += bytes_.get('>H')
                header = 'full'
                local_count = bytes_.get('>H')
                contents.append('\tlocals ' + ' '.join(getVT() for _ in range(local_count)))
                stack_count = bytes_.get('>H')
                contents.append('\tstack ' + ' '.join(getVT() for _ in range(stack_count)))

            if contents:
                contents.append('.end stack')
            contents = ['.stack ' + header] + contents
            frame = '\n'.join(contents)
            frames[offset] = frame
            offset += 1 #frames after the first have an offset one larger than the listed offset
    return frames

def disCFMAttribute(name_ind, name, bytes_, add, poolm):
    for vis in ('Visible', 'Invisible'):
        if name == 'Runtime{}Annotations'.format(vis):
            count = bytes_.get('>H')
            for _ in range(count):
                disAnnotation(bytes_, '.runtime{} '.format(vis.lower()), add, poolm, '')
            if count: #otherwise we'll create an empty generic attribute
                return

    if name == "Signature":
        add('.signature {}'.format(poolm.utfref(bytes_.get('>H'))))
        return
    #Create generic attribute if it can't be represented by a standard directive
    add('.attribute {} {!r}'.format(poolm.utfref(name_ind), bytes_.getRaw(bytes_.size())))

def disMethodAttribute(name_ind, name, bytes_, add, poolm):
    if name == 'Code':
        return
    elif name == 'AnnotationDefault':
        disElementValue(bytes_, '.annotationdefault ', add, poolm, '')
        return
    elif name == 'Exceptions':
        count = bytes_.get('>H')
        for _ in range(count):
            add('.throws ' + poolm.classref(bytes_.get('>H')))
        if count: #otherwise we'll create an empty generic attribute
            return

    for vis in ('Visible', 'Invisible'):
        if name == 'Runtime{}ParameterAnnotations'.format(vis):
            for i in range(bytes_.get('>B')):
                for _ in range(bytes_.get('>H')):
                    disAnnotation(bytes_, '.runtime{} parameter {} '.format(vis.lower(), i), add, poolm, '')
            return #generic fallback on empty list not yet supported

    disCFMAttribute(name_ind, name, bytes_, add, poolm)

def disMethod(method, add, poolm):
    mflags = ' '.join(map(str.lower, method.flags))
    add('.method {} {} : {}'.format(mflags, poolm.utfref(method.name_id), poolm.utfref(method.desc_id)))

    for name_ind, name, attr in getAttributeTriples(method):
        disMethodAttribute(name_ind, name, binUnpacker(attr), add, poolm)

    disMethodCode(method.code, add, poolm)
    add('.end method')

def _disEVorAnnotationSub(bytes_, add, poolm, isAnnot, init_prefix, init_indent):
    C_ANNOT, C_ANNOT2, C_ANNOT3, C_EV, C_EV2 = range(5)
    init_callt = C_ANNOT if isAnnot else C_EV

    stack = [(init_callt, init_prefix, init_indent)]
    while stack:
        callt, prefix, indent = stack.pop()

        if callt == C_ANNOT:
            add(indent + prefix + 'annotation ' + poolm.utfref(bytes_.get('>H')))
            #ones we want to happen last should be first on the stack. Annot3 is the final call which ends the annotation
            stack.append((C_ANNOT3, None, indent))
            stack.extend([(C_ANNOT2, None, indent)] * bytes_.get('>H'))

        elif callt == C_ANNOT2:
            key = poolm.utfref(bytes_.get('>H'))
            stack.append((C_EV, key + ' = ', indent+'\t'))

        elif callt == C_ANNOT3:
            add(indent + '.end annotation')

        elif callt == C_EV:
            tag = codes.et_rtags[bytes_.getRaw(1)]
            if tag == 'annotation':
                stack.append((C_ANNOT, prefix, indent + '\t'))
            else:
                if tag in ('byte','char','double','int','float','long','short','boolean','string'):
                    val = poolm.ldc(bytes_.get('>H'))
                elif tag == 'class':
                    val = poolm.utfref(bytes_.get('>H'))
                elif tag == 'enum':
                    val = poolm.utfref(bytes_.get('>H')) + ' ' + poolm.utfref(bytes_.get('>H'))
                elif tag == 'array':
                    val = ''

                add(indent + '{} {} {}'.format(prefix, tag, val))
                if tag == 'array':
                    for _ in range(bytes_.get('>H')):
                        stack.append((C_EV, '', indent+'\t'))
                    stack.append((C_EV2, None, indent))

        elif callt == C_EV2:
            add(indent + '.end array')

def disElementValue(bytes_, prefix, add, poolm, indent):
    _disEVorAnnotationSub(bytes_, add, poolm, False, prefix, indent)

def disAnnotation(bytes_, prefix, add, poolm, indent):
    _disEVorAnnotationSub(bytes_, add, poolm, True, prefix, indent)

#Todo - make fields automatically unpack this themselves
def getConstValue(field):
    if not field.static:
        return None
    const_attrs = [attr for attr in field.attributes if attr[0] == 'ConstantValue']
    if const_attrs:
        assert(len(const_attrs) == 1)
        bytes_ = binUnpacker(const_attrs[0][1])
        return bytes_.get('>H')

_classflags = [(v,k.lower()) for k,v in ClassFile.flagVals.items()]
def disInnerClassesAttribute(name_ind, length, bytes_, add, poolm):
    count = bytes_.get('>H')

    if length != 2+8*count:
        add('.innerlength {}'.format(length))

    for _ in range(count):
        inner, outer, innername, flagbits = bytes_.get('>HHHH')

        flags = [v for k,v in _classflags if k&flagbits]
        inner = poolm.classref(inner)
        outer = poolm.classref(outer)
        innername = poolm.utfref(innername)

        add('.inner {} {} {} {}'.format(' '.join(flags), innername, inner, outer))

    if not count:
        add('.attribute InnerClasses "\\0\\0"')

def disOtherClassAttribute(name_ind, name, bytes_, add, poolm):
    assert(name != 'InnerClasses')
    if name == 'EnclosingMethod':
        cls, nat = bytes_.get('>HH')
        add('.enclosing method {} {}'.format(poolm.classref(cls), poolm.multiref(nat)))
        return
    disCFMAttribute(name_ind, name, bytes_, add, poolm)

def disassemble(cls):
    lines = []
    add = lines.append
    poolm = PoolManager(cls.cpool)

    # def add(s): print s
    add('.version {0[0]} {0[1]}'.format(cls.version))

    class_attributes = getAttributesDict(cls)
    if 'SourceFile' in class_attributes:
        bytes_ = binUnpacker(class_attributes['SourceFile'].pop()[1])
        val_ind = bytes_.get('>H')
        add('.source {}'.format(poolm.utfref(val_ind)))

    if 'BootstrapMethods' in class_attributes:
        bytes_ = binUnpacker(class_attributes['BootstrapMethods'].pop()[1])
        count = bytes_.get('>H')
        for _ in range(count):
            arg1, argc = bytes_.get('>HH')
            args = (arg1,) + bytes_.get('>'+'H'*argc, forceTuple=True)
            poolm.bootstrap_methods.append(args)

    cflags = ' '.join(map(str.lower, cls.flags))
    add('.class {} {}'.format(cflags, poolm.classref(cls.this)))
    add('.super {}'.format(poolm.classref(cls.super)))
    for ii in cls.interfaces_raw:
        add('.implements {}'.format(poolm.classref(ii)))

    for name in class_attributes:
        if name == "InnerClasses":
            assert(len(class_attributes[name]) == 1)
            for name_ind, (length, attr) in class_attributes[name]:
                disInnerClassesAttribute(name_ind, length, binUnpacker(attr), add, poolm)
        else:
            for name_ind, attr in class_attributes[name]:
                disOtherClassAttribute(name_ind, name, binUnpacker(attr), add, poolm)

    add('')
    for field in cls.fields:
        fflags = ' '.join(map(str.lower, field.flags))
        const = getConstValue(field)

        if const is not None:
            add('.field {} {} {} = {}'.format(fflags, poolm.utfref(field.name_id), poolm.utfref(field.desc_id), poolm.ldc(const)))
        else:
            add('.field {} {} {}'.format(fflags, poolm.utfref(field.name_id), poolm.utfref(field.desc_id)))

        facount = 0
        for name_ind, name, attr in getAttributeTriples(field):
            if name == 'ConstantValue' and field.static:
                continue
            disMethodAttribute(name_ind, name, binUnpacker(attr), add, poolm)
            facount += 1
        if facount > 0:
            add('.end field')
            add('')

    add('')

    for method in cls.methods:
        disMethod(method, add, poolm)
        add('')

    poolm.printConstDefs(add)
    return '\n'.join(lines)