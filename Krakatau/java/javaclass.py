import itertools, collections
import struct

from ..ssa import objtypes
from ..verifier.descriptors import parseFieldDescriptor

from . import ast, ast2
from .javamethod import MethodDecompiler

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

    def _getField(self, field):
        flags = [x.lower() for x in sorted(field.flags) if x not in ('SYNTHETIC','ENUM')]
        desc = field.descriptor
        dtype = objtypes.verifierToSynthetic(parseFieldDescriptor(desc, unsynthesize=False)[0])

        initexpr = None
        if field.static:
            cpool = self.class_.cpool
            const_attrs = [attr for attr in field.attributes if cpool.getArgsCheck('Utf8', attr[0]) == 'ConstantValue']
            if const_attrs:
                assert(len(const_attrs) == 1)
                data = const_attrs[0][1]
                index = struct.unpack('>h', data)[0]
                initexpr = loadConstValue(cpool, index)
        return ast2.FieldDef(' '.join(flags), ast.TypeName(dtype), field.name, initexpr)       

    def _getMethod(self, method):
        try:
            graph = self.cb(method) if method.code is not None else None
            print 'Decompiling method', method.name, method.descriptor
            code_ast = MethodDecompiler(method, graph).generateAST()
            return code_ast
        except Exception as e:
            if not IGNORE_EXCEPTIONS:
                raise
            if e.__class__.__name__ == 'DecompilationError':
                print 'Unable to decompile ' + self.class_.name
            else:
                print 'Decompiling {} failed!'.format(self.class_.name)
            code_ast = MethodDecompiler(method, None).generateAST()
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