from . import ast
from .stringescape import escapeString as escape

class MethodDef(object):
    def __init__(self, class_, flags, name, desc, retType, paramDecls, body):
        self.flagstr = flags + ' ' if flags else ''
        self.retType, self.paramDecls = retType, paramDecls
        self.body = body
        self.comment = None
        self.triple = class_.name, name, desc

        if name == '<clinit>':
            self.isStaticInit, self.isConstructor = True, False
        elif name == '<init>':
            self.isStaticInit, self.isConstructor = False, True
            self.clsname = ast.TypeName((class_.name, 0))
        else:
            self.isStaticInit, self.isConstructor = False, False

    def print_(self, printer, print_):
        argstr = ', '.join(print_(decl) for decl in self.paramDecls)
        if self.isStaticInit:
            header = 'static'
        elif self.isConstructor:
            name = print_(self.clsname).rpartition('.')[-1]
            header = '{}{}({})'.format(self.flagstr, name, argstr)
        else:
            name = printer.methodName(*self.triple)
            header = '{}{} {}({})'.format(self.flagstr, print_(self.retType), escape(name), argstr)

        if self.comment:
            header = '//{}\n{}'.format(self.comment, header)

        if self.body is None:
            return header + ';\n'
        else:
            return header + '\n' + print_(self.body)

class FieldDef(object):
    def __init__(self, flags, type_, class_, name, desc, expr=None):
        self.flagstr = flags + ' ' if flags else ''
        self.type_ = type_
        self.name = name
        self.expr = None if expr is None else ast.makeCastExpr(type_.tt, expr)
        self.triple = class_.name, name, desc

    def print_(self, printer, print_):
        name = escape(printer.fieldName(*self.triple))
        if self.expr is not None:
            return '{}{} {} = {};'.format(self.flagstr, print_(self.type_), name, print_(self.expr))
        return '{}{} {};'.format(self.flagstr, print_(self.type_), name)

class ClassDef(object):
    def __init__(self, flags, isInterface, name, superc, interfaces, fields, methods):
        self.flagstr = flags + ' ' if flags else ''
        self.isInterface = isInterface
        self.name = ast.TypeName((name,0))
        self.super = ast.TypeName((superc,0)) if superc is not None else None
        self.interfaces = [ast.TypeName((iname,0)) for iname in interfaces]
        self.fields = fields
        self.methods = methods
        if superc == 'java/lang/Object':
            self.super = None

    def print_(self, printer, print_):
        contents = ''
        if self.fields:
            contents = '\n'.join(print_(x) for x in self.fields)
        if self.methods:
            if contents:
                contents += '\n\n' #extra line to divide fields and methods
            contents += '\n\n'.join(print_(x) for x in self.methods)

        indented = ['    '+line for line in contents.splitlines()]
        name = print_(self.name).rpartition('.')[-1]
        defname = 'interface' if self.isInterface else 'class'
        header = '{}{} {}'.format(self.flagstr, defname, name)

        if self.super:
            header += ' extends ' + print_(self.super)
        if self.interfaces:
            if self.isInterface:
                assert(self.super is None)
                header += ' extends ' + ', '.join(print_(x) for x in self.interfaces)
            else:
                header += ' implements ' + ', '.join(print_(x) for x in self.interfaces)

        lines = [header + ' {'] + indented + ['}']
        return '\n'.join(lines)