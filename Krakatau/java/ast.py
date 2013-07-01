import itertools

from ..ssa import objtypes
from .stringescape import escapeString
# from ..ssa.constraints import ValueType

class VariableDeclarator(object):
    def __init__(self, typename, identifier): self.typename = typename; self.local = identifier

    def print_(self): 
        return '{} {}'.format(self.typename.print_(), self.local.print_())

#############################################################################################################################################

class JavaStatement(object):
    expr = None #provide default for subclasses that don't have an expression
    def getScopes(self): return []

    def addCastsAndParens(self, env):
        if self.expr is not None:
            self.expr.addCasts(env)
            self.expr.addParens()

class ExpressionStatement(JavaStatement):
    def __init__(self, expr):
        self.expr = expr

    def print_(self): return self.expr.print_() + ';'

class LocalDeclarationStatement(JavaStatement):
    def __init__(self, decl, expr=None):
        self.decl = decl
        self.expr = expr

    def print_(self): 
        if self.expr is not None:
            return '{} = {};'.format(self.decl.print_(), self.expr.print_())
        return self.decl.print_() + ';'

    def addCastsAndParens(self, env):
        if self.expr is not None:
            self.expr.addCasts(env)
            if not isJavaAssignable(env, self.expr.dtype, self.decl.typename.tt):
                self.expr = makeCastExpr(self.decl.typename.tt, self.expr)
            self.expr.addParens()

class ReturnStatement(JavaStatement):
    def __init__(self, expr=None, tt=None):
        self.expr = expr
        self.tt = tt

    def print_(self): return 'return {};'.format(self.expr.print_()) if self.expr is not None else 'return;'

    def addCastsAndParens(self, env):
        if self.expr is not None:
            self.expr.addCasts(env)
            if not isJavaAssignable(env, self.expr.dtype, self.tt):
                self.expr = makeCastExpr(self.tt, self.expr)
            self.expr.addParens()

class ThrowStatement(JavaStatement):
    def __init__(self, expr):
        self.expr = expr
    def print_(self): return 'throw {};'.format(self.expr.print_())

class JumpStatement(JavaStatement):
    def __init__(self, target, isFront):
        self.target = target 
        self.isFront = isFront

    def getTarget(self): return self.redirect[0]

    def print_(self):
        keyword = 'continue' if self.isFront else 'break'
        if self.target is not None:
            return '{} {};'.format(keyword, self.target.getLabel())
        else:
            return keyword + ';'

#Compound Statements
class LazyLabelBase(JavaStatement):
    def __init__(self, labelfunc):
        self.label, self.func = None, labelfunc
        self.sources = {False:[], True:[]}

    def getSources(self): return self.sources[False] + self.sources[True]
    # See if there are any blocks that can jump only to us
    def hasDependents(self): return any(len(child.jumps) == 1 for child in self.getSources())

    def getLabel(self):
        if self.label is None:
            self.label = self.func() #Not a bound function!
        return self.label

    def getLabelPrefix(self): return '' if self.label is None else self.label + ': '
    # def getLabelPrefix(self): 
    #     return '{} //{}\n'.format(self._getLabelPrefix(), self)

    #For debugging
    def __str__(self):
        if isinstance(self, StatementBlock):
            return 'Sb'+str(self.id)
        return type(self).__name__[:3]
        # return type(self).__name__[:3] + str(self.getScopes()[0].id)
    __repr__ = __str__

class TryStatement(LazyLabelBase):
    def __init__(self, labelfunc):
        super(TryStatement, self).__init__(labelfunc)
        # self.tryb, self.pairs

    def getScopes(self): return (self.tryb,) + zip(*self.pairs)[1]

    def print_(self): 
        tryb = self.tryb.print_()
        parts = ['catch({})\n{}'.format(x.print_(), y.print_()) for x,y in self.pairs]
        return '{}try\n{}\n{}'.format(self.getLabelPrefix(), tryb, '\n'.join(parts))

class IfStatement(LazyLabelBase):
    def __init__(self, labelfunc, expr):
        super(IfStatement, self).__init__(labelfunc)
        self.expr = expr #don't rename without changing how var replacement works!
        # self.scopes = scopes
        # assert(len(self.scopes) == 1 or len(self.scopes) == 2)

    def getScopes(self): return self.scopes

    def print_(self): 
        parts = (self.expr,) + tuple(self.scopes)
        parts = [x.print_() for x in parts]
        if len(self.scopes) == 1:
            return '{}if({})\n{}'.format(self.getLabelPrefix(), *parts) 
        return '{}if({})\n{}\nelse\n{}'.format(self.getLabelPrefix(), *parts)

class SwitchStatement(LazyLabelBase):
    def __init__(self, labelfunc, expr):
        super(SwitchStatement, self).__init__(labelfunc)
        self.expr = expr #don't rename without changing how var replacement works!
        #self.pairs = (keys, scope)*

    def getScopes(self): return zip(*self.pairs)[1]

    def print_(self): 
        expr = self.expr.print_()

        def printCase(keys):
            if keys is None:
                return 'default: '
            return ''.join(map('case {}: '.format, sorted(keys)))

        bodies = [(printCase(keys) + scope.print_()) for keys, scope in self.pairs]
        if self.pairs[-1][0] is None and len(self.pairs[-1][1].statements) == 0:
            bodies.pop()

        contents = '\n'.join(bodies)
        indented = ['    '+line for line in contents.splitlines()]
        lines = ['{'] + indented + ['}']
        return '{}switch({}){}'.format(self.getLabelPrefix(), expr, '\n'.join(lines))

class WhileStatement(LazyLabelBase):
    def __init__(self, labelfunc):
        super(WhileStatement, self).__init__(labelfunc)
        self.expr = Literal.TRUE
        # self.parts = block,
    def getScopes(self): return self.parts

    def print_(self): 
        parts = self.expr.print_(), self.parts[0].print_()
        return '{}while({})\n{}'.format(self.getLabelPrefix(), *parts)

sbcount = itertools.count()
class StatementBlock(LazyLabelBase):
    def __init__(self, labelfunc):
        super(StatementBlock, self).__init__(labelfunc)
        self.jumps = [None] #Only fallthrough by default
        self.parent = None #should be assigned later
        #self.statements
        self.id = next(sbcount) #For debugging purposes

    def canFallthrough(self): return None in self.jumps

    def _updateJump(self, jump, func):
        func(self.jumps, jump)
        if jump is not None:
            func(jump[0].sources[jump[1]], self)
        assert(len(set(self.jumps)) == len(self.jumps))

    def removeJump(self, jump): self._updateJump(jump, list.remove)
    def addJump(self, jump): self._updateJump(jump, list.append)

    def setBreaks(self, vals):
        for jump in self.jumps[:]:
            self.removeJump(jump)
        for jump in vals:
            self.addJump(jump)

    def getScopes(self): return self,

    def print_(self): 
        contents = [x.print_() for x in self.statements]

        jump = self.jumps[-1]
        if jump is not None:
            temp = JumpStatement(*jump)
            contents.append(temp.print_())
        contents = '\n'.join(contents)
        # contents = '//{} <- {}\n'.format(str(self), ', '.join(map(str, self.sources[False]))) + contents
        indented = ['    '+line for line in contents.splitlines()]
        lines = [self.getLabelPrefix() + '{'] + indented + ['}']
        return '\n'.join(lines)

    @staticmethod
    def join(*scopes):
        blists = [s.bases for s in scopes if s is not None] #allow None to represent the universe (top element)
        if not blists:
            return None
        common = [x for x in zip(*blists) if len(set(x)) == 1]
        return common[-1][0]

#Temporary hack
class StringStatement(JavaStatement):
    def __init__(self, s):
        self.s = s
    def print_(self): return self.s

#############################################################################################################################################
_assignable_sprims = '.byte','.short','.char'
_assignable_lprims = '.int','.long','.float','.double'

def isJavaAssignable(env, fromt, to):
    if fromt is None or to is None: #this should never happen, except during debugging
        return True

    if to[1] or to[0][0] != '.':
        #todo - make it check interfaces too
        return objtypes.isSubtype(env, fromt, to)
    else: #allowed if numeric conversion is widening
        x, y = fromt[0], to[0]
        if x==y or (x in _assignable_sprims and y in _assignable_lprims):
            return True
        elif (x in _assignable_lprims and y in _assignable_lprims):
            return _assignable_lprims.index(x) <= _assignable_lprims.index(y)
        else:
            return x == '.byte' and y == '.short'

_int_tts = objtypes.LongTT, objtypes.IntTT, objtypes.ShortTT, objtypes.CharTT, objtypes.ByteTT
def makeCastExpr(newtt, expr):
    if newtt == expr.dtype:
        return expr

    if isinstance(expr, Literal) and newtt in (objtypes.IntTT, objtypes.BoolTT):
        return Literal(newtt, expr.val)

    if newtt == objtypes.IntTT and expr.dtype == objtypes.BoolTT:
        return Ternary(expr, Literal.ONE, Literal.ZERO)    
    elif newtt == objtypes.BoolTT and expr.dtype == objtypes.IntTT:
        return BinaryInfix('!=', (expr, Literal.ZERO), objtypes.BoolTT)
    return Cast(TypeName(newtt), expr)
#############################################################################################################################################
#Precedence:
#    0 - pseudoprimary
#    5 - pseudounary
#    10-19 binary infix
#    20 - ternary
#    21 - assignment
# Associativity: L = Left, R = Right, A = Full

class JavaExpression(object):
    precedence = 0 #Default precedence
    params = () #for subclasses that don't have params

    def complexity(self): return 1 + max(e.complexity() for e in self.params) if self.params else 0

    def postFlatIter(self):
        return itertools.chain([self], *[expr.postFlatIter() for expr in self.params])

    def print_(self): 
        return self.fmt.format(*[expr.print_() for expr in self.params])

    def replaceSubExprs(self, rdict):
        if self in rdict:
            return rdict[self]
        self.params = [param.replaceSubExprs(rdict) for param in self.params]
        return self

    def addCasts(self, env):
        for param in self.params:
            param.addCasts(env)
        self.addCasts_sub(env)

    def addCasts_sub(self, env): pass

    def addParens(self):
        for param in self.params:
            param.addParens()      
        self.params = list(self.params) #make it easy for children to edit  
        self.addParens_sub()

    def addParens_sub(self): pass

    def __repr__(self):
        return type(self).__name__.rpartition('.')[-1] + ' ' + self.print_()
    __str__ = __repr__

class ArrayAccess(JavaExpression):
    def __init__(self, *params):
        if params[0].dtype == objtypes.NullTT:
            #Unfortunately, Java doesn't really support array access on null constants
            #So we'll just cast it to Object[] as a hack
            param = makeCastExpr(('java/lang/Object',1), params[0])
            params = param, params[1]

        base, dim = params[0].dtype
        assert(dim >= 1)
        self.dtype = base, dim-1
        self.params = params
        self.fmt = '{}[{}]'

    def addParens_sub(self):
        p0 = self.params[0]
        if p0.precedence > 0 or isinstance(p0, ArrayCreation):
            self.params[0] = Parenthesis(p0)

class ArrayCreation(JavaExpression):
    def __init__(self, tt, *sizeargs):
        base, dim = tt
        self.params = (TypeName((base,0)),) + sizeargs
        self.dtype = tt
        assert(dim >= len(sizeargs) > 0)
        self.fmt = 'new {}' + '[{}]'*len(sizeargs) + '[]'*(dim-len(sizeargs))

class Assignment(JavaExpression):
    precedence = 21
    def __init__(self, *params):
        self.params = params
        self.fmt = '{} = {}'
        self.dtype = params[0].dtype

    def addCasts_sub(self, env):
        left, right = self.params
        if not isJavaAssignable(env, right.dtype, left.dtype):
            expr = makeCastExpr(left.dtype, right)
            self.params = left, expr

_binary_ptable = ['* / %', '+ -', '<< >> >>>', 
    '< > <= >= instanceof', '== !=', 
    '&', '^', '|', '&&', '||']

binary_precedences = {}
for _ops, _val in zip(_binary_ptable, range(10,20)):
    for _op in _ops.split():
        binary_precedences[_op] = _val

class BinaryInfix(JavaExpression):
    def __init__(self, opstr, params, dtype=None):
        self.params = params
        self.opstr = opstr
        self.fmt = '{{}} {} {{}}'.format(opstr)
        self.dtype = params[0].dtype if dtype is None else dtype
        self.precedence = binary_precedences[opstr]

    def addParens_sub(self):
        myprec = self.precedence
        associative = myprec >= 15 #for now we treat +, *, etc as nonassociative due to floats

        for i, p in enumerate(self.params):
            if p.precedence > myprec:
                self.params[i] = Parenthesis(p)
            elif p.precedence == myprec and i>0 and not associative:
                self.params[i] = Parenthesis(p)

class Cast(JavaExpression):
    precedence = 5
    def __init__(self, *params):
        self.dtype = params[0].tt
        self.params = params
        self.fmt = '({}){}'

    def addCasts_sub(self, env):
        tt, expr = self.dtype, self.params[1]
        # "Impossible" casts are a compile error in Java. 
        # This can be fixed with an intermediate cast to Object
        if not isJavaAssignable(env, tt, expr.dtype):
            if not isJavaAssignable(env, expr.dtype, tt):
                expr = makeCastExpr(objtypes.ObjectTT, expr)
                self.params = self.params[0], expr

    def addParens_sub(self):
        p1 = self.params[1]
        if p1.precedence > 5 or (isinstance(p1, UnaryPrefix) and p1.opstr[0] in '-+'):
            self.params[1] = Parenthesis(p1)

class ClassInstanceCreation(JavaExpression):
    def __init__(self, typename, tts, arguments):
        self.typename, self.tts, self.params = typename, tts, arguments
        self.dtype = typename.tt
    def print_(self): 
        return 'new {}({})'.format(self.typename.print_(), ', '.join(x.print_() for x in self.params))

    def addCasts_sub(self, env):
        newparams = []
        for tt, expr in zip(self.tts, self.params):
            if expr.dtype != tt:
                expr = makeCastExpr(tt, expr)
            newparams.append(expr)
        self.params = newparams

class FieldAccess(JavaExpression):
    def __init__(self, primary, name, dtype, printLeft=True):
        self.dtype = dtype
        self.params, self.name = [primary], escapeString(name)
        self.fmt = ('{}.' if printLeft else '') + self.name

    def addParens_sub(self):
        p0 = self.params[0]
        if p0.precedence > 0:
            self.params[0] = Parenthesis(p0)

def printFloat(x, isSingle):
    import math
    name = 'Float' if isSingle else 'Double'
    if math.isnan(x):
        return name + '.NaN'
    elif math.isinf(x):
        if x < 0:
            return name + '.NEGATIVE_INFINITY'
        return name + '.POSITIVE_INFINITY'
    suffix = 'f' if isSingle else ''
    return repr(x) + suffix

class Literal(JavaExpression):
    def __init__(self, vartype, val):
        self.dtype = vartype
        self.val = val

        self.str = None
        if vartype == objtypes.StringTT:
            self.str = '"' + escapeString(val) + '"'
        elif vartype == objtypes.IntTT:
            self.str = repr(int(val))   
            assert('L' not in self.str) #if it did we were passed an invalid value anyway
        elif vartype == objtypes.LongTT:
            self.str = repr(long(val))  
            assert('L' in self.str)
        elif vartype == objtypes.FloatTT or vartype == objtypes.DoubleTT:
            assert(type(val) == float)
            self.str = printFloat(val, vartype == objtypes.FloatTT)
        elif vartype == objtypes.NullTT:
            self.str = 'null'
        elif vartype == objtypes.ClassTT:
            self.params = [TypeName(val)]
            self.fmt = '{}.class'
        elif vartype == objtypes.BoolTT:
            self.str = 'true' if val else 'false'
        else:
            assert(0)

    def print_(self):
        if self.str is None:
            #for printing class literals
            return self.fmt.format(self.params[0].print_())
        return self.str

    def _key(self): return self.dtype, self.val
    def __eq__(self, other): return type(self) == type(other) and self._key() == other._key()
    def __ne__(self, other): return type(self) != type(other) or self._key() != other._key()
    def __hash__(self): return hash(self._key())   
Literal.FALSE = Literal(objtypes.BoolTT, 0)
Literal.TRUE = Literal(objtypes.BoolTT, 1)
Literal.N_ONE = Literal(objtypes.IntTT, -1)
Literal.ZERO = Literal(objtypes.IntTT, 0)
Literal.ONE = Literal(objtypes.IntTT, 1)

Literal.FZERO = Literal(objtypes.FloatTT, 0.0)
Literal.DZERO = Literal(objtypes.DoubleTT, 0.0)
Literal.NULL = Literal(objtypes.NullTT, None)

class Local(JavaExpression):
    def __init__(self, vartype, namefunc):
        self.dtype = vartype
        self.name = None
        self.func = namefunc

    def print_(self):
        if self.name is None:
            self.name = self.func(self)
        return self.name

class MethodInvocation(JavaExpression):
    def __init__(self, left, name, tts, arguments, op, dtype):
        if left is None:
            self.params = arguments
        else:
            self.params = [left] + arguments
        self.hasLeft = (left is not None)
        self.dtype = dtype
        self.name = escapeString(name)
        self.tts = tts
        self.op = op #keep around for future reference and new merging

    def print_(self): 
        if self.hasLeft:
            left, arguments = self.params[0], self.params[1:] 
            return '{}.{}({})'.format(left.print_(), self.name, ', '.join(x.print_() for x in arguments))
        else:
            arguments = self.params
            return '{}({})'.format(self.name, ', '.join(x.print_() for x in arguments))         

    def addCasts_sub(self, env):
        newparams = []
        for tt, expr in zip(self.tts, self.params):
            if expr.dtype != tt:
                expr = makeCastExpr(tt, expr)
            newparams.append(expr)
        self.params = newparams

    def addParens_sub(self):
        if self.hasLeft:
            p0 = self.params[0]
            if p0.precedence > 0:
                self.params[0] = Parenthesis(p0)

class Parenthesis(JavaExpression):
    def __init__(self, param):
        self.dtype = param.dtype
        self.params = param,
        self.fmt = '({})'

class Ternary(JavaExpression):
    precedence = 20
    def __init__(self, *params):
        self.params = params
        self.fmt = '{}?{}:{}'
        self.dtype = params[1].dtype

    def addParens_sub(self):
        if self.params[0].precedence >= 20:
            self.params[0] = Parenthesis(self.params[0])
        if self.params[2].precedence > 20:
            self.params[2] = Parenthesis(self.params[2])

class TypeName(JavaExpression):
    def __init__(self, tt):
        self.dtype = None
        self.tt = tt
        name, dim = tt
        if name[0] == '.': #primative type:
            name = name[1:]
        else:
            name = escapeString(name.replace('/','.'))
        s = name + '[]'*dim
        if s.rpartition('.')[0] == 'java.lang':
            s = s.rpartition('.')[2]
        self.str = s

    def print_(self): return self.str
    def complexity(self): return -1 #exprs which have this as a param won't be bumped up to 1 uncessarily

class CatchTypeNames(JavaExpression): #Used for caught exceptions, which can have multiple types specified
    def __init__(self, env, tts):
        assert(tts and not any(zip(*tts)[1])) #at least one type, no array types
        self.tnames = map(TypeName, tts)
        self.dtype = objtypes.commonSupertype(env, tts)

    def print_(self):
        return ' | '.join(tn.print_() for tn in self.tnames)

class UnaryPrefix(JavaExpression):
    precedence = 5
    def __init__(self, opstr, param, dtype=None):
        self.params = [param]
        self.opstr = opstr
        self.fmt = opstr + '{}'
        self.dtype = param.dtype if dtype is None else dtype

    def addParens_sub(self):
        p0 = self.params[0]
        if p0.precedence > 5 or (isinstance(p0, UnaryPrefix) and p0.opstr[0] == self.opstr[0]):
            self.params[0] = Parenthesis(p0)


class Dummy(JavaExpression):
    def __init__(self, fmt, params, isNew=False):
        self.params = params
        self.fmt = fmt
        self.isNew = isNew
        self.dtype = None