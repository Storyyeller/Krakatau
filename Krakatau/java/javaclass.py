import struct

from ..ssa import objtypes
from ..verifier.descriptors import parseFieldDescriptor

from . import ast, ast2
from .javamethod import generateAST
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

class ClassDecompiler(object):
    def __init__(self, class_, cb, method=None):
        self.env = class_.env
        self.class_ = class_
        self.cb = cb
        self.methods = class_.methods if method is None else [class_.methods[method]]

        fi = set(reserved_identifiers)
        for field in class_.fields:
            fi.add(field.name)
        self.forbidden_identifiers = frozenset(fi)

    def _getField(self, field):
        flags = [x.lower() for x in sorted(field.flags) if x not in ('SYNTHETIC','ENUM')]
        desc = field.descriptor
        dtype = objtypes.verifierToSynthetic(parseFieldDescriptor(desc, unsynthesize=False)[0])

        initexpr = None
        if field.static:
            cpool = self.class_.cpool
            const_attrs = [data for name,data in field.attributes if name == 'ConstantValue']
            if const_attrs:
                assert(len(const_attrs) == 1)
                data = const_attrs[0]
                index = struct.unpack('>h', data)[0]
                initexpr = loadConstValue(cpool, index)
        return ast2.FieldDef(' '.join(flags), ast.TypeName(dtype), field.name, initexpr)

    def _getMethod(self, method):
        try:
            graph = self.cb(method) if method.code is not None else None
            print 'Decompiling method', method.name.encode('utf8'), method.descriptor.encode('utf8')
            code_ast = generateAST(method, graph, self.forbidden_identifiers)
            return code_ast
        except Exception as e:
            if not IGNORE_EXCEPTIONS:
                raise
            if e.__class__.__name__ == 'DecompilationError':
                print 'Unable to decompile ' + self.class_.name
            else:
                print 'Decompiling {} failed!'.format(self.class_.name)
            code_ast = generateAST(method, None, self.forbidden_identifiers)
            code_ast.comment = ' {0!r}: {0!s}'.format(e)
            return code_ast

    def generateSource(self):
        cls = self.class_
        myflags = [x.lower() for x in sorted(cls.flags) if x not in ('INTERFACE','SUPER','SYNTHETIC','ANNOTATION','ENUM')]
        isInterface = 'INTERFACE' in cls.flags

        superc = cls.supername
        interfaces = [cls.cpool.getArgsCheck('Class', index) for index in cls.interfaces_raw] #todo - change when class actually loads interfaces

        field_defs = map(self._getField, cls.fields)
        method_defs = map(self._getMethod, self.methods)
        ast_root = ast2.ClassDef(' '.join(myflags), isInterface, cls.name, superc, interfaces, field_defs, method_defs)
        return ast_root.print_()