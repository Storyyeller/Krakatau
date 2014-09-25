import struct

from ..ssa import objtypes
from ..verifier.descriptors import parseFieldDescriptor

from . import ast, ast2, javamethod
from .reserved import reserved_identifiers

IGNORE_EXCEPTIONS = 0

def loadConstValue(cpool, index):
    entry_type = cpool.pool[index][0]
    args = cpool.getArgs(index)

    #Note: field constant values cannot be class literals
    tt = {'Int':objtypes.IntTT, 'Long':objtypes.LongTT,
        'Float':objtypes.FloatTT, 'Double':objtypes.DoubleTT,
        'String':objtypes.StringTT}[entry_type]
    return ast.Literal(tt, args[0])

def _getField(field):
    flags = [x.lower() for x in sorted(field.flags) if x not in ('SYNTHETIC','ENUM')]
    desc = field.descriptor
    dtype = objtypes.verifierToSynthetic(parseFieldDescriptor(desc, unsynthesize=False)[0])

    initexpr = None
    if field.static:
        cpool = field.class_.cpool
        const_attrs = [data for name,data in field.attributes if name == 'ConstantValue']
        if const_attrs:
            assert(len(const_attrs) == 1)
            data = const_attrs[0]
            index = struct.unpack('>h', data)[0]
            initexpr = loadConstValue(cpool, index)
    return ast2.FieldDef(' '.join(flags), ast.TypeName(dtype), field.class_, field.name, desc, initexpr)

def _getMethod(method, cb, forbidden_identifiers):
    try:
        graph = cb(method) if method.code is not None else None
        print 'Decompiling method', method.name.encode('utf8'), method.descriptor.encode('utf8')
        code_ast = javamethod.generateAST(method, graph, forbidden_identifiers)
        return code_ast
    except Exception as e:
        if not IGNORE_EXCEPTIONS:
            raise
        if e.__class__.__name__ == 'DecompilationError':
            print 'Unable to decompile ' + method.class_.name
        else:
            print 'Decompiling {} failed!'.format(method.class_.name)
        code_ast = javamethod.generateAST(method, None, forbidden_identifiers)
        code_ast.comment = ' {0!r}: {0!s}'.format(e)
        return code_ast

def generateAST(cls, cb, method=None):
    methods = cls.methods if method is None else [cls.methods[method]]
    fi = set(reserved_identifiers)
    for field in cls.fields:
        fi.add(field.name)
    forbidden_identifiers = frozenset(fi)

    myflags = [x.lower() for x in sorted(cls.flags) if x not in ('INTERFACE','SUPER','SYNTHETIC','ANNOTATION','ENUM')]
    isInterface = 'INTERFACE' in cls.flags

    superc = cls.supername
    interfaces = [cls.cpool.getArgsCheck('Class', index) for index in cls.interfaces_raw] #todo - change when class actually loads interfaces

    field_defs = [_getField(f) for f in cls.fields]
    method_defs = [_getMethod(m, cb, forbidden_identifiers) for m in methods]
    return ast2.ClassDef(' '.join(myflags), isInterface, cls.name, superc, interfaces, field_defs, method_defs)
